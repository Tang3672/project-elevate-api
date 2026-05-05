"""
CDC PLACES Connector (Rewritten for 2025 wide format)
=====================================================
The 2025 PLACES dataset is wide format: one row per county,
all measures as separate columns (diabetes_crudeprev, copd_crudeprev, etc.)
"""
import logging
from typing import AsyncIterator, List
from app.ingestion.connectors.base import BaseConnector
from app.models.demand_signal import (
    DemandSignal, SignalSource, SignalType, GeographicScope
)

logger = logging.getLogger(__name__)
SODA_BASE = "https://data.cdc.gov/resource"
DATASET_ID = "xyst-f73f"

# Map: (column_name, measure_name, category_hint, signal_type)
MEASURE_COLUMNS = [
    ("diabetes_crudeprev",   "Type 2 Diabetes",         "SOFTWARE",       SignalType.DISEASE_BURDEN),
    ("chd_crudeprev",        "Coronary Heart Disease",   "HARDWARE",       SignalType.DISEASE_BURDEN),
    ("stroke_crudeprev",     "Stroke",                   "SOFTWARE",       SignalType.DISEASE_BURDEN),
    ("copd_crudeprev",       "COPD / Emphysema",         "HARDWARE",       SignalType.DISEASE_BURDEN),
    ("depression_crudeprev", "Depression",               "SOFTWARE",       SignalType.DISEASE_BURDEN),
    ("obesity_crudeprev",    "Obesity",                  "SERVICE",        SignalType.DISEASE_BURDEN),
    ("bphigh_crudeprev",     "High Blood Pressure",      "SOFTWARE",       SignalType.DISEASE_BURDEN),
    ("kidney_crudeprev",     "Chronic Kidney Disease",   "HARDWARE",       SignalType.DISEASE_BURDEN),
    ("casthma_crudeprev",    "Current Asthma",           "SOFTWARE",       SignalType.DISEASE_BURDEN),
    ("cancer_crudeprev",     "Cancer (excl. skin)",      "HARDWARE",       SignalType.DISEASE_BURDEN),
    ("arthritis_crudeprev",  "Arthritis",                "HARDWARE",       SignalType.DISEASE_BURDEN),
    ("mhlth_crudeprev",      "Poor Mental Health",       "SERVICE",        SignalType.DISEASE_BURDEN),
    ("sleep_crudeprev",      "Short Sleep (<7hrs)",      "SOFTWARE",       SignalType.POPULATION_RISK),
    ("dental_crudeprev",     "No Dental Visit",          "SERVICE",        SignalType.CARE_GAP),
    ("checkup_crudeprev",    "No Annual Checkup",        "SERVICE",        SignalType.CARE_GAP),
    ("disability_crudeprev", "Any Disability",           "HARDWARE",       SignalType.CARE_GAP),
    ("colon_screen_crudeprev","No Colorectal Screening", "HARDWARE",       SignalType.CARE_GAP),
    ("mammouse_crudeprev",   "No Mammogram",             "HARDWARE",       SignalType.CARE_GAP),
]


class CDCPlacesConnector(BaseConnector):
    source_name = "cdc_places"
    description = "CDC PLACES 2025: county-level chronic disease prevalence"
    update_frequency_hours = 24 * 90
    batch_size = 150

    def __init__(self, app_token: str = "", level: str = "county"):
        super().__init__()
        self.app_token = app_token

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        offset = 0
        limit = 500
        total_processed = 0

        while True:
            params = {
                "$limit": str(limit),
                "$offset": str(offset),
                "$order": "stateabbr,countyname",
            }
            # Token not used for this dataset - works without authentication

            try:
                rows = await self._get_json(f"{SODA_BASE}/{DATASET_ID}.json", params)
            except Exception as e:
                logger.error(f"CDC PLACES fetch failed at offset {offset}: {e}")
                break

            if not isinstance(rows, list) or len(rows) == 0:
                break

            signals = []
            for row in rows:
                row_signals = self._row_to_signals(row)
                signals.extend(row_signals)

            total_processed += len(rows)

            # Yield in batches
            for i in range(0, len(signals), self.batch_size):
                yield signals[i:i + self.batch_size]

            if len(rows) < limit:
                break
            offset += limit

        logger.info(f"CDC PLACES: processed {total_processed} counties")

    def _row_to_signals(self, row: dict) -> List[DemandSignal]:
        signals = []
        state = row.get("stateabbr", "")
        county = row.get("countyname", "Unknown")
        fips = row.get("countyfips", "")
        try:
            population = int(row.get("totalpopulation", 0))
        except (ValueError, TypeError):
            population = 0

        if population < 1000:
            return []

        location_name = f"{county}, {state}"

        for col, measure_name, category_hint, sig_type in MEASURE_COLUMNS:
            val = row.get(col)
            if val is None:
                continue
            try:
                value = float(val)
            except (ValueError, TypeError):
                continue

            # Only flag meaningful burden levels
            if sig_type == SignalType.DISEASE_BURDEN and value < 8.0:
                continue
            if sig_type == SignalType.CARE_GAP and value < 20.0:
                continue
            if sig_type == SignalType.POPULATION_RISK and value < 25.0:
                continue

            description = (
                f"{measure_name} prevalence in {county}, {state}: {value}% of adults "
                f"(population: {population:,}). CDC PLACES 2025 data. "
                f"Geographic demand signal for {category_hint.lower()} innovations "
                f"addressing {measure_name.lower()}."
            )

            signals.append(DemandSignal(
                source=SignalSource.CDC_PLACES,
                source_record_id=f"{fips}_{col}",
                signal_type=sig_type,
                title=f"{measure_name}: {value}% in {county}, {state}",
                description=description,
                condition_or_topic=measure_name,
                innovation_category_hint=category_hint,
                keywords=[measure_name.lower(), "chronic disease", "prevalence", state.lower()],
                geographic_scope=GeographicScope.COUNTY,
                state_code=state,
                county_fips=fips,
                location_name=location_name,
                magnitude=value,
                magnitude_unit="percent of adults",
                data_year=2025,
                data_freshness_days=90,
                source_url=f"https://data.cdc.gov/resource/{DATASET_ID}.json",
                confidence_score=0.92,
                raw_data={"county": county, "state": state, "measure": col, "value": val},
            ))

        return signals
