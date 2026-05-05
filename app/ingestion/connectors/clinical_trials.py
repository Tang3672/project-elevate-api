"""
ClinicalTrials.gov Connector
==============================
Source: clinicaltrials.gov/api/v2/
Data:   Active/recruiting clinical trials — by condition, intervention, phase
Update: Continuous; we run weekly
Auth:   None required

Why high-value: Clinical trial volume is a leading indicator of future
demand. If 200 trials are recruiting for a condition, it means:
1. The treatment pipeline is active — inventors need supporting tools
2. The condition burden is significant enough for major investment
3. Specific intervention types (devices, drugs, digital) are trending

We aggregate by condition + intervention type to surface innovation demand
areas that are research-validated and commercially emerging.
"""

import logging
from typing import AsyncIterator, List

from app.ingestion.connectors.base import BaseConnector
from app.models.demand_signal import (
    DemandSignal, SignalSource, SignalType, GeographicScope
)

logger = logging.getLogger(__name__)

CT_BASE = "https://clinicaltrials.gov/api/v2"

# Conditions with high innovation potential — sample set to start
# Expand this list based on what demand signals emerge
TARGET_CONDITIONS = [
    "Diabetes Mellitus",
    "Heart Failure",
    "Sepsis",
    "Alzheimer Disease",
    "Depression",
    "Obesity",
    "Chronic Kidney Disease",
    "Atrial Fibrillation",
    "COPD",
    "Breast Cancer",
    "Colorectal Cancer",
    "Stroke",
    "Hypertension",
    "Sleep Apnea",
    "Rheumatoid Arthritis",
    "Parkinson Disease",
    "Multiple Sclerosis",
    "Opioid Use Disorder",
    "Posttraumatic Stress Disorder",
    "Sickle Cell Disease",
]

# Intervention type → innovation category hint
INTERVENTION_CATEGORY_MAP = {
    "DEVICE":      "HARDWARE",
    "DRUG":        "PHARMACEUTICALS",
    "BIOLOGICAL":  "PHARMACEUTICALS",
    "PROCEDURE":   "SERVICE",
    "BEHAVIORAL":  "SERVICE",
    "DIAGNOSTIC_TEST": "HARDWARE",
    "OTHER":       "SOFTWARE",
}


class ClinicalTrialsConnector(BaseConnector):
    """
    Fetches active recruiting trials by condition, aggregating to surface
    high-trial-volume conditions and intervention types as demand signals.
    """
    source_name = "clinical_trials"
    description = "ClinicalTrials.gov: active trial pipeline by condition and intervention"
    update_frequency_hours = 24 * 7  # weekly
    batch_size = 30

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        """For each target condition, summarize the trial landscape."""
        for condition in TARGET_CONDITIONS:
            try:
                signals = await self._fetch_condition_summary(condition)
                if signals:
                    yield signals
            except Exception as e:
                logger.warning(f"ClinicalTrials condition '{condition}' failed: {e}")
                continue

    async def _fetch_condition_summary(
        self, condition: str
    ) -> List[DemandSignal]:
        """
        Fetch trial counts and intervention breakdown for a condition.
        Returns a summary DemandSignal rather than one per trial (too noisy).
        """
        params = {
            "query.cond": condition,
            "filter.overallStatus": "RECRUITING,NOT_YET_RECRUITING,ENROLLING_BY_INVITATION",
            "pageSize": "100",
            "format": "json",
            "fields": (
                "NCTId,BriefTitle,Condition,Phase,StudyType,"
                "InterventionType,InterventionName,"
                "OverallStatus,StartDate,PrimaryCompletionDate,"
                "EnrollmentCount,LocationCountry"
            ),
        }

        data = await self._get_json(f"{CT_BASE}/studies", params)
        studies = data.get("studies", [])
        total = data.get("totalCount", len(studies))

        if not studies or total < 5:
            return []

        # Aggregate intervention types
        intervention_counts: dict[str, int] = {}
        phases: list[str] = []
        enrollment_total = 0
        us_studies = 0

        for study in studies:
            proto = study.get("protocolSection", {})
            design = proto.get("designModule", {})
            interventions = proto.get("armsInterventionsModule", {}).get("interventions", [])
            enrollment = design.get("enrollmentInfo", {}).get("count", 0)
            phases_list = design.get("phases", [])
            locations = proto.get("contactsLocationsModule", {}).get("locations", [])

            for intv in interventions:
                t = intv.get("type", "OTHER")
                intervention_counts[t] = intervention_counts.get(t, 0) + 1

            phases.extend(phases_list)
            if enrollment:
                try:
                    enrollment_total += int(enrollment)
                except (ValueError, TypeError):
                    pass

            for loc in locations:
                if loc.get("country") == "United States":
                    us_studies += 1
                    break

        # Determine primary intervention type
        primary_intv = max(intervention_counts, key=intervention_counts.get) if intervention_counts else "OTHER"
        category_hint = INTERVENTION_CATEGORY_MAP.get(primary_intv, "SOFTWARE")

        # Count phase distribution
        phase_3_4 = sum(1 for p in phases if "PHASE3" in p or "PHASE4" in p)

        # Build rich description
        intv_summary = ", ".join(
            f"{k}: {v}" for k, v in sorted(intervention_counts.items(), key=lambda x: -x[1])
        )

        description = (
            f"ClinicalTrials.gov: {total} active trials recruiting for {condition}. "
            f"US-based trials: {us_studies}. "
            f"Total enrollment target: {enrollment_total:,} participants. "
            f"Phase 3/4 trials (near-market): {phase_3_4}. "
            f"Intervention breakdown: {intv_summary}. "
            f"High trial volume signals validated clinical demand for {condition} solutions. "
            f"Phase 3/4 concentration indicates near-term commercial market development. "
            f"Primary intervention type ({primary_intv.lower()}) signals where "
            f"{category_hint.lower()} innovation is most active."
        )

        return [DemandSignal(
            source=SignalSource.CLINICAL_TRIALS,
            source_record_id=f"ct_condition_{condition.lower().replace(' ', '_')}",
            signal_type=SignalType.RESEARCH_TREND,
            title=f"Active trial pipeline: {condition} ({total} trials, {phase_3_4} Phase 3/4)",
            description=description,
            condition_or_topic=condition,
            innovation_category_hint=category_hint,
            keywords=[
                condition.lower(), "clinical trial", "research pipeline",
                primary_intv.lower(), "recruiting", "phase 3"
            ],
            geographic_scope=GeographicScope.NATIONAL,
            magnitude=float(total),
            magnitude_unit="active recruiting trials",
            data_freshness_days=7,
            source_url=f"https://clinicaltrials.gov/search?cond={condition.replace(' ', '+')}",
            confidence_score=0.88,
            raw_data={
                "condition": condition,
                "total_trials": total,
                "us_studies": us_studies,
                "enrollment_total": enrollment_total,
                "phase_3_4": phase_3_4,
                "intervention_counts": intervention_counts,
            },
        )]
