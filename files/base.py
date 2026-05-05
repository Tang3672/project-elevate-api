"""
BaseConnector: abstract interface all data source connectors implement.

Every connector must produce a list of DemandSignals.
The ingestion pipeline only knows about this interface — not specific sources.

Connectors are intentionally stateless. State (last-run timestamps,
cursor tokens) is stored in the DB so the scheduler can resume after restarts.
"""

import logging
import httpx
from abc import ABC, abstractmethod
from typing import List, AsyncIterator
from datetime import datetime, timezone

from app.models.demand_signal import DemandSignal

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    """Raised when a connector fails fatally and should be retried later."""
    pass


class BaseConnector(ABC):

    # Subclasses set these
    source_name: str = "unknown"
    description: str = ""
    update_frequency_hours: int = 24     # how often to re-run this connector
    batch_size: int = 100                # how many signals to yield per batch

    def __init__(self):
        # Shared async HTTP client — reused across requests within one run
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "ProjectElevate/1.0 (healthcare-research-platform)"},
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()
            self._client = None

    @abstractmethod
    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        """
        Yield batches of DemandSignals.

        Use `yield` (not `return`) — connectors can be large (100k+ records).
        Yield in batches of self.batch_size so the pipeline can embed + store
        incrementally without loading everything into memory.

        Example:
            async def fetch(self):
                page = 0
                while True:
                    rows = await self._get_page(page)
                    if not rows:
                        break
                    yield [self._to_signal(r) for r in rows]
                    page += 1
        """
        ...

    async def _get_json(self, url: str, params: dict = None) -> dict | list:
        """HTTP GET with error handling and basic retry."""
        if not self._client:
            raise ConnectorError("Connector used outside async context manager")
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            raise ConnectorError(
                f"{self.source_name}: HTTP {e.response.status_code} from {url}"
            ) from e
        except httpx.RequestError as e:
            raise ConnectorError(
                f"{self.source_name}: Network error fetching {url}: {e}"
            ) from e

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _freshness(self, data_year: int) -> int:
        """Calculate how old source data is in days."""
        current_year = datetime.now().year
        return max(0, (current_year - data_year) * 365)
