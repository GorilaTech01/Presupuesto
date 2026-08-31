"""CatalystService: builds the 7-day forward event calendar.

Combines:
  - fixed, publicly pre-announced central bank meeting dates (static config)
  - official U.S. release-calendar dates from FRED (when reachable)
  - ISM's well-known release convention (1st/3rd business day of month) as
    a calendar estimate, clearly labeled as such since ISM has no free
    machine-readable calendar API

Never uses these events to predict a data outcome -- only to flag *when*
uncertainty resolves and to force CONDITIONAL_POST_EVENT behavior around it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

from app.common.errors import DataSourceUnavailable
from app.common.time_utils import to_local
from app.domain.enums import CatalystSeverity
from app.domain.models import CatalystEvent, FactObservation
from app.sources.fred.client import FredClient

DEFAULT_CALENDAR_CONFIG = (
    Path(__file__).resolve().parents[2] / "config" / "central_bank_calendar_2026.yaml"
)

# indicator -> (country, severity, source label, source url)
INDICATOR_META: dict[str, tuple[str, CatalystSeverity, str, str]] = {
    "us_nonfarm_payrolls": (
        "US",
        CatalystSeverity.CRITICAL,
        "BLS Employment Situation",
        "https://www.bls.gov/ces/",
    ),
    "us_cpi_yoy": ("US", CatalystSeverity.CRITICAL, "BLS CPI", "https://www.bls.gov/cpi/"),
    "us_core_pce_price_index": (
        "US",
        CatalystSeverity.HIGH,
        "BEA Personal Income and Outlays",
        "https://www.bea.gov/data/personal-consumption-expenditures-price-index",
    ),
    "us_jolts_openings": ("US", CatalystSeverity.MEDIUM, "BLS JOLTS", "https://www.bls.gov/jlt/"),
    "us_initial_claims": (
        "US",
        CatalystSeverity.LOW,
        "DOL Unemployment Insurance Weekly Claims",
        "https://oui.doleta.gov/unemploy/claims.asp",
    ),
    "us_ism_manufacturing_pmi": (
        "US",
        CatalystSeverity.HIGH,
        "ISM Manufacturing Report On Business",
        "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/",
    ),
    "us_ism_services_pmi": (
        "US",
        CatalystSeverity.HIGH,
        "ISM Services Report On Business",
        "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/",
    ),
}

# What kind of surprise favors/weakens/invalidates a thesis that is LONG the
# given country's currency. Direction is inverted by the caller when the
# thesis is SHORT that currency instead.
_HAWKISH_ABOVE_CONSENSUS = {
    "us_nonfarm_payrolls",
    "us_cpi_yoy",
    "us_core_pce_price_index",
    "us_jolts_openings",
    "us_ism_manufacturing_pmi",
    "us_ism_services_pmi",
}
_HAWKISH_BELOW_CONSENSUS = {"us_initial_claims"}


def hawkish_direction_for_indicator(indicator: str) -> str | None:
    """Returns "above" if a print above consensus is the hawkish/currency-
    supportive surprise for this indicator, "below" if a print below
    consensus is, or None if this indicator has no documented directionality
    (e.g. a central bank rate decision, which isn't a consensus-vs-actual
    surprise in the same sense). Shared with `app.monitor.trigger_evaluator`
    so the monitoring layer's confirm/contradict logic uses the exact same
    table this module already uses for `favors_thesis_if` text, rather than
    a second, potentially-diverging copy.
    """
    if indicator in _HAWKISH_ABOVE_CONSENSUS:
        return "above"
    if indicator in _HAWKISH_BELOW_CONSENSUS:
        return "below"
    return None


@dataclass
class _RawEvent:
    indicator: str
    country: str
    severity: CatalystSeverity
    date_utc: datetime
    source: str
    source_url: str


def _nth_business_day(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    count = 0
    while True:
        if d.weekday() < 5:
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


class CatalystService:
    def __init__(
        self, fred_client: FredClient | None, calendar_config: Path = DEFAULT_CALENDAR_CONFIG
    ) -> None:
        self.fred_client = fred_client
        self._config = yaml.safe_load(calendar_config.read_text())

    def _central_bank_events(self, horizon_days: int) -> list[_RawEvent]:
        today = datetime.now(UTC).date()
        events: list[_RawEvent] = []
        for bank_key, meta in (
            ("fomc", ("US", "Federal Reserve (FOMC)")),
            ("ecb", ("EZ", "ECB Governing Council")),
        ):
            block = self._config.get(bank_key, {})
            country, source = meta
            for meeting in block.get("meetings", []):
                d = datetime.strptime(meeting["decision_date"], "%Y-%m-%d").replace(tzinfo=UTC)
                if 0 <= (d.date() - today).days <= horizon_days:
                    events.append(
                        _RawEvent(
                            indicator=f"{bank_key}_rate_decision",
                            country=country,
                            severity=CatalystSeverity.CRITICAL,
                            date_utc=d,
                            source=source,
                            source_url=block.get("source_url", ""),
                        )
                    )
        return events

    def _ism_events(self, indicators: list[str], horizon_days: int) -> list[_RawEvent]:
        wanted = {"us_ism_manufacturing_pmi", "us_ism_services_pmi"} & set(indicators)
        if not wanted:
            return []
        today = datetime.now(UTC).date()
        events: list[_RawEvent] = []
        for year, month in {(today.year, today.month), _next_month(today)}:
            manufacturing = _nth_business_day(year, month, 1)
            services = _nth_business_day(year, month, 3)
            for d, indicator in (
                (manufacturing, "us_ism_manufacturing_pmi"),
                (services, "us_ism_services_pmi"),
            ):
                if indicator not in wanted:
                    continue
                dt = datetime(d.year, d.month, d.day, 15, 0, tzinfo=UTC)  # ISM releases ~10:00 ET
                if 0 <= (dt.date() - today).days <= horizon_days:
                    country, severity, source, url = INDICATOR_META[indicator]
                    events.append(
                        _RawEvent(
                            indicator, country, severity, dt, source + " (estimated date)", url
                        )
                    )
        return events

    def _fred_release_events(self, indicators: list[str], horizon_days: int) -> list[_RawEvent]:
        events: list[_RawEvent] = []
        if self.fred_client is None:
            return events
        for indicator in indicators:
            if indicator not in INDICATOR_META:
                continue
            country, severity, source, url = INDICATOR_META[indicator]
            try:
                dates = self.fred_client.fetch_upcoming_release_dates(indicator, horizon_days)
            except DataSourceUnavailable:
                continue
            for d in dates:
                events.append(_RawEvent(indicator, country, severity, d, source, url))
        return events

    def build_calendar(
        self,
        indicators: list[str],
        *,
        horizon_days: int = 7,
        timezone_name: str = "America/Costa_Rica",
        facts: dict[str, FactObservation] | None = None,
    ) -> list[CatalystEvent]:
        facts = facts or {}
        raw = (
            self._central_bank_events(horizon_days)
            + self._fred_release_events(indicators, horizon_days)
            + self._ism_events(indicators, horizon_days)
        )
        raw.sort(key=lambda e: e.date_utc)
        events: list[CatalystEvent] = []
        for r in raw:
            fact = facts.get(r.indicator)
            events.append(
                CatalystEvent(
                    symbol_context=r.country,
                    date_utc=r.date_utc,
                    date_local=to_local(r.date_utc, timezone_name),
                    country=r.country,
                    indicator=r.indicator,
                    severity=r.severity,
                    actual=fact.value if fact else None,
                    consensus=fact.consensus if fact else None,
                    previous=fact.revised_previous if fact else None,
                    source=r.source,
                    source_url=r.source_url,
                )
            )
        return events


def annotate_thesis_impact(
    events: list[CatalystEvent], *, favored_country: str, direction_label: str
) -> list[CatalystEvent]:
    """Fill favors/weakens/invalidates fields once the thesis direction is known.

    `favored_country` is the country whose currency/asset the thesis wants
    to be relatively strong (e.g. "US" for a long-USD thesis).
    """
    annotated: list[CatalystEvent] = []
    for e in events:
        is_favored_side = e.country == favored_country
        hawkish_is_favorable = is_favored_side  # a hawkish surprise on the favored side helps it
        if e.indicator in _HAWKISH_ABOVE_CONSENSUS:
            favors = "prints ABOVE consensus" if hawkish_is_favorable else "prints BELOW consensus"
            weakens = "prints roughly in line with consensus"
            invalidates = (
                "prints BELOW consensus" if hawkish_is_favorable else "prints ABOVE consensus"
            )
        elif e.indicator in _HAWKISH_BELOW_CONSENSUS:
            favors = "prints BELOW consensus" if hawkish_is_favorable else "prints ABOVE consensus"
            weakens = "prints roughly in line with consensus"
            invalidates = (
                "prints ABOVE consensus" if hawkish_is_favorable else "prints BELOW consensus"
            )
        else:  # rate decisions and anything else: unscheduled surprise vs. hold
            favors = f"outcome reinforces the {direction_label} thesis for {favored_country}"
            weakens = "outcome is broadly neutral/as expected"
            invalidates = (
                f"outcome directly contradicts the {direction_label} thesis for {favored_country}"
            )
        annotated.append(
            e.model_copy(
                update={
                    "favors_thesis_if": f"{e.indicator} {favors}",
                    "weakens_thesis_if": f"{e.indicator} {weakens}",
                    "invalidates_thesis_if": f"{e.indicator} {invalidates}",
                }
            )
        )
    return annotated


def _next_month(d: date) -> tuple[int, int]:
    if d.month == 12:
        return d.year + 1, 1
    return d.year, d.month + 1
