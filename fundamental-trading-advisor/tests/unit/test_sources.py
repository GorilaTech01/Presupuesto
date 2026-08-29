from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.common.cache import DiskCache
from app.common.errors import DataSourceUnavailable
from app.sources.bls.client import BlsClient
from app.sources.cftc.client import CftcClient
from app.sources.ecb.client import EcbClient
from app.sources.eia.client import EiaClient
from app.sources.eurostat.client import EurostatClient
from app.sources.fred.client import FredClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def cache(tmp_path: Path) -> DiskCache:
    return DiskCache(tmp_path / "cache")


# --- FRED ---------------------------------------------------------------


@respx.mock
def test_fred_fetch_indicator_ok(cache: DiskCache):
    payload = json.loads((FIXTURES / "fred_observations.json").read_text())
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = FredClient(api_key="testkey", cache=cache)
    fact = client.fetch_indicator("us_fed_funds_target_upper")
    assert fact.value == 4.00
    assert fact.revised_previous == 3.75
    assert fact.source == "FRED"


def test_fred_missing_api_key_raises(cache: DiskCache):
    client = FredClient(api_key=None, cache=cache)
    with pytest.raises(DataSourceUnavailable):
        client.fetch_indicator("us_fed_funds_target_upper")


@respx.mock
def test_fred_http_error_raises_data_source_unavailable(cache: DiskCache):
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(500)
    )
    client = FredClient(api_key="testkey", cache=cache)
    with pytest.raises(DataSourceUnavailable):
        client.fetch_indicator("us_fed_funds_target_upper")


@respx.mock
def test_fred_yoy_derived_series(cache: DiskCache):
    # 14 monthly observations, descending (latest first), index rising ~3%/yr
    observations = []
    base = 310.0
    for i in range(14):
        observations.append(
            {"date": f"2026-{(8 - i) % 12 + 1:02d}-01", "value": str(round(base - i * 0.2, 2))}
        )
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json={"observations": observations})
    )
    client = FredClient(api_key="testkey", cache=cache)
    fact = client.fetch_indicator("us_cpi_yoy")
    assert fact.unit == "percent"
    assert fact.value is not None


@respx.mock
def test_fred_yoy_series_insufficient_history_raises(cache: DiskCache):
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(
            200, json={"observations": [{"date": "2026-08-01", "value": "310.0"}]}
        )
    )
    client = FredClient(api_key="testkey", cache=cache)
    with pytest.raises(DataSourceUnavailable):
        client.fetch_indicator("us_cpi_yoy")


def test_fred_unknown_indicator_raises(cache: DiskCache):
    client = FredClient(api_key="testkey", cache=cache)
    with pytest.raises(DataSourceUnavailable):
        client.fetch_indicator("not_a_real_indicator")


# --- ECB ------------------------------------------------------------------


@respx.mock
def test_ecb_fetch_indicator_ok(cache: DiskCache):
    payload = json.loads((FIXTURES / "ecb_sdmx.json").read_text())
    respx.get(url__startswith="https://data-api.ecb.europa.eu/service/data/FM").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = EcbClient(cache=cache)
    fact = client.fetch_indicator("ez_deposit_facility_rate")
    assert fact.value == 2.5
    assert fact.revised_previous == 2.25


@respx.mock
def test_ecb_malformed_response_raises(cache: DiskCache):
    respx.get(url__startswith="https://data-api.ecb.europa.eu/service/data/FM").mock(
        return_value=httpx.Response(200, json={"unexpected": True})
    )
    client = EcbClient(cache=cache)
    with pytest.raises(DataSourceUnavailable):
        client.fetch_indicator("ez_deposit_facility_rate")


# --- Eurostat ---------------------------------------------------------------


@respx.mock
def test_eurostat_fetch_indicator_ok(cache: DiskCache):
    payload = {
        "id": ["geo", "time"],
        "size": [1, 2],
        "dimension": {"time": {"category": {"index": {"2026-05": 0, "2026-06": 1}}}},
        "value": {"0": 6.3, "1": 6.2},
    }
    respx.get(
        url__startswith="https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m"
    ).mock(return_value=httpx.Response(200, json=payload))
    client = EurostatClient(cache=cache)
    fact = client.fetch_indicator("ez_unemployment_rate")
    assert fact.value == 6.2
    assert fact.revised_previous == 6.3


# --- BLS --------------------------------------------------------------------


@respx.mock
def test_bls_fetch_indicator_ok(cache: DiskCache):
    payload = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {
            "series": [
                {
                    "data": [
                        {"year": "2026", "period": "M07", "value": "4.0"},
                        {"year": "2026", "period": "M06", "value": "4.1"},
                    ]
                }
            ]
        },
    }
    respx.get(url__startswith="https://api.bls.gov/publicAPI/v1/timeseries/data/LNS14000000").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = BlsClient(cache=cache)
    fact = client.fetch_indicator("us_unemployment_rate_bls")
    assert fact.value == 4.0


@respx.mock
def test_bls_request_failed_status_raises(cache: DiskCache):
    respx.get(url__startswith="https://api.bls.gov/publicAPI/v1/timeseries/data/LNS14000000").mock(
        return_value=httpx.Response(
            200, json={"status": "REQUEST_NOT_PROCESSED", "message": ["quota exceeded"]}
        )
    )
    client = BlsClient(cache=cache)
    with pytest.raises(DataSourceUnavailable):
        client.fetch_indicator("us_unemployment_rate_bls")


# --- EIA --------------------------------------------------------------------


def test_eia_missing_api_key_raises(cache: DiskCache):
    client = EiaClient(api_key=None, cache=cache)
    with pytest.raises(DataSourceUnavailable):
        client.fetch_indicator("us_wti_spot_price")


@respx.mock
def test_eia_fetch_indicator_ok(cache: DiskCache):
    payload = {
        "response": {
            "data": [
                {"period": "2026-08-21", "value": "80.0"},
                {"period": "2026-08-14", "value": "78.0"},
            ]
        }
    }
    respx.get(url__startswith="https://api.eia.gov/v2/petroleum/pri/spt/data").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = EiaClient(api_key="testkey", cache=cache)
    fact = client.fetch_indicator("us_wti_spot_price")
    assert fact.value == 80.0


# --- CFTC -------------------------------------------------------------------


@respx.mock
def test_cftc_fetch_indicator_ok(cache: DiskCache):
    rows = [
        {
            "report_date_as_yyyy_mm_dd": "2026-08-19T00:00:00.000",
            "noncomm_positions_long_all": "150000",
            "noncomm_positions_short_all": "50000",
        },
        {
            "report_date_as_yyyy_mm_dd": "2026-08-12T00:00:00.000",
            "noncomm_positions_long_all": "140000",
            "noncomm_positions_short_all": "60000",
        },
    ]
    respx.get("https://publicreporting.cftc.gov/resource/6dca-aqww.json").mock(
        return_value=httpx.Response(200, json=rows)
    )
    client = CftcClient(cache=cache)
    fact = client.fetch_indicator("eur_net_noncommercial_positioning")
    assert fact.value == 100_000
    assert fact.revised_previous == 80_000


@respx.mock
def test_cftc_empty_response_raises(cache: DiskCache):
    respx.get("https://publicreporting.cftc.gov/resource/6dca-aqww.json").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = CftcClient(cache=cache)
    with pytest.raises(DataSourceUnavailable):
        client.fetch_indicator("eur_net_noncommercial_positioning")
