"""
CMS Hospital Quality Connector (Fixed for new API)
"""
import logging
import httpx
from typing import AsyncIterator, List
from app.ingestion.connectors.base import BaseConnector
from app.models.demand_signal import (
    DemandSignal, SignalSource, SignalType, GeographicScope
)

logger = logging.getLogger(__name__)
CMS_API_BASE = "https://data.cms.gov/provider-data/api/1/datastore/query"
HOSPITAL_GENERAL_ID = "xubh-q36u"
HCAHPS_ID = "dgck-syfz"
READMISSIONS_ID = "9n3s-kdb3"


class CMSHospitalQualityConnector(BaseConnector):
    source_name = "cms_hospital_quality"
    description = "CMS Hospital Compare: quality ratings, HCAHPS, readmissions"
    update_frequency_hours = 24 * 90
    batch_size = 100

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        async for batch in self._fetch_star_ratings():
            yield batch
        async for batch in self._fetch_hcahps():
            yield batch
        async for batch in self._fetch_readmissions():
            yield batch

    async def _cms_query(self, dataset_id, conditions, limit=500):
        url = f"{CMS_API_BASE}/{dataset_id}/0"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json={"conditions": conditions, "limit": limit, "offset": 0})
                resp.raise_for_status()
                return resp.json().get("results", [])
        except Exception as e:
            logger.error(f"CMS API query failed for {dataset_id}: {e}")
            return []

    async def _fetch_star_ratings(self) -> AsyncIterator[List[DemandSignal]]:
        results = await self._cms_query(HOSPITAL_GENERAL_ID, [{"property": "hospital_overall_rating", "value": ["1","2"], "operator": "in"}])
        signals = []
        for row in results:
            rating = row.get("hospital_overall_rating", "")
            name = row.get("facility_name", "Unknown")
            city = row.get("city", "")
            state = row.get("state", "")
            description = (f"{name} in {city}, {state} received a CMS overall rating of {rating}/5 stars. "
                f"Low ratings indicate quality deficits. High-priority target for care coordination and safety tools.")
            signals.append(DemandSignal(
                source=SignalSource.CMS_HOSPITAL_QUALITY,
                source_record_id=f"cms_star_{row.get('facility_id', name[:30])}",
                signal_type=SignalType.QUALITY_DEFICIT,
                title=f"Low quality hospital ({rating}★): {name}, {state}",
                description=description,
                condition_or_topic="Hospital Quality",
                innovation_category_hint="SOFTWARE",
                keywords=["hospital quality", "cms rating", state.lower()],
                geographic_scope=GeographicScope.FACILITY,
                state_code=state,
                location_name=f"{name}, {city}, {state}",
                magnitude=float(rating) if str(rating).isdigit() else None,
                magnitude_unit="CMS star rating (1-5)",
                national_average=3.0,
                data_year=2024,
                data_freshness_days=90,
                source_url="https://www.medicare.gov/care-compare/",
                confidence_score=0.9,
                raw_data={k: str(v)[:200] for k, v in row.items()},
            ))
        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]

    async def _fetch_hcahps(self) -> AsyncIterator[List[DemandSignal]]:
        measures = {
            "H_COMP_1_A_P": "Nurse Communication",
            "H_COMP_2_A_P": "Doctor Communication",
            "H_COMP_7_A": "Care Transitions",
            "H_RESP_RATE_P": "Staff Responsiveness",
        }
        for measure_id, measure_name in measures.items():
            results = await self._cms_query(HCAHPS_ID, [{"property": "hcahps_measure_id", "value": measure_id, "operator": "="}], limit=300)
            signals = []
            for row in results:
                score = row.get("hcahps_answer_percent")
                if not score:
                    continue
                try:
                    score_val = float(score)
                except (ValueError, TypeError):
                    continue
                if score_val > 60:
                    continue
                name = row.get("facility_name", "Unknown")
                state = row.get("state", "")
                description = (f"{name} in {state} scored {score_val}% on '{measure_name}' (national avg ~75%). "
                    f"Signals unmet need for communication technology and care coordination software.")
                signals.append(DemandSignal(
                    source=SignalSource.CMS_HCAHPS,
                    source_record_id=f"hcahps_{row.get('facility_id','')}_{measure_id}",
                    signal_type=SignalType.QUALITY_DEFICIT,
                    title=f"Low {measure_name}: {score_val}% at {name}, {state}",
                    description=description,
                    condition_or_topic=f"Patient Experience: {measure_name}",
                    innovation_category_hint="SOFTWARE",
                    keywords=["hcahps", "patient experience", measure_name.lower(), state.lower()],
                    geographic_scope=GeographicScope.FACILITY,
                    state_code=state,
                    location_name=f"{name}, {state}",
                    magnitude=score_val,
                    magnitude_unit="percent positive responses",
                    national_average=75.0,
                    data_year=2024,
                    data_freshness_days=90,
                    source_url="https://www.medicare.gov/care-compare/",
                    confidence_score=0.88,
                    raw_data={k: str(v)[:200] for k, v in row.items()},
                ))
            for i in range(0, len(signals), self.batch_size):
                yield signals[i:i + self.batch_size]

    async def _fetch_readmissions(self) -> AsyncIterator[List[DemandSignal]]:
        results = await self._cms_query(READMISSIONS_ID, [{"property": "compared_to_national", "value": "Worse than the National Rate", "operator": "="}])
        signals = []
        for row in results:
            name = row.get("facility_name", "")
            state = row.get("state", "")
            measure = row.get("measure_name", "")
            description = (f"{name} in {state} has readmission rates worse than national average for: {measure}. "
                f"Signals demand for post-discharge care management and remote monitoring platforms.")
            signals.append(DemandSignal(
                source=SignalSource.CMS_HOSPITAL_QUALITY,
                source_record_id=f"readmit_{row.get('facility_id','')}_{measure[:30]}",
                signal_type=SignalType.QUALITY_DEFICIT,
                title=f"High readmissions ({measure[:60]}): {name}, {state}",
                description=description,
                condition_or_topic=measure,
                innovation_category_hint="SOFTWARE",
                keywords=["readmissions", "care transitions", state.lower()],
                geographic_scope=GeographicScope.FACILITY,
                state_code=state,
                location_name=f"{name}, {state}",
                data_year=2024,
                data_freshness_days=90,
                source_url="https://data.cms.gov/provider-data/",
                confidence_score=0.9,
                raw_data={k: str(v)[:200] for k, v in row.items()},
            ))
        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]
