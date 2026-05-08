import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.logging import DefaultFormatter

from app.cache import cache
from app.config import settings
from app.fetchers import (
    fetch_binance,
    fetch_bitfinex,
    fetch_bitstamp,
    fetch_coinbase,
    fetch_coinmate,
    fetch_gemini,
    fetch_kraken,
)
from app.models import ConvertResponse, CurrencyRateResponse, ExchangeRates, RatesResponse


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(DefaultFormatter("%(levelprefix)s %(message)s", use_colors=None))
    app_log = logging.getLogger("app")
    app_log.addHandler(handler)
    app_log.setLevel(logging.INFO)
    app_log.propagate = False


_setup_logging()
logger = logging.getLogger(__name__)

_DESCRIPTION = """\
Real-time BTC price aggregator that polls **Coinbase**, **Kraken**, **Bitfinex**,
**Bitstamp**, **Binance**, **Coinmate**, and **Gemini**
on a configurable interval (default: 60 s) and serves the results from an in-memory cache.

Per-currency statistics (min, max, median) are computed across all exchanges
that successfully returned a price in the most recent fetch cycle.

## Notes

- A `null` exchange value means the exchange does not list that currency pair
  (e.g. Coinbase has no BTC-CHF), or the exchange has never successfully returned
  a price since startup. Failed fetches preserve the last known value.
- Statistics exclude `null` sources — with two live sources the median equals their mean.
- The `timestamp` field reflects when the last background fetch completed.
- Polling interval and currencies are set via environment variables (`.env`);
  exchange URLs, supported pairs, and timeouts are set in `exchanges.json`.

## Machine-readable schema

The full OpenAPI schema is available at [`/openapi.json`](/openapi.json).
"""

_TAGS = [
    {
        "name": "rates",
        "description": "BTC price data aggregated from multiple exchanges.",
    },
    {
        "name": "ops",
        "description": "Operational endpoints for health checks and monitoring.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    headers = {"User-Agent": "lnbits-price-aggregator/1.0 (https://github.com/lnbits)"}
    async with httpx.AsyncClient(headers=headers) as client:
        await _fetch_and_cache(client)
        task = asyncio.create_task(_price_loop(client))
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="LNbits Price Aggregator",
    version="1.0.0",
    description=_DESCRIPTION,
    license_info={"name": "MIT"},
    openapi_tags=_TAGS,
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=500)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


async def _fetch_and_cache(client: httpx.AsyncClient) -> None:
    currencies = settings.currencies
    coinbase, kraken, bitfinex, bitstamp, binance, coinmate, gemini = await asyncio.gather(
        fetch_coinbase(client),
        fetch_kraken(client),
        fetch_bitfinex(client),
        fetch_bitstamp(client),
        fetch_binance(client),
        fetch_coinmate(client),
        fetch_gemini(client),
        return_exceptions=True,
    )

    def _safe(result: object) -> dict[str, float | None]:
        return result if isinstance(result, dict) else {c: None for c in currencies}  # type: ignore[return-value]

    fresh = {
        "coinbase": _safe(coinbase),
        "kraken":   _safe(kraken),
        "bitfinex": _safe(bitfinex),
        "bitstamp": _safe(bitstamp),
        "binance":  _safe(binance),
        "coinmate": _safe(coinmate),
        "gemini":   _safe(gemini),
    }

    # Preserve last-known price when an exchange fails — only overwrite with a real value.
    prev, _ = await cache.snapshot()
    merged = {
        currency: {
            exchange: (
                fresh[exchange].get(currency)
                if fresh[exchange].get(currency) is not None
                else prev.get(currency, {}).get(exchange)
            )
            for exchange in fresh
        }
        for currency in currencies
    }
    await cache.update(merged)
    logger.info("Rates updated: %s", list(merged.keys()))


async def _price_loop(client: httpx.AsyncClient) -> None:
    while True:
        await asyncio.sleep(settings.fetch_interval_seconds)
        try:
            await _fetch_and_cache(client)
        except Exception as exc:
            logger.error("Fetch error: %s", exc)


@app.get(
    "/rates",
    summary="Get current BTC prices",
    description="""\
Returns the most recent BTC prices fetched from Coinbase, Kraken, Bitfinex, Bitstamp,
Binance, and Coinmate, broken down per currency and per exchange.

Prices are refreshed every `FETCH_INTERVAL_SECONDS` seconds (default: 60) by a
background task. This endpoint always returns the **cached** values — it never
blocks on a live exchange request.

Exchange values are `null` when:
- The exchange does not list that currency pair (Coinbase has no BTC-CHF).
- The exchange has never successfully returned a price since startup.

Failed fetches retain the last known value rather than flipping to `null`.

Statistics (`min`, `max`, `median`) are computed only from non-null exchange prices.
""",
    response_description="BTC price snapshot across all configured currencies.",
    response_model=RatesResponse,
    tags=["rates"],
    responses={
        200: {"description": "Price snapshot returned successfully."},
        503: {
            "description": (
                "No price data available yet. "
                "The server is still completing its first fetch after startup."
            )
        },
    },
)
async def get_rates() -> RatesResponse:
    data, last_updated = await cache.snapshot()
    if not data:
        raise HTTPException(status_code=503, detail="No rate data available yet")
    rates = {currency: ExchangeRates(**exchange_data) for currency, exchange_data in data.items()}
    return RatesResponse(
        timestamp=last_updated or datetime.now(UTC),
        base="BTC",
        rates=rates,
    )


@app.get(
    "/rate/{currency}",
    summary="Get BTC price for one currency",
    description=(
        "Returns the full exchange breakdown and statistics for a single currency. "
        "Use the `currency` path parameter to select the currency (e.g. `USD`, `EUR`, `CZK`)."
    ),
    response_description="Exchange breakdown and statistics for the requested currency.",
    response_model=CurrencyRateResponse,
    tags=["rates"],
    responses={
        200: {"description": "Rate data returned successfully."},
        404: {"description": "Currency not configured on this server."},
        503: {"description": "No price data available yet."},
    },
)
async def get_rate(currency: str) -> CurrencyRateResponse:
    currency = currency.upper()
    data, last_updated = await cache.snapshot()
    if not data:
        raise HTTPException(status_code=503, detail="No rate data available yet")
    if currency not in data:
        raise HTTPException(status_code=404, detail=f"Currency {currency} not configured")
    return CurrencyRateResponse(
        timestamp=last_updated or datetime.now(UTC),
        base="BTC",
        currency=currency,
        rates=ExchangeRates(**data[currency]),
    )


@app.get(
    "/rate/{currency}/{amount}",
    summary="Convert fiat amount to satoshis",
    description=(
        "Converts `amount` units of `currency` to satoshis using the current median "
        "BTC price. The result is floored to the nearest whole satoshi.\n\n"
        "Returns `503` if no price data is available yet, or if all exchanges returned "
        "`null` for the requested currency."
    ),
    response_description="Satoshi equivalent of the given fiat amount.",
    response_model=ConvertResponse,
    tags=["rates"],
    responses={
        200: {"description": "Conversion result returned successfully."},
        404: {"description": "Currency not configured on this server."},
        503: {"description": "No price data available yet or no median for this currency."},
    },
)
async def convert_to_sats(currency: str, amount: float) -> ConvertResponse:
    currency = currency.upper()
    data, last_updated = await cache.snapshot()
    if not data:
        raise HTTPException(status_code=503, detail="No rate data available yet")
    if currency not in data:
        raise HTTPException(status_code=404, detail=f"Currency {currency} not configured")
    rates = ExchangeRates(**data[currency])
    if rates.median is None:
        raise HTTPException(
            status_code=503, detail=f"No median price available for {currency}"
        )
    sats = int(amount / rates.median * 100_000_000)
    return ConvertResponse(
        timestamp=last_updated or datetime.now(UTC),
        currency=currency,
        amount=amount,
        sats=sats,
        rate=rates.median,
    )


@app.get(
    "/health",
    summary="Health check",
    description=(
        'Returns `{"status": "ok"}` when the server is running. '
        "Used by Docker HEALTHCHECK and load balancers."
    ),
    response_description="Server liveness status.",
    tags=["ops"],
    responses={
        200: {"description": "Server is healthy."},
    },
)
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _ago(ts: datetime) -> str:
    seconds = int((datetime.now(UTC) - ts).total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s ago"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m ago"


def _fmt(price: float | None, width: int = 13) -> str:
    return f"{price:>{width},.2f}" if price is not None else f"{'—':>{width}}"


def _build_overview(
    data: dict[str, dict[str, float | None]], last_updated: datetime | None
) -> str:
    col = 13  # price column width
    pair_w = 9
    cols = [
        "Median", "Min", "Max",
        "Coinbase", "Kraken", "Bitfinex", "Bitstamp", "Binance", "Coinmate", "Gemini",
    ]
    header_row = f"  {'Pair':<{pair_w}}" + "".join(f"  {h:>{col}}" for h in cols)
    rule = "  " + "─" * (len(header_row) - 2)

    ts_str = last_updated.strftime("%Y-%m-%d %H:%M:%S UTC") if last_updated else "—"
    ago_str = _ago(last_updated) if last_updated else "—"
    title = "  ₿  LNbits Price Aggregator"
    title_line = f"{title:<40}  {ts_str}"

    rows = []
    for currency, ex in data.items():
        rates = ExchangeRates(**ex)
        rows.append(
            f"  {'BTC/' + currency:<{pair_w}}"
            f"  {_fmt(rates.median,   col)}"
            f"  {_fmt(rates.min,      col)}"
            f"  {_fmt(rates.max,      col)}"
            f"  {_fmt(ex['coinbase'], col)}"
            f"  {_fmt(ex['kraken'],   col)}"
            f"  {_fmt(ex['bitfinex'], col)}"
            f"  {_fmt(ex['bitstamp'], col)}"
            f"  {_fmt(ex['binance'],  col)}"
            f"  {_fmt(ex['coinmate'], col)}"
            f"  {_fmt(ex['gemini'],   col)}"
        )

    footer = (
        f"  updated {ago_str}"
        f"  ·  refreshes every {settings.fetch_interval_seconds}s"
        f"  ·  / web  ·  /rates JSON  ·  /docs API"
    )

    lines = [
        "",
        title_line,
        "",
        header_row,
        rule,
        *rows,
        rule,
        "",
        footer,
        "",
    ]
    return "\n".join(lines)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/curl", include_in_schema=False)
async def curl_overview() -> PlainTextResponse:
    data, last_updated = await cache.snapshot()
    if not data:
        return PlainTextResponse("LNbits Price Aggregator — fetching prices, please wait...\n")
    return PlainTextResponse(_build_overview(data, last_updated))
