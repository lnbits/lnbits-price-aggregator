# LNbits Price Aggregator

FastAPI service that fetches BTC prices from Coinbase, Kraken, Bitfinex, Bitstamp, Binance,
Coinmate, and Gemini every 60 seconds and serves them via a JSON API.

## API

### `GET /rates`

Returns current BTC prices in USD, EUR, CHF, GBP, and CZK with a per-exchange breakdown and
min/max/median statistics.

```sh
curl -s http://localhost:8000/rates | python3 -m json.tool
```

Example response:

```json
{
  "timestamp": "2026-05-07T12:34:56.789000Z",
  "base": "BTC",
  "rates": {
    "USD": {
      "min": 95228.00, "median": 95230.25, "max": 95232.00,
      "coinbase": 95230.50, "kraken": 95228.00, "bitfinex": 95231.20,
      "bitstamp": 95229.00, "binance": 95232.00, "coinmate": null, "gemini": 95230.00
    },
    "EUR": {
      "min": 88095.00, "median": 88099.00, "max": 88103.00,
      "coinbase": 88100.00, "kraken": 88095.00, "bitfinex": 88102.00,
      "bitstamp": 88098.00, "binance": 88103.00, "coinmate": 88096.00, "gemini": 88099.00
    },
    "CHF": {
      "min": 85000.00, "median": 85000.50, "max": 85001.00,
      "coinbase": null, "kraken": 85000.00, "bitfinex": 85001.00,
      "bitstamp": null, "binance": null, "coinmate": null, "gemini": null
    },
    "GBP": {
      "min": 75795.00, "median": 75799.00, "max": 75802.00,
      "coinbase": 75800.00, "kraken": 75795.00, "bitfinex": 75802.00,
      "bitstamp": 75798.00, "binance": null, "coinmate": null, "gemini": 75797.00
    },
    "CZK": {
      "min": 2849500.00, "median": 2849750.00, "max": 2850000.00,
      "coinbase": null, "kraken": null, "bitfinex": null,
      "bitstamp": null, "binance": null, "coinmate": 2849500.00, "gemini": null
    }
  }
}
```

`null` means the exchange does not list that currency pair or the last fetch failed.
Last-known values are preserved across failed fetches — a `null` only appears if the
exchange has never successfully returned a price since startup.

### `GET /health`

```sh
curl -s http://localhost:8000/health
# {"status":"ok"}
```

### `GET /`

Plain-text ASCII overview table — useful for quick checks from a terminal:

```sh
curl http://localhost:8000/
```

## Docker

```sh
make build        # build the image
make run          # run on port 8000 (stops any existing container first)

# or with docker compose (supports .env file and auto-restart):
docker compose up --build
```

Pass configuration via environment variables:

```sh
docker run --rm -p 8000:8000 \
  -e CURRENCIES=USD,EUR,CZK \
  -e FETCH_INTERVAL_SECONDS=30 \
  lnbits-price-aggregator
```

## Configuration

**Environment variables** — copy `.env.example` to `.env` and edit. `docker compose up` loads it automatically.

| Variable | Default | Description |
|---|---|---|
| `CURRENCIES` | `USD,EUR,CHF,GBP,CZK` | Comma-separated currency codes to fetch |
| `FETCH_INTERVAL_SECONDS` | `60` | How often to refresh prices (seconds) |

**Exchange configuration** — edit `exchanges.json` to enable/disable exchanges, update API URLs, adjust supported pairs, or set per-exchange timeouts.

| Key | Description |
|---|---|
| `timeout` | Default request timeout in seconds (top-level fallback) |
| `{exchange}.enabled` | Set to `false` to disable an exchange without removing it |
| `{exchange}.url` | Base URL for the exchange API |
| `{exchange}.timeout` | Per-exchange timeout in seconds (overrides the top-level default) |
| `{exchange}.currencies` / `pairs` | Which currency codes or pair names to request |

## Development

**Requirements:** Python 3.12, [uv](https://docs.astral.sh/uv/)

```sh
# Install all dependencies (including dev)
uv sync --all-extras

# Run locally
uv run uvicorn app.main:app --reload

# Lint
make ruff

# Tests
make test
```

## CI / CD

GitHub Actions workflows are in `.github/workflows/`:

- **`ci.yml`** — runs on every push and pull request: lints with Ruff, then runs Pytest.
- **`release.yml`** — triggered on `v*` tags: runs tests, then builds and pushes to Docker Hub.

To enable Docker Hub releases, add these secrets to your GitHub repository:

| Secret | Description |
|---|---|
| `DOCKERHUB_USERNAME` | Your Docker Hub username |
| `DOCKERHUB_TOKEN` | Docker Hub access token (Settings → Security → New Access Token) |

Publish a release:

```sh
git tag v1.0.0
git push origin v1.0.0
```

This will push `your-username/lnbits-price-aggregator:1.0.0`,
`your-username/lnbits-price-aggregator:1.0`, and
`your-username/lnbits-price-aggregator:latest` to Docker Hub.
