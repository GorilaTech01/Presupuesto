"""ISM (Institute for Supply Management) PMI adapter -- PENDING.

ISM does not publish a free, keyless machine-readable API for its
Manufacturing/Services PMI reports (the headline figures are paywalled /
released via press release only). This adapter intentionally always raises
DataSourceUnavailable so the rest of the pipeline treats ISM data as
missing rather than fabricating a value.

To complete this integration, wire it to either:
  - a licensed ISM data feed, or
  - a manual/CSV entry workflow (analyst pastes the released headline
    figure with its source URL) that still produces a normal
    FactObservation.
"""

from __future__ import annotations

from app.common.errors import DataSourceUnavailable
from app.domain.models import FactObservation

INDICATORS = {"us_ism_manufacturing_pmi", "us_ism_services_pmi", "us_ism_manufacturing_employment"}


class IsmClient:
    def fetch_indicator(self, indicator: str) -> FactObservation:
        raise DataSourceUnavailable(
            "ism",
            f"'{indicator}' has no free official API integrated yet; "
            "requires a licensed feed or manual entry (see module docstring)",
        )
