"""U.S. Bureau of Economic Analysis adapter -- PENDING full implementation.

BEA does offer a free API (https://apps.bea.gov/api/signup/) for GDP,
personal income, etc. It is not wired up in this version because FRED
already mirrors BEA's key series (GDP, PCE) with a simpler contract; see
app.sources.fred. This module exists so the source tree matches the
documented architecture and so a direct BEA integration can be added later
without restructuring.
"""

from __future__ import annotations

from app.common.errors import DataSourceUnavailable
from app.domain.models import FactObservation

INDICATORS = {"us_gdp_growth_annualized", "us_personal_income"}


class BeaClient:
    def fetch_indicator(self, indicator: str) -> FactObservation:
        raise DataSourceUnavailable(
            "bea",
            f"'{indicator}' not implemented directly yet; use FRED-mirrored series "
            "(e.g. GDP via FRED) or add a BEA_API_KEY integration",
        )
