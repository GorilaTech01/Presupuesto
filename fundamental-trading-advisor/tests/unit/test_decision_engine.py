from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.enums import CatalystSeverity, Direction, DriverCategory, Freshness, TradeAction
from app.domain.models import CatalystEvent, DriverScore, FundamentalScore
from app.fundamental.decision import FundamentalDecisionEngine


def _score(subject: str, total: float, warnings: list[str] | None = None) -> FundamentalScore:
    driver = DriverScore(
        category=DriverCategory.MONETARY_POLICY,
        label="policy",
        contribution=total,
        rationale="test driver",
        supporting_facts=["TESTSRC:x=1"],
    )
    return FundamentalScore(
        subject=subject,
        total=total,
        drivers=[driver],
        data_cutoff_utc=datetime.now(UTC),
        warnings=warnings or [],
    )


def test_no_trade_when_bias_too_weak():
    engine = FundamentalDecisionEngine()
    eur = _score("EUR", 0.1)
    usd = _score("USD", 0.0)
    draft = engine.decide_fx_pair(
        symbol="EURUSD",
        base_ccy="EUR",
        quote_ccy="USD",
        base_score=eur,
        quote_score=usd,
        bias=0.1,
        catalysts=[],
        facts_freshness=[Freshness.FRESH],
    )
    assert draft.direction is Direction.NO_TRADE
    assert "asymmetry too weak" in draft.reasons[0]


def test_no_trade_when_data_stale():
    engine = FundamentalDecisionEngine()
    eur = _score("EUR", 2.0)
    usd = _score("USD", 0.0)
    draft = engine.decide_fx_pair(
        symbol="EURUSD",
        base_ccy="EUR",
        quote_ccy="USD",
        base_score=eur,
        quote_score=usd,
        bias=2.0,
        catalysts=[],
        facts_freshness=[Freshness.STALE],
    )
    assert draft.direction is Direction.NO_TRADE
    assert "STALE" in draft.reasons[0]


def test_no_trade_when_too_many_warnings():
    engine = FundamentalDecisionEngine()
    eur = _score("EUR", 2.0, warnings=["missing a", "missing b"])
    usd = _score("USD", 0.0)
    draft = engine.decide_fx_pair(
        symbol="EURUSD",
        base_ccy="EUR",
        quote_ccy="USD",
        base_score=eur,
        quote_score=usd,
        bias=2.0,
        catalysts=[],
        facts_freshness=[Freshness.FRESH],
    )
    assert draft.direction is Direction.NO_TRADE
    assert "insufficient evidence" in draft.reasons[0]


def test_buy_when_base_currency_strong_and_data_clean():
    engine = FundamentalDecisionEngine()
    eur = _score("EUR", 2.0)
    usd = _score("USD", 0.0)
    draft = engine.decide_fx_pair(
        symbol="EURUSD",
        base_ccy="EUR",
        quote_ccy="USD",
        base_score=eur,
        quote_score=usd,
        bias=2.0,
        catalysts=[],
        facts_freshness=[Freshness.FRESH],
    )
    assert draft.direction is Direction.BUY
    assert draft.conviction >= 55


def test_sell_when_quote_currency_strong():
    engine = FundamentalDecisionEngine()
    eur = _score("EUR", 0.0)
    usd = _score("USD", 2.0)
    draft = engine.decide_fx_pair(
        symbol="EURUSD",
        base_ccy="EUR",
        quote_ccy="USD",
        base_score=eur,
        quote_score=usd,
        bias=-2.0,
        catalysts=[],
        facts_freshness=[Freshness.FRESH],
    )
    assert draft.direction is Direction.SELL


def test_no_trade_when_critical_catalyst_has_no_consensus():
    engine = FundamentalDecisionEngine()
    eur = _score("EUR", 2.0)
    usd = _score("USD", 0.0)
    critical_event = CatalystEvent(
        symbol_context="US",
        date_utc=datetime.now(UTC) + timedelta(days=1),
        date_local=datetime.now(UTC) + timedelta(days=1),
        country="US",
        indicator="us_nonfarm_payrolls",
        severity=CatalystSeverity.CRITICAL,
        actual=None,
        consensus=None,
    )
    draft = engine.decide_fx_pair(
        symbol="EURUSD",
        base_ccy="EUR",
        quote_ccy="USD",
        base_score=eur,
        quote_score=usd,
        bias=2.0,
        catalysts=[critical_event],
        facts_freshness=[Freshness.FRESH],
    )
    assert draft.direction is Direction.NO_TRADE
    assert "CONSENSUS_UNAVAILABLE" in draft.reasons[0]


def test_conditional_post_event_entry_when_critical_catalyst_has_consensus():
    engine = FundamentalDecisionEngine()
    eur = _score("EUR", 2.0)
    usd = _score("USD", 0.0)
    critical_event = CatalystEvent(
        symbol_context="US",
        date_utc=datetime.now(UTC) + timedelta(days=1),
        date_local=datetime.now(UTC) + timedelta(days=1),
        country="US",
        indicator="us_nonfarm_payrolls",
        severity=CatalystSeverity.CRITICAL,
        actual=None,
        consensus=150.0,
        favors_thesis_if="prints below consensus",
    )
    draft = engine.decide_fx_pair(
        symbol="EURUSD",
        base_ccy="EUR",
        quote_ccy="USD",
        base_score=eur,
        quote_score=usd,
        bias=2.0,
        catalysts=[critical_event],
        facts_freshness=[Freshness.FRESH],
    )
    assert draft.direction is Direction.BUY
    assert "CONDITIONAL_POST_EVENT" in draft.entry_condition
    # audit section 7: BUY must not be read as "enter now" while a CRITICAL
    # catalyst is still pending -- fundamental_bias (direction) and
    # trade_action are distinct.
    assert draft.trade_action is TradeAction.WAIT_FOR_TRIGGER


def test_enter_now_when_no_pending_critical_catalyst():
    engine = FundamentalDecisionEngine()
    eur = _score("EUR", 2.0)
    usd = _score("USD", 0.0)
    draft = engine.decide_fx_pair(
        symbol="EURUSD",
        base_ccy="EUR",
        quote_ccy="USD",
        base_score=eur,
        quote_score=usd,
        bias=2.0,
        catalysts=[],
        facts_freshness=[Freshness.FRESH],
    )
    assert draft.direction is Direction.BUY
    assert draft.trade_action is TradeAction.ENTER_NOW


def test_no_trade_has_none_trade_action_and_no_conviction_breakdown():
    engine = FundamentalDecisionEngine()
    eur = _score("EUR", 0.1)
    usd = _score("USD", 0.0)
    draft = engine.decide_fx_pair(
        symbol="EURUSD",
        base_ccy="EUR",
        quote_ccy="USD",
        base_score=eur,
        quote_score=usd,
        bias=0.1,
        catalysts=[],
        facts_freshness=[Freshness.FRESH],
    )
    assert draft.trade_action is TradeAction.NONE
    assert draft.conviction_breakdown is None


def test_conviction_breakdown_is_fully_populated_and_matches_conviction():
    engine = FundamentalDecisionEngine()
    eur = _score("EUR", 2.0)
    usd = _score("USD", 0.0)
    draft = engine.decide_fx_pair(
        symbol="EURUSD",
        base_ccy="EUR",
        quote_ccy="USD",
        base_score=eur,
        quote_score=usd,
        bias=2.0,
        catalysts=[],
        facts_freshness=[Freshness.FRESH],
    )
    b = draft.conviction_breakdown
    assert b is not None
    assert b.final_conviction == draft.conviction
    assert b.raw_score == 2.0
    assert b.expectations_penalty == 8  # EXPECTATIONS_INCOMPLETE_PENALTY, always applied
    assert b.missing_data_penalty == 0  # no warnings on either synthetic score
    assert b.event_risk_penalty == 0  # no catalysts passed in this test


def test_single_asset_no_trade_on_weak_score():
    engine = FundamentalDecisionEngine()
    score = _score("XAUUSD", 0.05)
    draft = engine.decide_single_asset(
        symbol="XAUUSD", score=score, catalysts=[], facts_freshness=[Freshness.FRESH]
    )
    assert draft.direction is Direction.NO_TRADE


def test_single_asset_sell_on_negative_score():
    engine = FundamentalDecisionEngine()
    score = _score("XAUUSD", -2.0)
    draft = engine.decide_single_asset(
        symbol="XAUUSD", score=score, catalysts=[], facts_freshness=[Freshness.FRESH]
    )
    assert draft.direction is Direction.SELL
