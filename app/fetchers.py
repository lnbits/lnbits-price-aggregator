import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_CFG: dict[str, Any] = json.loads(
    (Path(__file__).parent.parent / "exchanges.json").read_text()
)

_COINBASE_SEMAPHORE = asyncio.Semaphore(3)


def _enabled(exchange: str) -> bool:
    return _CFG.get(exchange, {}).get("enabled", True)


def _timeout(exchange: str) -> float:
    return _CFG.get(exchange, {}).get("timeout", _CFG.get("timeout", 5.0))


async def _fetch_coinbase_pair(client: httpx.AsyncClient, currency: str) -> float | None:
    async with _COINBASE_SEMAPHORE:
        try:
            r = await client.get(
                f"{_CFG['coinbase']['url']}/products/BTC-{currency}/ticker",
                timeout=_timeout("coinbase"),
            )
            if r.status_code == 404:
                return None
            if not r.is_success:
                try:
                    detail = r.json().get("message") or r.text[:120]
                except Exception:
                    detail = r.text[:120]
                logger.warning("Coinbase BTC-%s: HTTP %s — %s", currency, r.status_code, detail)
                return None
            return float(r.json()["price"])
        except httpx.TimeoutException:
            logger.warning("Coinbase BTC-%s: timed out", currency)
            return None
        except Exception as exc:
            logger.warning("Coinbase BTC-%s: %s", currency, exc)
            return None


async def fetch_coinbase(client: httpx.AsyncClient) -> dict[str, float | None]:
    currencies = settings.currencies
    if not _enabled("coinbase"):
        return {c: None for c in currencies}
    results = await asyncio.gather(*[_fetch_coinbase_pair(client, c) for c in currencies])
    return dict(zip(currencies, results))


def _match_kraken_price(result: dict[str, Any], currency: str) -> float | None:
    suffixes: list[str] = _CFG["kraken"]["suffixes"].get(currency, [currency])
    for suffix in suffixes:
        for key, val in result.items():
            if "XBT" in key and key.endswith(suffix):
                try:
                    return float(val["c"][0])
                except (KeyError, IndexError, TypeError, ValueError):
                    return None
    return None


async def fetch_kraken(client: httpx.AsyncClient) -> dict[str, float | None]:
    currencies = settings.currencies
    out: dict[str, float | None] = {c: None for c in currencies}
    if not _enabled("kraken"):
        return out
    kraken_suffixes: dict[str, list[str]] = _CFG["kraken"]["suffixes"]
    supported = [c for c in currencies if c in kraken_suffixes]
    if not supported:
        return out
    pairs = ",".join(f"XBT{c}" for c in supported)
    try:
        r = await client.get(
            f"{_CFG['kraken']['url']}/0/public/Ticker?pair={pairs}",
            timeout=_timeout("kraken"),
        )
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            return out
        result = body["result"]
        for c in supported:
            out[c] = _match_kraken_price(result, c)
        return out
    except httpx.TimeoutException:
        logger.warning("Kraken: timed out")
        return out
    except Exception:
        return out


async def _fetch_bitstamp_pair(client: httpx.AsyncClient, currency: str) -> float | None:
    try:
        r = await client.get(
            f"{_CFG['bitstamp']['url']}/api/v2/ticker/btc{currency.lower()}/",
            timeout=_timeout("bitstamp"),
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return None
        return float(data["last"])
    except httpx.TimeoutException:
        logger.warning("Bitstamp BTC-%s: timed out", currency)
        return None
    except Exception:
        return None


async def fetch_bitstamp(client: httpx.AsyncClient) -> dict[str, float | None]:
    currencies = settings.currencies
    out: dict[str, float | None] = {c: None for c in currencies}
    if not _enabled("bitstamp"):
        return out
    supported = [c for c in currencies if c in _CFG["bitstamp"]["currencies"]]
    results = await asyncio.gather(*[_fetch_bitstamp_pair(client, c) for c in supported])
    for c, price in zip(supported, results):
        out[c] = price
    return out


async def fetch_binance(client: httpx.AsyncClient) -> dict[str, float | None]:
    currencies = settings.currencies
    out: dict[str, float | None] = {c: None for c in currencies}
    if not _enabled("binance"):
        return out
    pair_map: dict[str, str] = _CFG["binance"]["pairs"]
    pairs = [pair_map[c] for c in currencies if c in pair_map]
    if not pairs:
        return out
    symbols = "[" + ",".join(f'"{p}"' for p in pairs) + "]"
    try:
        r = await client.get(
            f"{_CFG['binance']['url']}/api/v3/ticker/price?symbols={symbols}",
            timeout=_timeout("binance"),
        )
        if not r.is_success:
            logger.warning("Binance ticker: HTTP %s", r.status_code)
            return out
        pair_to_currency = {v: k for k, v in pair_map.items()}
        for item in r.json():
            currency = pair_to_currency.get(item["symbol"])
            if currency is not None:
                try:
                    out[currency] = float(item["price"])
                except (KeyError, TypeError, ValueError):
                    pass
    except httpx.TimeoutException:
        logger.warning("Binance: timed out")
        return out
    except Exception as exc:
        logger.warning("Binance: %s", exc)
    return out


async def _fetch_coinmate_pair(client: httpx.AsyncClient, pair: str) -> float | None:
    try:
        r = await client.get(
            f"{_CFG['coinmate']['url']}/api/ticker",
            params={"currencyPair": pair},
            timeout=_timeout("coinmate"),
        )
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            logger.warning("Coinmate %s: %s", pair, body.get("errorMessage"))
            return None
        return float(body["data"]["last"])
    except httpx.TimeoutException:
        logger.warning("Coinmate %s: timed out", pair)
        return None
    except Exception as exc:
        logger.warning("Coinmate %s: %s", pair, exc)
        return None


async def fetch_coinmate(client: httpx.AsyncClient) -> dict[str, float | None]:
    currencies = settings.currencies
    out: dict[str, float | None] = {c: None for c in currencies}
    if not _enabled("coinmate"):
        return out
    pair_map: dict[str, str] = _CFG["coinmate"]["pairs"]
    pairs = [(c, pair_map[c]) for c in currencies if c in pair_map]
    results = await asyncio.gather(*[_fetch_coinmate_pair(client, pair) for _, pair in pairs])
    for (currency, _), price in zip(pairs, results):
        out[currency] = price
    return out


async def _fetch_gemini_pair(client: httpx.AsyncClient, currency: str) -> float | None:
    try:
        r = await client.get(
            f"{_CFG['gemini']['url']}/v1/pubticker/btc{currency.lower()}",
            timeout=_timeout("gemini"),
        )
        r.raise_for_status()
        return float(r.json()["last"])
    except httpx.TimeoutException:
        logger.warning("Gemini BTC-%s: timed out", currency)
        return None
    except Exception:
        return None


async def fetch_gemini(client: httpx.AsyncClient) -> dict[str, float | None]:
    currencies = settings.currencies
    out: dict[str, float | None] = {c: None for c in currencies}
    if not _enabled("gemini"):
        return out
    supported = [c for c in currencies if c in _CFG["gemini"]["currencies"]]
    results = await asyncio.gather(*[_fetch_gemini_pair(client, c) for c in supported])
    for c, price in zip(supported, results):
        out[c] = price
    return out


async def fetch_bitfinex(client: httpx.AsyncClient) -> dict[str, float | None]:
    currencies = settings.currencies
    out: dict[str, float | None] = {c: None for c in currencies}
    if not _enabled("bitfinex"):
        return out
    supported = [c for c in currencies if c in _CFG["bitfinex"]["currencies"]]
    if not supported:
        return out
    symbols = ",".join(f"tBTC{c}" for c in supported)
    symbol_to_currency = {f"tBTC{c}": c for c in supported}
    try:
        r = await client.get(
            f"{_CFG['bitfinex']['url']}/v2/tickers?symbols={symbols}",
            timeout=_timeout("bitfinex"),
        )
        r.raise_for_status()
        for ticker in r.json():
            currency = symbol_to_currency.get(ticker[0])
            if currency is not None:
                try:
                    out[currency] = float(ticker[7])  # flat array: LAST_PRICE at index 7
                except (IndexError, TypeError, ValueError):
                    pass
    except httpx.TimeoutException:
        logger.warning("Bitfinex: timed out")
        return out
    except Exception:
        pass
    return out
