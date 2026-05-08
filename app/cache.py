import asyncio
import copy
from datetime import UTC, datetime


class PriceCache:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._data: dict[str, dict[str, float | None]] = {}
        self._last_updated: datetime | None = None

    async def update(self, new_data: dict[str, dict[str, float | None]]) -> None:
        async with self._lock:
            self._data = new_data
            self._last_updated = datetime.now(UTC)

    async def snapshot(self) -> tuple[dict[str, dict[str, float | None]], datetime | None]:
        async with self._lock:
            return copy.deepcopy(self._data), self._last_updated


cache = PriceCache()
