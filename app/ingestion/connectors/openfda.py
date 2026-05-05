"""
openFDA Connector (Fixed)
=========================
Fix: device events tries multiple event_type values; recalls tries multiple query formats
"""
import logging
from typing import AsyncIterator, List
from app.ingestion.connectors.base import BaseConnector
from app.models.demand_signal import (
    DemandSignal, SignalSource, SignalType, GeographicScope
)

logger = logging.getLogger(__name__)
FDA_BASE = "https://api.fda.gov"


class FDAAdverseEventsConnector(BaseConnector):
    source_name = "fda_adverse_events"
    description = "FDA FAERS drug adverse events"
    update_frequency_hours = 24 * 7
    batch_size = 50

    def __init__(self, api_key: str = ""):
        super().__init__()
        self.api_key = api_key

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        params = {"search": "serious:1", "count": "patient.drug.openfda.generic_name.exact", "limit": "100"}
        if self.api_key:
            params["api_key"] = self.api_key
        try:
            data = await self._get_json(f"{FDA_BASE}/drug/event.json", params)
            results = data.get("results", [])
        except Exception as e:
            logger.error(f"FDA adverse events failed: {e}")
            return
        signals = []
        for item in results:
            drug_name = item.get("term", "")
            count = item.get("count", 0)
            if not drug_name or count < 100:
                continue
            description = (
                f"FDA FAERS: {drug_name} has {count:,} serious adverse event reports. "
                f"Signals demand for safer alternatives, better monitoring tools, "
                f"and adverse event prediction software."
            )
            signals.append(DemandSignal(
                source=SignalSource.FDA_ADVERSE_EVENTS,
                source_record_id=f"faers_drug_{drug_name.lower().replace(' ','_')[:80]}",
                signal_type=SignalType.SAFETY_FAILURE,
                title=f"High adverse events: {drug_name} ({count:,} serious reports)",
                description=description,
                condition_or_topic=drug_name,
                innovation_category_hint="PHARMACEUTICALS",
                keywords=[drug_name.lower(), "adverse events", "drug safety", "faers"],
                geographic_scope=GeographicScope.NATIONAL,
                magnitude=float(count),
                magnitude_unit="serious adverse event reports",
                data_freshness_days=30,
                source_url="https://open.fda.gov/apis/drug/event/",
                confidence_score=0.85,
                raw_data=item,
            ))
        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]


class FDADeviceEventsConnector(BaseConnector):
    source_name = "fda_device_events"
    description = "FDA MAUDE medical device adverse events"
    update_frequency_hours = 24 * 7
    batch_size = 50

    def __init__(self, api_key: str = ""):
        super().__init__()
        self.api_key = api_key

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        for event_type in ["M", "Malfunction", "malfunction"]:
            try:
                params = {"search": f"event_type:{event_type}", "count": "device.generic_name.exact", "limit": "100"}
                if self.api_key:
                    params["api_key"] = self.api_key
                data = await self._get_json(f"{FDA_BASE}/device/event.json", params)
                results = data.get("results", [])
                if results:
                    async for batch in self._process(results):
                        yield batch
                    return
            except Exception:
                continue
        try:
            params = {"count": "device.generic_name.exact", "limit": "100"}
            if self.api_key:
                params["api_key"] = self.api_key
            data = await self._get_json(f"{FDA_BASE}/device/event.json", params)
            async for batch in self._process(data.get("results", [])):
                yield batch
        except Exception as e:
            logger.error(f"FDA device events all fallbacks failed: {e}")

    async def _process(self, results):
        signals = []
        for item in results:
            device = item.get("term", "")
            count = item.get("count", 0)
            if not device or count < 50:
                continue
            description = (
                f"FDA MAUDE: {device} has {count:,} adverse event reports. "
                f"Signals demand for redesigned devices, improved monitoring, or safer alternatives."
            )
            signals.append(DemandSignal(
                source=SignalSource.FDA_DEVICE_EVENTS,
                source_record_id=f"maude_{device.lower().replace(' ','_')[:80]}",
                signal_type=SignalType.SAFETY_FAILURE,
                title=f"Device failures: {device} ({count:,} reports)",
                description=description,
                condition_or_topic=device,
                innovation_category_hint="HARDWARE",
                keywords=[device.lower(), "medical device", "malfunction", "maude"],
                geographic_scope=GeographicScope.NATIONAL,
                magnitude=float(count),
                magnitude_unit="adverse event reports",
                data_freshness_days=14,
                source_url="https://open.fda.gov/apis/device/event/",
                confidence_score=0.85,
                raw_data=item,
            ))
        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]


class FDARecallsConnector(BaseConnector):
    source_name = "fda_recalls"
    description = "FDA drug and device recalls"
    update_frequency_hours = 24 * 3
    batch_size = 50

    def __init__(self, api_key: str = ""):
        super().__init__()
        self.api_key = api_key

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        for noun in ["drug", "device"]:
            async for batch in self._fetch_recalls(noun):
                yield batch

    async def _fetch_recalls(self, noun):
        queries = [
            'classification:"Class I" AND status:Ongoing',
            'classification:Class+I AND status:Ongoing',
            'classification:"Class I"',
        ]
        data = None
        for query in queries:
            try:
                params = {"search": query, "limit": "100"}
                if self.api_key:
                    params["api_key"] = self.api_key
                data = await self._get_json(f"{FDA_BASE}/{noun}/enforcement.json", params)
                if data.get("results"):
                    break
            except Exception:
                continue
        if not data or not data.get("results"):
            logger.warning(f"FDA {noun} recalls: no results")
            return
        signals = []
        cat_hint = "HARDWARE" if noun == "device" else "PHARMACEUTICALS"
        for item in data["results"]:
            product = item.get("product_description", "")[:200]
            reason = item.get("reason_for_recall", "")[:300]
            firm = item.get("recalling_firm", "")
            if not product or not reason:
                continue
            description = (
                f"FDA Class I recall: {product}. Reason: {reason}. Firm: {firm}. "
                f"Direct evidence that existing {noun} solutions are inadequate — safer alternatives needed."
            )
            signals.append(DemandSignal(
                source=SignalSource.FDA_RECALLS,
                source_record_id=item.get("recall_number", product[:50]),
                signal_type=SignalType.SAFETY_FAILURE,
                title=f"Class I Recall: {product[:80]}",
                description=description,
                condition_or_topic=product[:100],
                innovation_category_hint=cat_hint,
                keywords=["recall", "class I", "FDA", noun, "patient safety"],
                geographic_scope=GeographicScope.NATIONAL,
                data_freshness_days=7,
                source_url=f"https://open.fda.gov/apis/{noun}/enforcement/",
                confidence_score=0.95,
                raw_data={k: str(v)[:200] for k, v in item.items()},
            ))
        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]
