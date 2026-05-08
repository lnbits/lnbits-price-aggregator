from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.cache import cache as app_cache
from app.main import app


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


@pytest.fixture(autouse=True)
def reset_app():
    app.router.lifespan_context = _noop_lifespan
    app_cache._data = {}
    app_cache._last_updated = None
    yield
    app_cache._data = {}
    app_cache._last_updated = None


def _inject(data: dict) -> None:
    app_cache._data = data
    app_cache._last_updated = datetime.now(UTC)


def _ex(cb, kr, bf, bs, bn, cm=None, gm=None):
    return {
        "coinbase": cb, "kraken": kr, "bitfinex": bf,
        "bitstamp": bs, "binance": bn, "coinmate": cm, "gemini": gm,
    }

_FULL_DATA = {
    "USD": _ex(45000.0, 44999.0, 45001.0, 44998.0, 45002.0, 45003.0, 45004.0),
    "EUR": _ex(38000.0, 37999.0, 38001.0, 37997.0, 38003.0, 38004.0, 38005.0),
    "CHF": _ex(None,    42000.0, 42001.0, None,     None),
    "GBP": _ex(35000.0, 34999.0, 35001.0, 34996.0, None,    None,    35003.0),
    "CZK": _ex(None,    None,    None,    None,     None,    2850000.0),
}


def test_health_ok():
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_rates_empty_cache_returns_503():
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/rates")
    assert r.status_code == 503


def test_rates_returns_all_currencies():
    _inject(_FULL_DATA)
    with TestClient(app) as c:
        r = c.get("/rates")
    assert r.status_code == 200
    body = r.json()
    assert body["base"] == "BTC"
    assert set(body["rates"].keys()) == {"USD", "EUR", "CHF", "GBP", "CZK"}


def test_rates_response_schema():
    _inject(_FULL_DATA)
    with TestClient(app) as c:
        body = c.get("/rates").json()
    assert "timestamp" in body
    assert "T" in body["timestamp"]
    for currency in ("USD", "EUR", "CHF", "GBP", "CZK"):
        rates = body["rates"][currency]
        for field in ("coinbase", "kraken", "bitfinex", "coinmate", "gemini",
                      "min", "max", "median"):
            assert field in rates


def test_rates_null_coinbase_chf():
    _inject(_FULL_DATA)
    with TestClient(app) as c:
        body = c.get("/rates").json()
    assert body["rates"]["CHF"]["coinbase"] is None


def test_rates_stats_computed_correctly():
    _inject(_FULL_DATA)
    with TestClient(app) as c:
        body = c.get("/rates").json()
    usd = body["rates"]["USD"]
    # sorted: 44998, 44999, 45000, 45001, 45002, 45003, 45004 → median = 45001.0
    assert usd["min"] == 44998.0
    assert usd["max"] == 45004.0
    assert usd["median"] == pytest.approx(45001.0)


def test_rates_stats_with_null_exchange():
    _inject(_FULL_DATA)
    with TestClient(app) as c:
        body = c.get("/rates").json()
    chf = body["rates"]["CHF"]
    # coinbase=None, kraken=42000, bitfinex=42001, bitstamp=None, binance=None, coinmate=None
    assert chf["min"] == 42000.0
    assert chf["max"] == 42001.0
    assert chf["median"] == 42000.5


def test_rates_stats_all_null():
    _inject({"USD": _ex(None, None, None, None, None)})
    with TestClient(app) as c:
        body = c.get("/rates").json()
    usd = body["rates"]["USD"]
    assert usd["min"] is None
    assert usd["max"] is None
    assert usd["median"] is None


# /rate/{currency} tests

def test_rate_currency_ok():
    _inject(_FULL_DATA)
    with TestClient(app) as c:
        r = c.get("/rate/USD")
    assert r.status_code == 200
    body = r.json()
    assert body["base"] == "BTC"
    assert body["currency"] == "USD"
    assert "rates" in body
    assert body["rates"]["coinbase"] == 45000.0


def test_rate_currency_case_insensitive():
    _inject(_FULL_DATA)
    with TestClient(app) as c:
        r = c.get("/rate/usd")
    assert r.status_code == 200
    assert r.json()["currency"] == "USD"


def test_rate_currency_not_configured_returns_404():
    _inject(_FULL_DATA)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/rate/JPY")
    assert r.status_code == 404


def test_rate_currency_empty_cache_returns_503():
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/rate/USD")
    assert r.status_code == 503


# /rate/{currency}/{amount} tests

def test_convert_to_sats_ok():
    _inject(_FULL_DATA)
    with TestClient(app) as c:
        r = c.get("/rate/USD/1000")
    assert r.status_code == 200
    body = r.json()
    assert body["currency"] == "USD"
    assert body["amount"] == 1000.0
    assert body["rate"] == pytest.approx(45001.0)
    # 1000 / 45001.0 * 1e8 floored
    assert body["sats"] == int(1000 / 45001.0 * 100_000_000)


def test_convert_to_sats_all_null_returns_503():
    _inject({"USD": _ex(None, None, None, None, None)})
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/rate/USD/1000")
    assert r.status_code == 503


def test_convert_to_sats_unknown_currency_returns_404():
    _inject(_FULL_DATA)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/rate/JPY/1000")
    assert r.status_code == 404


def test_convert_to_sats_empty_cache_returns_503():
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/rate/USD/500")
    assert r.status_code == 503
