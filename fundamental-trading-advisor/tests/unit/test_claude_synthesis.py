from __future__ import annotations

from datetime import UTC, datetime

from app.domain.enums import AssetClass, Direction
from app.domain.models import FundamentalDecision
from app.llm.claude_synthesis import ClaudeSynthesisClient


def _no_trade_decision() -> FundamentalDecision:
    return FundamentalDecision(
        symbol="EURUSD",
        asset_class=AssetClass.FX,
        direction=Direction.NO_TRADE,
        conviction=0,
        horizon="N/A",
        thesis="t",
        top_drivers=[],
        catalysts=[],
        entry_condition="N/A",
        fundamental_invalidation="N/A",
        risks=[],
        time_stop="N/A",
        data_freshness="FRESH",
        sources=[],
        data_cutoff_utc=datetime.now(UTC),
        data_cutoff_local="",
        trade_plan=None,
    )


def test_disabled_without_api_key():
    client = ClaudeSynthesisClient(api_key=None, model="claude-sonnet-4-5")
    assert client.enabled is False
    assert client.synthesize_narrative(_no_trade_decision()) is None
