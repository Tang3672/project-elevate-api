"""
CDC PLACES Connector
====================
Source: data.cdc.gov (Socrata/SODA API)
Data:   Local-level chronic disease estimates at census tract, county, ZIP, city level
Update: Annual
Auth:   None required (app token optional, set CDC_APP_TOKEN env var)

Why this is high-value: PLACES is the only source of census-tract-level chronic
disease prevalence for the entire US. It answers "where does diabetes / COPD /
asthma / depression cluster?" — directly actionable for inventors targeting
specific geographies or underserved populations.

We ingest the COUNTY-level dataset first (smaller, faster) then optionally
the TRACT dataset (500k+ rows). Both use identical field names.
"""

import logging
from typing import AsyncIterator, List
from datetime import datetime

from app.ingestion.connectors.base import BaseConnector
from app.models.demand_signal import (
    DemandSignal, SignalSource, SignalType, GeographicScope
)

logger = logging.getLogger(__name__)

# SODA dataset IDs (verified 2025)
COUNTY_DATASET_ID = "swc5-untb"   # PLACES county-level
TRACT_DATASET_ID  = "cwsq-ngmh"  # PLACES census tract level

SODA_BASE = "https://data.cdc.gov/resource"

# Measures we care about most for innovation demand signal
# Format: (measure_id, human_name, innovation_category_hint, signal_type)
TARGET_MEASURES = [
    ("DIABETES",    "Type 2 Diabetes",             "SOFTWARE",  SignalType.DISEASE_BURDEN),
    ("HEART",       "Coronary Heart Disease",       "HARDWARE",  SignalType.DISEASE_BURDEN),
    ("STROKE",      "Stroke",                       "SOFTWARE",  SignalType.DISEASE_BURDEN),
    ("COPD",        "COPD / Emphysema",             "HARDWARE",  SignalType.DISEASE_BURDEN),
    ("ASTHMA",      "Asthma",                       "SOFTWARE",  SignalType.DISEASE_BURDEN),
    ("CANCER",      "Cancer (excluding skin)",      "HARDWARE",  SignalType.DISEASE_BURDEN),
    ("DEPRESSION",  "Depression",                   "SOFTWARE",  SignalType.DISEASE_BURDEN),
    ("MHLTH",       "Poor Mental Health (14+ days)","SERVICE",   SignalType.DISEASE_BURDEN),
    ("PHLTH",       "Poor Physical Health",         "SOFTWARE",  SignalType.DISEASE_BURDEN),
    ("OBESITY",     "Obesity",                      "SERVICE",   SignalType.DISEASE_BURDEN),
    ("BPHIGH",      "High Blood Pressure",          "SOFTWARE",  SignalType.DISEASE_BURDEN),
    ("HIGHCHOL",    "High Cholesterol",             "PHARMACEUTICALS", SignalType.DISEASE_BURDEN),
    ("KIDNEY",      "Chronic Kidney Disease",       "HARDWARE",  SignalType.DISEASE_BURDEN),
    ("ARTHRITIS",   "Arthritis",                    "HARDWARE",  SignalType.DISEASE_BURDEN),
    ("DENTAL",      "No Dental Visit (past year)",  "SERVICE",   SignalType.CARE_GAP),
    ("MAMMOUSE",    "No Mammogram (women 50-74)",   "HARDWARE",  SignalType.CARE_GAP),
    ("COLON_SCREEN","No Colorectal Screening",      "HARDWARE",  SignalType.CARE_GAP),
    ("CHECKUP",     "No Annual Checkup",            "SERVICE",   SignalType.CARE_GAP),
    ("CASTHMA",     "Current Asthma (adults)",      "SOFTWARE",  SignalType.DISEASE_BURDEN),
    ("SLEEP",       "Short Sleep Duration (<7hrs)", "SOFTWARE",  SignalType.POPULATION_RISK),
    ("ACCESS2",     "Lack of Health Insurance",     "SERVICE",   SignalType.CARE_GAP),
    ("DISABILITY",  "Any Disability",               "HARDWARE",  SignalType.CARE_GAP),
    ("BROADBAND",   "No Broadband Internet",        "SERVICE",   SignalType.CARE_GAP),
]

MEASURE_LOOKUP = {m[0]: m for m in TARGET_MEASURES}


class CDCPlacesConnector(BaseConnector):
    source_name = "cdc_places"
    description = "CDC PLACES: census-tract and county-level chronic disease prevalence"
    update_frequency_hours = 24 * 90   # quarterly re-run is sufficient (annual data)
    batch_size = 200

    def __init__(self, app_token: str = "", level: str = "county"):
        super().__init__()
        self.app_token = app_token
        self.level = level  # "county" or "tract"
        self.dataset_id = COUNTY_DATASET_ID if level == "county" else TRACT_DATASET_ID

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        """Fetch PLACES data by measure, yielding batches of DemandSignals."""
        for measure_id, measure_name, category_hint, sig_type in TARGET_MEASURES:
            try:
                signals = await self._fetch_measure(
                    measure_id, measure_name, category_hint, sig_type
                )
                if signals:
                    # Yield in batches
                    for i in range(0, len(signals), self.batch_size):
                        yield signals[i:i + self.batch_size]
            except Exception as e:
                logger.warning(f"PLACES measure {measure_id} failed: {e}")
                continue

    async def _fetch_measure(
        self,
        measure_id: str,
        measure_name: str,
        category_hint: str,
        sig_type: SignalType
    ) -> List[DemandSignal]:
        """
        Fetch the top 200 locations with highest prevalence for a given measure.
        We focus on the HIGH-burden locations because those are the strongest
        demand signals for inventors.
        """
        url = f"{SODA_BASE}/{self.dataset_id}.json"
        params = {
            "$where": f"measureid='{measure_id}' AND datavaluetypeid='CrdPrv'",
            "$select": (
                "locationid,locationabbr,locationname,locationdesc,"
                "stateabbr,statedesc,"
                "measureid,measure,data_value,data_value_unit,"
                "low_confidence_limit,high_confidence_limit,"
                "totalpopulation,year"
            ),
            "$order": "data_value DESC",
            "$limit": "500",
        }
        if self.app_token:
            params["$$app_token"] = self.app_token

        data = await self._get_json(url, params)
        if not isinstance(data, list):
            return []

        # Filter out suppressed values and very small populations
        rows = [
            r for r in data
            if r.get("data_value") and r.get("totalpopulation")
            and float(r.get("totalpopulation", 0)) > 500
        ]

        signals = []
        for row in rows:
            signal = self._row_to_signal(row, measure_name, category_hint, sig_type)
            if signal:
                signals.append(signal)
        return signals

    def _row_to_signal(
        self,
        row: dict,
        measure_name: str,
        category_hint: str,
        sig_type: SignalType
    ) -> DemandSignal | None:
        try:
            value = float(row["data_value"])
            population = int(row.get("totalpopulation", 0))
            location = row.get("locationdesc") or row.get("locationname", "Unknown")
            state = row.get("stateabbr", "")
            year = int(row.get("year", 2024))

            # Build rich description for embedding quality
            description = (
                f"{measure_name} prevalence in {location}, {state}: {value}% of adults "
                f"(population: {population:,}). "
                f"This represents a {'high' if value > 15 else 'moderate'} burden "
                f"for this {'county' if self.level == 'county' else 'census tract'}. "
                f"Data from CDC PLACES {year}. "
                f"Geographic demand signal for {category_hint.lower()} innovations "
                f"addressing {measure_name.lower()} prevention, management, and care gaps."
            )

            return DemandSignal(
                source=SignalSource.CDC_PLACES,
                source_record_id=f"{row.get('locationid', '')}_{row.get('measureid', '')}_{year}",
                signal_type=sig_type,
                title=f"{measure_name}: {value}% in {location}, {state}",
                description=description,
                condition_or_topic=measure_name,
                innovation_category_hint=category_hint,
                keywords=[
                    measure_name.lower(), "chronic disease", "prevalence",
                    state.lower(), "population health", "cdc places"
                ],
                geographic_scope=GeographicScope.COUNTY if self.level == "county" else GeographicScope.TRACT,
                state_code=state,
                county_fips=row.get("locationid", "") if self.level == "county" else None,
                census_tract=row.get("locationid", "") if self.level == "tract" else None,
                location_name=f"{location}, {state}",
                magnitude=value,
                magnitude_unit="percent of adults",
                trend_direction=None,
                data_year=year,
                data_period=str(year),
                data_freshness_days=self._freshness(year),
                source_url=f"https://chronicdata.cdc.gov/resource/{self.dataset_id}.json",
                confidence_score=0.9,
                raw_data={k: v for k, v in row.items() if k != "embedding"},
            )
        except (KeyError, ValueError, TypeError) as e:
            logger.debug(f"Skipping PLACES row: {e}")
            return None
