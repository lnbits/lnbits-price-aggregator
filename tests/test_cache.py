import pytest

from app.cache import PriceCache


@pytest.fixture
def cache():
    return PriceCache()


async def test_snapshot_empty(cache):
    data, ts = await cache.snapshot()
    assert data == {}
    assert ts is None


async def test_update_and_snapshot(cache):
    payload = {
        "USD": {"coinbase": 45000.0, "kraken": 44999.0, "bitfinex": 45001.0},
        "EUR": {"coinbase": 38000.0, "kraken": None, "bitfinex": 38002.0},
    }
    await cache.update(payload)
    data, ts = await cache.snapshot()
    assert data == payload
    assert ts is not None


async def test_update_overwrites_previous(cache):
    await cache.update({"USD": {"coinbase": 1.0, "kraken": 1.0, "bitfinex": 1.0}})
    new_payload = {"USD": {"coinbase": 2.0, "kraken": 2.0, "bitfinex": 2.0}}
    await cache.update(new_payload)
    data, _ = await cache.snapshot()
    assert data == new_payload


async def test_snapshot_returns_copy(cache):
    payload = {"USD": {"coinbase": 100.0, "kraken": 100.0, "bitfinex": 100.0}}
    await cache.update(payload)
    data, _ = await cache.snapshot()
    data["USD"]["coinbase"] = 999.0
    data2, _ = await cache.snapshot()
    assert data2["USD"]["coinbase"] == 100.0
