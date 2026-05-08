from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    currencies: list[str] = ["USD", "EUR", "CHF", "GBP", "CZK"]
    fetch_interval_seconds: int = 60

    @field_validator("currencies", mode="before")
    @classmethod
    def parse_currencies(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [c.strip().upper() for c in v.split(",") if c.strip()]
        return v  # type: ignore[return-value]


settings = Settings()
