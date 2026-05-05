"""
openFDA Connector
=================
Source: api.fda.gov
Endpoints: drug adverse events (FAERS), device adverse events, recalls, drug shortages
Update: Continuous (FAERS quarterly; recalls/shortages ~weekly)
Auth:   Free API key (240/min, 120k/day with key; 1000/day without)

Why high-value: Safety failures and shortages are *direct* demand signals.
- A recall of a device class = "this device category needs a safer replacement"
- 10,000 adverse events for a drug = "there's unmet need for safer alternatives"
- Drug shortage = "supply chain innovation needed here"
"""

import logging
from typing import AsyncIterator, List, Optional
from datetime import datetime, timedelta

from app.ingestion.connectors.base import BaseConnector
from app.models.demand_signal import (
    DemandSignal, SignalSource, SignalType, GeographicScope
)

logger = logging.getLogger(__name__)

FDA_BASE = "https://api.fda.gov"


class FDAAdverseEventsConnector(BaseConnector):
    """
    FAERS: FDA Adverse Event Reporting System (drugs).
    We aggregate by drug + reaction to find the most-reported safety signals.
    """
    source_name = "fda_adverse_events"
    description = "FDA FAERS drug adverse events — aggregated by drug and reaction type"
    update_frequency_hours = 24 * 7  # weekly
    batch_size = 50

    def __init__(self, api_key: str = ""):
        super().__init__()
        self.api_key = api_key

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        """Fetch top adverse event drug-reaction combinations."""
        url = f"{FDA_BASE}/drug/event.json"

        # Get the most-reported drug-reaction pairs (serious events only)
        params = {
            "search": "serious:1",
            "count": "patient.drug.openfda.generic_name.exact",
            "limit": "100",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            data = await self._get_json(url, params)
            results = data.get("results", [])
        except Exception as e:
            logger.error(f"FDA adverse events count query failed: {e}")
            return

        signals = []
        for item in results:
            drug_name = item.get("term", "")
            count = item.get("count", 0)
            if not drug_name or count < 100:  # filter noise
                continue

            description = (
                f"FDA FAERS: {drug_name} has {count:,} serious adverse event reports. "
                f"High adverse event volume signals demand for safer drug alternatives, "
                f"better monitoring tools, improved dosing systems, or adverse event "
                f"prediction software for {drug_name} and drugs in its class."
            )

            signals.append(DemandSignal(
                source=SignalSource.FDA_ADVERSE_EVENTS,
                source_record_id=f"faers_drug_{drug_name.lower().replace(' ', '_')}",
                signal_type=SignalType.SAFETY_FAILURE,
                title=f"High adverse events: {drug_name} ({count:,} serious reports)",
                description=description,
                condition_or_topic=drug_name,
                innovation_category_hint="PHARMACEUTICALS",
                keywords=[
                    drug_name.lower(), "adverse events", "drug safety",
                    "faers", "pharmacovigilance", "patient safety"
                ],
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
    """
    MAUDE: FDA Medical Device Adverse Events.
    Aggregated by device type to find highest-failure device categories.
    """
    source_name = "fda_device_events"
    description = "FDA MAUDE medical device adverse events by device type"
    update_frequency_hours = 24 * 7
    batch_size = 50

    def __init__(self, api_key: str = ""):
        super().__init__()
        self.api_key = api_key

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        url = f"{FDA_BASE}/device/event.json"
        params = {
            "search": "event_type:M",  # malfunctions
            "count": "device.generic_name.exact",
            "limit": "100",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            data = await self._get_json(url, params)
            results = data.get("results", [])
        except Exception as e:
            logger.error(f"FDA device events failed: {e}")
            return

        signals = []
        for item in results:
            device = item.get("term", "")
            count = item.get("count", 0)
            if not device or count < 50:
                continue

            description = (
                f"FDA MAUDE: {device} has {count:,} malfunction reports. "
                f"Device malfunction patterns signal demand for redesigned or "
                f"replacement medical devices, improved device monitoring systems, "
                f"predictive maintenance software, or safety enhancement add-ons for "
                f"existing {device} platforms."
            )

            signals.append(DemandSignal(
                source=SignalSource.FDA_DEVICE_EVENTS,
                source_record_id=f"maude_device_{device.lower().replace(' ', '_')[:80]}",
                signal_type=SignalType.SAFETY_FAILURE,
                title=f"Device malfunctions: {device} ({count:,} reports)",
                description=description,
                condition_or_topic=device,
                innovation_category_hint="HARDWARE",
                keywords=[
                    device.lower(), "medical device", "malfunction", "maude",
                    "device safety", "FDA"
                ],
                geographic_scope=GeographicScope.NATIONAL,
                magnitude=float(count),
                magnitude_unit="malfunction reports",
                data_freshness_days=14,
                source_url="https://open.fda.gov/apis/device/event/",
                confidence_score=0.85,
                raw_data=item,
            ))

        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]


class FDARecallsConnector(BaseConnector):
    """
    FDA Drug and Device Enforcement Actions (recalls).
    Recalls are the strongest possible safety-failure demand signal.
    """
    source_name = "fda_recalls"
    description = "FDA drug and device recalls — active enforcement actions"
    update_frequency_hours = 24 * 3  # every 3 days
    batch_size = 50

    def __init__(self, api_key: str = ""):
        super().__init__()
        self.api_key = api_key

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        # Drug recalls
        async for batch in self._fetch_recalls("drug"):
            yield batch
        # Device recalls
        async for batch in self._fetch_recalls("device"):
            yield batch

    async def _fetch_recalls(self, noun: str) -> AsyncIterator[List[DemandSignal]]:
        url = f"{FDA_BASE}/{noun}/enforcement.json"
        # Get Class I recalls (most serious) from last 2 years
        params = {
            "search": "classification:'Class I' AND status:Ongoing",
            "$limit": "100",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            data = await self._get_json(url, params)
            results = data.get("results", [])
        except Exception as e:
            logger.error(f"FDA {noun} recalls failed: {e}")
            return

        signals = []
        source = SignalSource.FDA_RECALLS
        cat_hint = "HARDWARE" if noun == "device" else "PHARMACEUTICALS"

        for item in results:
            product = item.get("product_description", "")[:200]
            reason = item.get("reason_for_recall", "")[:300]
            firm = item.get("recalling_firm", "")
            quantity = item.get("product_quantity", "unknown quantity")
            recall_date = item.get("recall_initiation_date", "")

            if not product or not reason:
                continue

            title = f"Class I Recall: {product[:80]}"
            description = (
                f"FDA Class I recall (serious health hazard): {product}. "
                f"Reason: {reason}. "
                f"Recalling firm: {firm}. Quantity: {quantity}. "
                f"Initiated: {recall_date}. "
                f"Class I recalls represent the highest-risk product failures — "
                f"direct evidence that existing {noun} solutions are inadequate and "
                f"that safer alternatives are needed in this product category."
            )

            signals.append(DemandSignal(
                source=source,
                source_record_id=item.get("recall_number", product[:50]),
                signal_type=SignalType.SAFETY_FAILURE,
                title=title,
                description=description,
                condition_or_topic=product[:100],
                innovation_category_hint=cat_hint,
                keywords=[
                    "recall", "class I", "FDA", noun, "patient safety",
                    "product failure"
                ],
                geographic_scope=GeographicScope.NATIONAL,
                data_freshness_days=7,
                source_url=f"https://open.fda.gov/apis/{noun}/enforcement/",
                confidence_score=0.95,
                raw_data={k: str(v)[:200] for k, v in item.items()},
            ))

        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]
