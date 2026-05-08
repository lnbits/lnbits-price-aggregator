from datetime import datetime
from statistics import median as _median
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class ExchangeRates(BaseModel):
    """BTC price data for a single fiat currency, broken down by exchange."""

    _null_desc = "`null` if the pair is unlisted or no price has been received since startup."
    _stat_null = "`null` if no exchange returned data."

    median: Annotated[
        float | None,
        Field(
            default=None,
            description=(
                "Median price across all exchanges that returned data. "
                f"With two sources this equals their mean. {_stat_null}"
            ),
            json_schema_extra={"readOnly": True},
        ),
    ]
    min: Annotated[
        float | None,
        Field(
            default=None,
            description=f"Lowest price across all exchanges that returned data. {_stat_null}",
            json_schema_extra={"readOnly": True},
        ),
    ]
    max: Annotated[
        float | None,
        Field(
            default=None,
            description=f"Highest price across all exchanges that returned data. {_stat_null}",
            json_schema_extra={"readOnly": True},
        ),
    ]
    coinbase: Annotated[
        float | None,
        Field(description=f"Last traded price on Coinbase Exchange. {_null_desc}"),
    ]
    kraken: Annotated[
        float | None,
        Field(description=f"Last traded price on Kraken. {_null_desc}"),
    ]
    bitfinex: Annotated[
        float | None,
        Field(description=f"Last traded price on Bitfinex. {_null_desc}"),
    ]
    bitstamp: Annotated[
        float | None,
        Field(description=f"Last traded price on Bitstamp. {_null_desc}"),
    ]
    binance: Annotated[
        float | None,
        Field(description=f"Last traded price on Binance. USD uses BTCUSDT. {_null_desc}"),
    ]
    coinmate: Annotated[
        float | None,
        Field(
            description=(
                "Last traded price on Coinmate (Czech exchange). "
                f"CZK and EUR only. {_null_desc}"
            )
        ),
    ]
    gemini: Annotated[
        float | None,
        Field(description=f"Last traded price on Gemini. USD, EUR, and GBP only. {_null_desc}"),
    ]

    @model_validator(mode="after")
    def _compute_stats(self) -> "ExchangeRates":
        prices = self._available_prices()
        self.min = min(prices) if prices else None
        self.max = max(prices) if prices else None
        self.median = _median(prices) if prices else None
        return self

    def _available_prices(self) -> list[float]:
        sources = (
            self.coinbase, self.kraken, self.bitfinex,
            self.bitstamp, self.binance, self.coinmate, self.gemini,
        )
        return [p for p in sources if p is not None]


class CurrencyRateResponse(BaseModel):
    """BTC price data for a single requested currency."""

    timestamp: Annotated[
        datetime,
        Field(description="UTC timestamp of the last successful background fetch."),
    ]
    base: Annotated[
        Literal["BTC"],
        Field(description="The base asset. Always `BTC`."),
    ]
    currency: Annotated[
        str,
        Field(description="The requested ISO 4217 currency code."),
    ]
    rates: Annotated[
        ExchangeRates,
        Field(description="Exchange breakdown and statistics for this currency."),
    ]


class ConvertResponse(BaseModel):
    """Result of converting a fiat amount to satoshis."""

    timestamp: Annotated[
        datetime,
        Field(description="UTC timestamp of the last successful background fetch."),
    ]
    currency: Annotated[str, Field(description="ISO 4217 currency code of the input amount.")]
    amount: Annotated[float, Field(description="Input amount in the given currency.")]
    sats: Annotated[int, Field(description="Equivalent value in satoshis (floored).")]
    rate: Annotated[
        float,
        Field(description="Median BTC/{currency} price used for the conversion."),
    ]


class RatesResponse(BaseModel):
    """BTC price snapshot across all configured fiat currencies."""

    timestamp: Annotated[
        datetime,
        Field(description="UTC timestamp of the last successful background fetch."),
    ]
    base: Annotated[
        Literal["BTC"],
        Field(description="The base asset. Always `BTC`."),
    ]
    rates: Annotated[
        dict[str, ExchangeRates],
        Field(
            description=(
                "Per-currency price breakdown keyed by ISO 4217 currency code "
                "(e.g. `USD`, `EUR`, `CHF`, `GBP`, `CZK`). Configured via the `CURRENCIES` env var."
            )
        ),
    ]
