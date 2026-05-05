"""
CMS Hospital Quality Connector
================================
Source: data.cms.gov / data.medicare.gov (Socrata/SODA)
Data:   Hospital Compare replacement — quality measures, HCAHPS, readmissions,
        complications, HAIs, value-based purchasing scores
Update: Quarterly
Auth:   None required

Why high-value: Hospital quality deficits are *care gap* demand signals.
- Low HCAHPS communication scores → communication tool innovation needed
- High readmission rates → care coordination / discharge planning gap
- High complication rates → surgical tool or monitoring device opportunity
- Low sepsis care scores → sepsis detection software needed

We ingest facility-level scores and flag outliers (low performers) as
the strongest demand signals — that's where hospitals most need innovation.
"""

import logging
from typing import AsyncIterator, List

from app.ingestion.connectors.base import BaseConnector
from app.models.demand_signal import (
    DemandSignal, SignalSource, SignalType, GeographicScope
)

logger = logging.getLogger(__name__)

CMS_BASE = "https://data.cms.gov/provider-data/api/1/datastore/sql"


class CMSHospitalQualityConnector(BaseConnector):
    """
    Ingests CMS Hospital General Information and HCAHPS patient survey data.
    Flags hospitals with poor quality scores as demand signal locations.
    """
    source_name = "cms_hospital_quality"
    description = "CMS Hospital Compare: quality ratings, HCAHPS, readmissions, HAIs"
    update_frequency_hours = 24 * 90  # quarterly
    batch_size = 100

    # CMS Provider Data Catalog dataset UUIDs (verified 2025)
    HOSPITAL_GENERAL_UUID = "xubh-q36u"    # Hospital general info + star ratings
    HCAHPS_UUID           = "dgck-syfz"    # Patient survey HCAHPS scores
    READMISSIONS_UUID     = "9n3s-kdb3"    # Unplanned hospital visits
    COMPLICATIONS_UUID    = "632h-zaca"    # Complications and deaths
    HAI_UUID              = "77hc-ibv8"    # Healthcare-associated infections

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        # 1. Overall hospital star ratings (low performers = demand signals)
        async for batch in self._fetch_star_ratings():
            yield batch
        # 2. HCAHPS patient experience scores
        async for batch in self._fetch_hcahps():
            yield batch
        # 3. Readmission rates
        async for batch in self._fetch_readmissions():
            yield batch

    async def _fetch_star_ratings(self) -> AsyncIterator[List[DemandSignal]]:
        """Fetch hospitals with 1-2 star overall ratings (clear demand signal locations)."""
        url = f"{CMS_BASE}"
        params = {
            "query": f"""
                [SELECT facility_id, facility_name, address, city, state,
                        zip_code, county_name, hospital_type, hospital_ownership,
                        emergency_services, hospital_overall_rating
                 FROM {self.HOSPITAL_GENERAL_UUID}
                 WHERE hospital_overall_rating IN ('1','2')
                 LIMIT 500][offset 0]
            """
        }

        try:
            data = await self._get_json(url, params)
            results = data if isinstance(data, list) else data.get("results", [])
        except Exception as e:
            logger.error(f"CMS star ratings fetch failed: {e}")
            return

        signals = []
        for row in results:
            rating = row.get("hospital_overall_rating", "")
            name = row.get("facility_name", "Unknown Hospital")
            city = row.get("city", "")
            state = row.get("state", "")
            hosp_type = row.get("hospital_type", "")
            ownership = row.get("hospital_ownership", "")
            has_er = row.get("emergency_services", "No")

            description = (
                f"{name} in {city}, {state} received an overall CMS rating of "
                f"{rating} out of 5 stars. Type: {hosp_type}. Ownership: {ownership}. "
                f"Emergency services: {has_er}. "
                f"Low CMS star ratings correlate with systemic quality deficits across "
                f"safety, readmissions, patient experience, effectiveness, and timeliness. "
                f"This hospital represents a high-priority target for quality improvement "
                f"technology: care coordination platforms, clinical decision support, "
                f"patient safety monitoring, and discharge management tools."
            )

            signals.append(DemandSignal(
                source=SignalSource.CMS_HOSPITAL_QUALITY,
                source_record_id=f"cms_star_{row.get('facility_id', name[:30])}",
                signal_type=SignalType.QUALITY_DEFICIT,
                title=f"Low quality hospital ({rating}★): {name}, {state}",
                description=description,
                condition_or_topic="Hospital Quality",
                innovation_category_hint="SOFTWARE",
                keywords=[
                    "hospital quality", "cms star rating", "low performance",
                    "quality improvement", state.lower(), city.lower()
                ],
                geographic_scope=GeographicScope.FACILITY,
                state_code=state,
                location_name=f"{name}, {city}, {state}",
                magnitude=float(rating) if rating.isdigit() else None,
                magnitude_unit="CMS star rating (1-5)",
                national_average=3.0,
                data_year=2024,
                data_period="2024",
                data_freshness_days=90,
                source_url="https://www.medicare.gov/care-compare/",
                confidence_score=0.9,
                raw_data={k: str(v)[:200] for k, v in row.items()},
            ))

        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]

    async def _fetch_hcahps(self) -> AsyncIterator[List[DemandSignal]]:
        """Fetch poor HCAHPS communication/responsiveness scores as care gap signals."""
        url = f"{CMS_BASE}"
        # Target the communication and care transition measures (most actionable for inventors)
        measures_of_interest = [
            "H_COMP_1_A_P",  # Nurse communication: always
            "H_COMP_2_A_P",  # Doctor communication: always
            "H_COMP_6_Y_P",  # Discharge info given
            "H_COMP_7_A",    # Care transitions
            "H_CLEAN_HSP_A_P",  # Cleanliness: always
            "H_RESP_RATE_P", # Staff responsiveness
        ]

        measure_names = {
            "H_COMP_1_A_P":   "Nurse Communication",
            "H_COMP_2_A_P":   "Doctor Communication",
            "H_COMP_6_Y_P":   "Discharge Information",
            "H_COMP_7_A":     "Care Transitions",
            "H_CLEAN_HSP_A_P":"Hospital Cleanliness",
            "H_RESP_RATE_P":  "Staff Responsiveness",
        }

        for measure_id in measures_of_interest:
            measure_name = measure_names.get(measure_id, measure_id)
            params = {
                "query": f"""
                    [SELECT facility_id, facility_name, state, hcahps_measure_id,
                            hcahps_answer_description, hcahps_answer_percent,
                            number_of_completed_surveys, survey_response_rate_percent
                     FROM {self.HCAHPS_UUID}
                     WHERE hcahps_measure_id='{measure_id}'
                       AND hcahps_answer_percent IS NOT NULL
                     ORDER BY hcahps_answer_percent ASC
                     LIMIT 200][offset 0]
                """
            }
            try:
                data = await self._get_json(url, params)
                results = data if isinstance(data, list) else []
            except Exception as e:
                logger.warning(f"HCAHPS measure {measure_id} failed: {e}")
                continue

            signals = []
            for row in results:
                score = row.get("hcahps_answer_percent")
                if not score:
                    continue
                try:
                    score_val = float(score)
                except ValueError:
                    continue

                if score_val > 60:  # only flag genuinely poor performers
                    continue

                name = row.get("facility_name", "Unknown")
                state = row.get("state", "")

                description = (
                    f"{name} in {state} scored {score_val}% on HCAHPS '{measure_name}'. "
                    f"The national average for this measure is approximately 70-80%. "
                    f"Poor {measure_name.lower()} scores signal unmet need for "
                    f"healthcare communication technology, digital patient engagement "
                    f"platforms, discharge planning tools, and care coordination software."
                )

                signals.append(DemandSignal(
                    source=SignalSource.CMS_HCAHPS,
                    source_record_id=f"hcahps_{row.get('facility_id','')}_{measure_id}",
                    signal_type=SignalType.QUALITY_DEFICIT,
                    title=f"Low {measure_name}: {score_val}% at {name}, {state}",
                    description=description,
                    condition_or_topic=f"Patient Experience: {measure_name}",
                    innovation_category_hint="SOFTWARE",
                    keywords=[
                        "hcahps", "patient experience", measure_name.lower(),
                        "care quality", state.lower(), "patient satisfaction"
                    ],
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
        """Flag hospitals with high readmission rates by condition."""
        url = f"{CMS_BASE}"
        params = {
            "query": f"""
                [SELECT facility_id, facility_name, state, measure_name,
                        score, compared_to_national
                 FROM {self.READMISSIONS_UUID}
                 WHERE compared_to_national='Worse than the National Rate'
                 LIMIT 500][offset 0]
            """
        }

        try:
            data = await self._get_json(url, params)
            results = data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"CMS readmissions fetch failed: {e}")
            return

        signals = []
        for row in results:
            name = row.get("facility_name", "")
            state = row.get("state", "")
            measure = row.get("measure_name", "")
            score = row.get("score", "")

            description = (
                f"{name} in {state} has readmission rates worse than the national "
                f"average for: {measure} (score: {score}). "
                f"High readmission rates signal demand for post-discharge care management, "
                f"remote patient monitoring, care coordination platforms, and predictive "
                f"analytics tools to identify high-risk patients before discharge."
            )

            signals.append(DemandSignal(
                source=SignalSource.CMS_HOSPITAL_QUALITY,
                source_record_id=f"readmit_{row.get('facility_id','')}_{measure[:30]}",
                signal_type=SignalType.QUALITY_DEFICIT,
                title=f"High readmissions ({measure[:60]}): {name}, {state}",
                description=description,
                condition_or_topic=measure,
                innovation_category_hint="SOFTWARE",
                keywords=[
                    "readmissions", "care transitions", "post-discharge",
                    measure.lower()[:50], state.lower()
                ],
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
