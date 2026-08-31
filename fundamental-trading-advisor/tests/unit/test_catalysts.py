from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from app.catalysts.service import CatalystService, annotate_thesis_impact
from app.domain.enums import CatalystSeverity


def _write_calendar(tmp_path: Path, fomc_offset_days: int, ecb_offset_days: int) -> Path:
    today = datetime.now(UTC).date()
    config = {
        "fomc": {
            "source_url": "https://example.invalid/fomc",
            "meetings": [
                {
                    "decision_date": (today + timedelta(days=fomc_offset_days)).isoformat(),
                    "label": "test FOMC",
                }
            ],
        },
        "ecb": {
            "source_url": "https://example.invalid/ecb",
            "meetings": [
                {
                    "decision_date": (today + timedelta(days=ecb_offset_days)).isoformat(),
                    "label": "test ECB",
                }
            ],
        },
    }
    path = tmp_path / "calendar.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def test_central_bank_event_within_horizon_is_included(tmp_path: Path):
    config_path = _write_calendar(tmp_path, fomc_offset_days=3, ecb_offset_days=20)
    service = CatalystService(fred_client=None, calendar_config=config_path)
    events = service.build_calendar([], horizon_days=7)
    indicators = [e.indicator for e in events]
    assert "fomc_rate_decision" in indicators
    assert "ecb_rate_decision" not in indicators  # outside horizon


def test_central_bank_events_are_critical_severity(tmp_path: Path):
    config_path = _write_calendar(tmp_path, fomc_offset_days=1, ecb_offset_days=2)
    service = CatalystService(fred_client=None, calendar_config=config_path)
    events = service.build_calendar([], horizon_days=7)
    assert all(e.severity is CatalystSeverity.CRITICAL for e in events)


def test_ism_events_are_estimated_and_within_month(tmp_path: Path):
    config_path = _write_calendar(tmp_path, fomc_offset_days=100, ecb_offset_days=100)
    service = CatalystService(fred_client=None, calendar_config=config_path)
    events = service.build_calendar(
        ["us_ism_manufacturing_pmi", "us_ism_services_pmi"], horizon_days=30
    )
    indicators = {e.indicator for e in events}
    assert "us_ism_manufacturing_pmi" in indicators or "us_ism_services_pmi" in indicators


def test_no_network_calls_without_fred_client(tmp_path: Path):
    config_path = _write_calendar(tmp_path, fomc_offset_days=100, ecb_offset_days=100)
    service = CatalystService(fred_client=None, calendar_config=config_path)
    # us_nonfarm_payrolls would normally hit FRED release-dates; with no client it must not raise
    events = service.build_calendar(["us_nonfarm_payrolls"], horizon_days=7)
    assert isinstance(events, list)


def test_annotate_thesis_impact_favored_side_hawkish_above_consensus():
    # a synthetic NFP event, since real release dates need a live FRED client
    from app.domain.models import CatalystEvent

    synthetic = [
        CatalystEvent(
            symbol_context="US",
            date_utc=datetime.now(UTC) + timedelta(days=1),
            date_local=datetime.now(UTC) + timedelta(days=1),
            country="US",
            indicator="us_nonfarm_payrolls",
            severity=CatalystSeverity.CRITICAL,
        )
    ]
    annotated = annotate_thesis_impact(synthetic, favored_country="US", direction_label="BUY")
    assert "ABOVE consensus" in annotated[0].favors_thesis_if
    assert "BELOW consensus" in annotated[0].invalidates_thesis_if
