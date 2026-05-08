# LNbits Price Aggregator — Agent Skills

This document tells AI agents how to interact with the LNbits Price Aggregator.

## What this service does

Aggregates real-time BTC prices from seven exchanges (Coinbase, Kraken, Bitfinex, Bitstamp,
Binance, Coinmate, and Gemini) and serves them through a JSON API. Prices are refreshed every
60 seconds in the background. No authentication is required.

## Schema discovery

The full OpenAPI 3.1 schema — including all fields, types, and constraints — is always
available at runtime:

```
GET /openapi.json
```

Parse this to discover the current field list, descriptions, and any server-side changes
that postdate this document.

The interactive UI is at `/docs` (Swagger) and `/redoc`.

---

## Endpoints

### `GET /rates`

Returns BTC prices in all configured fiat currencies.

**Success response — `200 OK`:**

```json
{
  "timestamp": "2026-05-07T12:34:56.789000Z",
  "base": "BTC",
  "rates": {
    "USD": {
      "min":      95228.00,
      "median":   95230.25,
      "max":      95232.00,
      "coinbase": 95230.50,
      "kraken":   95228.00,
      "bitfinex": 95231.20,
      "bitstamp": 95229.00,
      "binance":  95232.00,
      "coinmate": null,
      "gemini":   95230.00
    },
    "CZK": {
      "min":      2849500.00,
      "median":   2849750.00,
      "max":      2850000.00,
      "coinbase": null,
      "kraken":   null,
      "bitfinex": null,
      "bitstamp": null,
      "binance":  null,
      "coinmate": 2849500.00,
      "gemini":   null
    }
  }
}
```

**Error — `503 Service Unavailable`:**

```json
{ "detail": "No rate data available yet" }
```

Returned only in the first ~60 seconds after a cold start. Retry after a short delay.

**Field reference:**

| Field | Type | Description |
|---|---|---|
| `timestamp` | ISO-8601 datetime (UTC) | When the last background fetch completed |
| `base` | string | Always `"BTC"` |
| `rates` | object | Keys are ISO 4217 currency codes |
| `rates.{CUR}.min` | number \| null | Lowest price across available exchanges |
| `rates.{CUR}.max` | number \| null | Highest price across available exchanges |
| `rates.{CUR}.median` | number \| null | Median price across available exchanges |
| `rates.{CUR}.coinbase` | number \| null | Last trade price on Coinbase Exchange |
| `rates.{CUR}.kraken` | number \| null | Last trade price on Kraken |
| `rates.{CUR}.bitfinex` | number \| null | Last trade price on Bitfinex |
| `rates.{CUR}.bitstamp` | number \| null | Last trade price on Bitstamp |
| `rates.{CUR}.binance` | number \| null | Last trade price on Binance (USD uses BTCUSDT) |
| `rates.{CUR}.coinmate` | number \| null | Last trade price on Coinmate (CZK and EUR only) |
| `rates.{CUR}.gemini` | number \| null | Last trade price on Gemini (USD, EUR, and GBP only) |

**Null semantics:** An exchange value is `null` when the exchange does not list that pair
(e.g. Coinbase has no BTC-CHF, Binance has no BTC-GBP) or when the exchange has never
successfully returned a price since startup. Statistics (`min`, `max`, `median`) are
computed from non-null values only; they are `null` only when every exchange returned
`null` for that currency.

---

### `GET /health`

```
GET /health
```

```json
{ "status": "ok" }
```

Always returns `200` while the server process is running. Does **not** reflect whether
prices are fresh — use `timestamp` from `/rates` to gauge data freshness.

---

## Key behaviours agents should know

1. **Cache-only reads.** `/rates` never blocks on a live exchange call. The worst-case
   latency is the time to acquire an in-memory lock, typically sub-millisecond.

2. **Stale value retention on exchange failure.** If an exchange fetch fails, the last
   successfully fetched value is preserved — the field does **not** flip to `null`.
   Only a value that has never been successfully fetched shows as `null`. The `timestamp`
   field still advances — it records when the fetch *ran*, not whether every exchange
   succeeded.

3. **Configurable currencies.** The set of currencies is controlled by the `CURRENCIES`
   environment variable (comma-separated, default `USD,EUR,CHF,GBP,CZK`). Fetch
   `/openapi.json` or `/rates` at runtime to discover which currencies are actually active.

4. **Polling interval.** Default is 60 seconds (`FETCH_INTERVAL_SECONDS`). If you need
   to know how stale the data might be, check `timestamp` in the response.

5. **Best-effort aggregation.** All six exchanges are fetched concurrently. One exchange
   failing does not affect the others; partial results are always served.

6. **Exchange coverage varies by currency.** Not every exchange lists every pair.
   Known gaps: Coinbase has no BTC-CHF; Binance only covers USD and EUR (BTC-GBP is
   excluded due to low liquidity); Coinmate only covers CZK and EUR; Bitfinex and
   Bitstamp have no BTC-CZK; Gemini covers USD, EUR, and GBP only (no CHF or CZK).
