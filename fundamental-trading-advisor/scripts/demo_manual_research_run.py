"""Manual-research demonstration run for the week of 2026-08-31 to 2026-09-04.

WHY THIS SCRIPT EXISTS
-----------------------
`python -m app weekly` calls live official APIs (FRED, ECB, Eurostat, EIA,
CFTC) over the network. The sandbox this project was originally built in
blocks all outbound HTTPS to those hosts, so a live run there correctly
fails closed to NO_TRADE (see README section 8) -- that IS the fail-closed
architecture working as designed, but it is not a useful demonstration of
what the *scoring and decision* logic actually does with real numbers.

This script plugs real, currently-published figures (gathered by hand via
web research on 2026-08-29, each with its source cited below) into the
exact same normalized-fact / scoring / catalyst / decision / risk pipeline
`app.services.weekly_pipeline.WeeklyPipeline` uses internally -- it does
NOT call any network API itself. Treat this as "what the system would have
produced that week with a working internet connection", not as a
replacement for the real `weekly` command.

It intentionally does NOT hardcode a directional conclusion: the figures
below are what was actually published for the reference week, and the
decision at the bottom is whatever the deterministic scoring/decision
engine computes from them.

Sources (retrieved 2026-08-29):
  - Fed funds target 3.50-3.75%, held at the Jul 28-29, 2026 FOMC meeting:
    https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm
  - US CPI July 2026: headline 3.4% YoY (prior 3.5%), core 2.5% YoY (prior 2.6%):
    https://www.bls.gov/news.release/cpi.nr0.htm
  - US unemployment 4.1% (July, prior 4.2%); NFP -23k (July, vs +83k consensus):
    https://www.bls.gov/news.release/empsit.htm
  - JOLTS job openings ~7.40M (June 2026, "little changed"):
    https://www.bls.gov/news.release/jolts.nr0.htm
  - US 10Y yield 4.69%, 10Y TIPS (real) yield 2.34% (Aug 28, 2026):
    https://home.treasury.gov/resource-center/data-chart-center/interest-rates
  - Broad USD index ~99.6 (early Aug), down from ~101.70 (late Jul):
    https://www.federalreserve.gov/releases/h10/
  - US core PCE for July 2026: secondary sources disagreed (2.9% vs 3.3%
    YoY across different aggregators) -- treated as CONTRADICTORY and
    excluded per section 33/9 of the spec, not guessed.
  - ECB deposit facility rate 2.25% (held in July, hiked from 2.00% in June):
    https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260611~4d41bd5e83.en.html
  - Eurozone HICP July 2026: headline 2.9% YoY (prior 2.8%), core 2.5% YoY (prior 2.4%):
    https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-19082026-ap
  - Eurozone unemployment 6.3% (June 2026, flat vs May):
    https://ec.europa.eu/eurostat/web/products-euro-indicators/w/3-30072026-bp
  - Eurozone GDP +0.4% QoQ in Q2 2026 (accelerating from ~flat in Q1):
    Eurostat flash GDP release, Aug 2026
  - Eurozone retail sales +0.7% YoY (June 2026):
    https://ec.europa.eu/eurostat/web/products-euro-indicators/w/4-06082026-ap
  - August 2026 NFP (released 2026-09-04, the critical catalyst for this
    week) was forecast at +90k, unemployment seen unchanged at 4.2%:
    https://www.financecalendar.com/event/us-employment-situation-non-farm-payrolls-august-2026/
  - EURUSD spot ~1.1583 on 2026-08-28 (approximate, for demo math only --
    NOT to be used for real execution; re-verify live in MT5):
    https://tradingeconomics.com/euro-area/currency

Run: `uv run python scripts/demo_manual_research_run.py`
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.broker.symbol_resolver import BrokerSymbolResolver
from app.catalysts.service import annotate_thesis_impact
from app.domain.enums import AssetClass, CatalystSeverity, Direction, Freshness, ObservationKind
from app.domain.models import CatalystEvent, FactObservation, TradePlan
from app.fundamental import analysis
from app.fundamental.decision import FundamentalDecisionEngine
from app.market.price_provider import PriceQuote
from app.risk.trade_math import build_trade_math
from app.sources.repository import FetchResult

RETRIEVED_AT = datetime(2026, 8, 29, tzinfo=UTC)


def fact(
    indicator: str,
    value: float,
    *,
    country: str,
    unit: str,
    source: str,
    source_url: str,
    publication: datetime,
    previous: float | None = None,
) -> FactObservation:
    return FactObservation(
        indicator=indicator,
        country=country,
        asset_relevance=[],
        source=source,
        source_url=source_url,
        publication_timestamp=publication,
        observation_period=publication.strftime("%Y-%m"),
        kind=ObservationKind.ACTUAL,
        value=value,
        unit=unit,
        consensus=None,
        revised_previous=previous,
        freshness=Freshness.FRESH,
        retrieval_timestamp=RETRIEVED_AT,
    )


BLS = "BLS"
FED = "Federal Reserve"
TREASURY = "U.S. Treasury / FRB H.15"
ECB = "ECB"
EUROSTAT = "Eurostat"

us_facts = {
    "us_fed_funds_target_upper": fact(
        "us_fed_funds_target_upper",
        3.75,
        country="US",
        unit="percent",
        source=FED,
        source_url="https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm",
        publication=datetime(2026, 7, 29, tzinfo=UTC),
        previous=3.75,
    ),
    "us_cpi_yoy": fact(
        "us_cpi_yoy",
        3.4,
        country="US",
        unit="percent",
        source=BLS,
        source_url="https://www.bls.gov/news.release/cpi.nr0.htm",
        publication=datetime(2026, 8, 12, tzinfo=UTC),
        previous=3.5,
    ),
    "us_core_cpi_yoy": fact(
        "us_core_cpi_yoy",
        2.5,
        country="US",
        unit="percent",
        source=BLS,
        source_url="https://www.bls.gov/news.release/cpi.nr0.htm",
        publication=datetime(2026, 8, 12, tzinfo=UTC),
        previous=2.6,
    ),
    "us_unemployment_rate": fact(
        "us_unemployment_rate",
        4.1,
        country="US",
        unit="percent",
        source=BLS,
        source_url="https://www.bls.gov/news.release/empsit.htm",
        publication=datetime(2026, 8, 7, tzinfo=UTC),
        previous=4.2,
    ),
    # NFP is conventionally the MoM change (thousands), not a level; we
    # model it here as a "change" fact with a zero baseline so the labor
    # scorer's delta math reduces to the reported change itself.
    "us_nonfarm_payrolls": fact(
        "us_nonfarm_payrolls",
        -23,
        country="US",
        unit="thousands (MoM change)",
        source=BLS,
        source_url="https://www.bls.gov/news.release/empsit.htm",
        publication=datetime(2026, 8, 7, tzinfo=UTC),
        previous=0,
    ),
    "us_jolts_openings": fact(
        "us_jolts_openings",
        7400,
        country="US",
        unit="thousands",
        source=BLS,
        source_url="https://www.bls.gov/news.release/jolts.nr0.htm",
        publication=datetime(2026, 8, 5, tzinfo=UTC),
        previous=7350,
    ),
    "us_real_10y_yield": fact(
        "us_real_10y_yield",
        2.34,
        country="US",
        unit="percent",
        source=TREASURY,
        source_url="https://home.treasury.gov/resource-center/data-chart-center/interest-rates",
        publication=datetime(2026, 8, 28, tzinfo=UTC),
        previous=2.43,
    ),
    "us_dollar_index_broad": fact(
        "us_dollar_index_broad",
        99.6,
        country="US",
        unit="index",
        source=FED,
        source_url="https://www.federalreserve.gov/releases/h10/",
        publication=datetime(2026, 8, 28, tzinfo=UTC),
        previous=101.70,
    ),
    # us_core_pce_price_index deliberately OMITTED: secondary sources
    # disagreed materially (2.9% vs 3.3%) and no official BEA figure could
    # be confirmed independently -- CONTRADICTORY, so excluded rather than
    # guessed (spec sections 9/33).
}

ez_facts = {
    "ez_deposit_facility_rate": fact(
        "ez_deposit_facility_rate",
        2.25,
        country="EZ",
        unit="percent",
        source=ECB,
        source_url="https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260611~4d41bd5e83.en.html",
        publication=datetime(2026, 7, 23, tzinfo=UTC),
        previous=2.00,
    ),
    "ez_hicp_headline_yoy": fact(
        "ez_hicp_headline_yoy",
        2.9,
        country="EZ",
        unit="percent",
        source=EUROSTAT,
        source_url="https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-19082026-ap",
        publication=datetime(2026, 8, 19, tzinfo=UTC),
        previous=2.8,
    ),
    "ez_hicp_core_yoy": fact(
        "ez_hicp_core_yoy",
        2.5,
        country="EZ",
        unit="percent",
        source=EUROSTAT,
        source_url="https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-19082026-ap",
        publication=datetime(2026, 8, 19, tzinfo=UTC),
        previous=2.4,
    ),
    "ez_unemployment_rate": fact(
        "ez_unemployment_rate",
        6.3,
        country="EZ",
        unit="percent",
        source=EUROSTAT,
        source_url="https://ec.europa.eu/eurostat/web/products-euro-indicators/w/3-30072026-bp",
        publication=datetime(2026, 7, 30, tzinfo=UTC),
        previous=6.3,
    ),
    "ez_gdp_growth_yoy": fact(
        "ez_gdp_growth_yoy",
        0.4,  # QoQ, not YoY -- Eurostat flash estimate; see README note on units
        country="EZ",
        unit="percent (QoQ, flash)",
        source=EUROSTAT,
        source_url="https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Eurostatistics_-_data_for_short-term_economic_analysis",
        publication=datetime(2026, 8, 14, tzinfo=UTC),
        previous=0.0,
    ),
    "ez_retail_sales_yoy": fact(
        "ez_retail_sales_yoy",
        0.7,
        country="EZ",
        unit="percent",
        source=EUROSTAT,
        source_url="https://ec.europa.eu/eurostat/web/products-euro-indicators/w/4-06082026-ap",
        publication=datetime(2026, 8, 6, tzinfo=UTC),
        previous=None,
    ),
}

gold_facts = {
    "us_real_10y_yield": us_facts["us_real_10y_yield"],
    "us_dollar_index_broad": us_facts["us_dollar_index_broad"],
    "us_cpi_yoy": us_facts["us_cpi_yoy"],
    "us_core_cpi_yoy": us_facts["us_core_cpi_yoy"],
    # gold_net_noncommercial_positioning deliberately OMITTED: no CFTC
    # figure could be retrieved for this run -- missing, not guessed.
}

btc_facts = {
    "us_fed_funds_target_upper": us_facts["us_fed_funds_target_upper"],
}


def main() -> None:
    eur_result = FetchResult(facts=ez_facts, errors={})
    usd_result = FetchResult(
        facts=us_facts,
        errors={"us_core_pce_price_index": "CONTRADICTORY across secondary sources; excluded"},
    )
    xau_result = FetchResult(
        facts=gold_facts,
        errors={"gold_net_noncommercial_positioning": "no CFTC figure retrieved for this run"},
    )
    btc_result = FetchResult(facts=btc_facts, errors={})

    eur_score = analysis.build_currency_score("EUR", eur_result)
    usd_score = analysis.build_currency_score("USD", usd_result)
    bias = analysis.build_fx_pair_bias(eur_score, usd_score)
    xau_score = analysis.build_xau_score(xau_result)
    btc_score = analysis.build_btc_score(btc_result)

    nfp_event = CatalystEvent(
        symbol_context="US",
        date_utc=datetime(2026, 9, 4, 12, 30, tzinfo=UTC),
        date_local=datetime(2026, 9, 4, 6, 30, tzinfo=UTC),
        country="US",
        indicator="us_nonfarm_payrolls",
        severity=CatalystSeverity.CRITICAL,
        actual=None,
        consensus=90,
        previous=-23,
        source="BLS Employment Situation",
        source_url="https://www.financecalendar.com/event/us-employment-situation-non-farm-payrolls-august-2026/",
    )

    engine = FundamentalDecisionEngine()

    favored = "US" if bias < 0 else "EZ"
    eurusd_catalysts = annotate_thesis_impact(
        [nfp_event], favored_country=favored, direction_label="BUY" if bias > 0 else "SELL"
    )
    eurusd_draft = engine.decide_fx_pair(
        symbol="EURUSD",
        base_ccy="EUR",
        quote_ccy="USD",
        base_score=eur_score,
        quote_score=usd_score,
        bias=bias,
        catalysts=eurusd_catalysts,
        facts_freshness=[f.freshness for f in {**ez_facts, **us_facts}.values()],
    )
    xau_draft = engine.decide_single_asset(
        symbol="XAUUSD",
        score=xau_score,
        catalysts=annotate_thesis_impact([], favored_country="US", direction_label="n/a"),
        facts_freshness=[f.freshness for f in gold_facts.values()],
    )
    btc_draft = engine.decide_single_asset(
        symbol="BTCUSD",
        score=btc_score,
        catalysts=[],
        facts_freshness=[f.freshness for f in btc_facts.values()],
    )

    print("=" * 70)
    print("MANUAL-RESEARCH DEMO RUN -- week of 2026-08-31 to 2026-09-04")
    print("(real published figures, fed through the same scoring/decision")
    print(" pipeline `weekly` uses -- see script docstring for sources)")
    print("=" * 70)
    for label, draft, score in (
        (
            "EURUSD",
            eurusd_draft,
            f"EUR={eur_score.total:+.3f} USD={usd_score.total:+.3f} bias={bias:+.3f}",
        ),
        ("XAUUSD", xau_draft, f"score={xau_score.total:+.3f}"),
        ("BTCUSD", btc_draft, f"score={btc_score.total:+.3f}"),
    ):
        print(f"\n{label}: {draft.direction.value} (conviction {draft.conviction}/100) [{score}]")
        print(f"  {draft.thesis}")

    drafts = {"EURUSD": eurusd_draft, "XAUUSD": xau_draft, "BTCUSD": btc_draft}
    tradeable = {k: v for k, v in drafts.items() if v.direction is not Direction.NO_TRADE}
    if not tradeable:
        print("\n>>> FINAL: NO_TRADE -- no candidate cleared the minimum fundamental asymmetry.")
        return

    winner_symbol = max(tradeable, key=lambda k: tradeable[k].conviction)
    winner_draft = tradeable[winner_symbol]
    print(f"\n>>> FINAL SELECTION: {winner_symbol} {winner_draft.direction.value}")

    if winner_symbol == "EURUSD":
        resolver = BrokerSymbolResolver()
        resolved = resolver.resolve("EURUSD")
        quote = PriceQuote(
            symbol="EURUSD", bid=1.1582, ask=1.1584, as_of=datetime(2026, 8, 28, tzinfo=UTC)
        )
        math_result = build_trade_math(
            direction=winner_draft.direction,
            asset_class=AssetClass.FX,
            mid_price=quote.mid,
            spread=quote.spread,
            spec=resolved.spec,
            account_equity=10_000.0,
            risk_percent=0.005,
            has_critical_catalyst_in_horizon=True,
        )
        if math_result.feasible:
            plan = TradePlan(
                asset="EURUSD",
                symbol=resolved.broker_symbol,
                direction=winner_draft.direction,
                conviction_1_10=max(1, round(winner_draft.conviction / 10)),
                horizon="3-5 trading days (through Fri 2026-09-04 NFP)",
                order_type="Market or limit at estimated entry (manual, in MT5)",
                fundamental_trigger=winner_draft.entry_condition,
                estimated_entry=math_result.entry,
                stop_loss=math_result.stop_loss,
                distance_to_sl=math_result.distance_to_sl,
                take_profit=math_result.take_profit,
                distance_to_tp=math_result.distance_to_tp,
                risk_reward=math_result.risk_reward,
                time_stop=winner_draft.time_stop,
                cancellation_condition=(
                    "Cancel if not triggered by the entry condition before the time stop."
                ),
                fundamental_invalidation=winner_draft.fundamental_invalidation,
                early_exit_condition="Exit early if the Sep 4 NFP/wages print reverses the thesis.",
                main_catalysts=[f"{c.indicator} ({c.country})" for c in winner_draft.catalysts[:3]],
                main_risks=winner_draft.risks,
            )
            print("\nTRADE PLAN")
            for field_name in TradePlan.model_fields:
                print(f"  {field_name}: {getattr(plan, field_name)}")
            print(f"\nNOTE: {resolved.notice}")
        else:
            print(f"\nTrade math infeasible: {math_result.reason} -> treat as NO_TRADE.")


if __name__ == "__main__":
    main()
