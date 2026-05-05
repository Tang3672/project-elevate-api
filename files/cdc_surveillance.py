"""
CDC Real-Time Surveillance Connectors
=======================================
Two connectors:
  1. CDCWastewaterConnector — NWSS wastewater surveillance (5-7 day leading indicator)
  2. CDCFluViewConnector    — Weekly ILI/flu/RSV/COVID activity

Source: data.cdc.gov (NWSS), api.delphi.cmu.edu (FluView via Delphi Epidata)
Update: Weekly (Fridays)
Auth:   None

Why high-value: These are the FASTEST public health signals available.
Wastewater detects community viral spread 5-7 days before clinical testing.
Flu activity spikes are direct signals for hospital capacity tools,
respiratory device demand, and remote monitoring platform usage.
"""

import logging
from typing import AsyncIterator, List
from datetime import datetime, timedelta

from app.ingestion.connectors.base import BaseConnector
from app.models.demand_signal import (
    DemandSignal, SignalSource, SignalType, GeographicScope
)

logger = logging.getLogger(__name__)

# SODA dataset IDs
NWSS_DATASET = "2ew6-ywp6"   # NWSS SARS-CoV-2 wastewater data
SODA_BASE = "https://data.cdc.gov/resource"


class CDCWastewaterConnector(BaseConnector):
    """
    CDC National Wastewater Surveillance System (NWSS).
    Fetches the most recent week's wastewater pathogen data by HHS region.
    Flags regions with "increasing" or "high" activity levels.
    """
    source_name = "cdc_wastewater"
    description = "CDC NWSS wastewater surveillance — viral early warning by region"
    update_frequency_hours = 24 * 7  # weekly
    batch_size = 50

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        # Get recent data, grouped by state/region
        url = f"{SODA_BASE}/{NWSS_DATASET}.json"
        # Last 30 days
        cutoff = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")

        params = {
            "$where": f"date_end >= '{cutoff}'",
            "$select": (
                "wwtp_jurisdiction,reporting_jurisdiction,date_end,"
                "detect_prop_15d,percentile,ptc_15d,counties_served,"
                "population_served,key_plot_id"
            ),
            "$order": "date_end DESC, ptc_15d DESC",
            "$limit": "500",
        }

        try:
            data = await self._get_json(url, params)
            if not isinstance(data, list):
                return
        except Exception as e:
            logger.error(f"NWSS fetch failed: {e}")
            return

        # Aggregate by jurisdiction (state) and get worst-case week
        by_state: dict[str, list] = {}
        for row in data:
            state = row.get("wwtp_jurisdiction", row.get("reporting_jurisdiction", ""))
            if state:
                by_state.setdefault(state, []).append(row)

        signals = []
        for state, rows in by_state.items():
            # Use the most recent row for this state
            latest = rows[0]
            detect_prop = latest.get("detect_prop_15d")
            percentile = latest.get("percentile")
            ptc_change = latest.get("ptc_15d")  # % change over 15 days
            date_end = latest.get("date_end", "")[:10]
            pop_served = latest.get("population_served", "unknown")

            if detect_prop is None:
                continue

            try:
                detect_val = float(detect_prop) * 100
                pct_val = float(percentile) if percentile else None
                ptc_val = float(ptc_change) if ptc_change else 0
            except (ValueError, TypeError):
                continue

            # Only flag elevated or rapidly increasing signals
            if detect_val < 10 and (pct_val is None or pct_val < 60) and ptc_val < 50:
                continue

            trend = "increasing" if ptc_val > 0 else "decreasing" if ptc_val < 0 else "stable"
            severity = "high" if pct_val and pct_val > 75 else "elevated" if pct_val and pct_val > 50 else "moderate"

            description = (
                f"CDC wastewater surveillance ({date_end}): {severity} SARS-CoV-2 signal "
                f"detected in {state}. Detection: {detect_val:.1f}% of sites positive. "
                f"National percentile: {pct_val:.0f}th percentile. "
                f"15-day trend: {ptc_val:+.1f}% ({trend}). "
                f"Population covered by monitoring: {pop_served:,} people. "
                f"Wastewater signals precede clinical case surges by 5-7 days. "
                f"Elevated signals indicate upcoming demand for: hospital surge capacity tools, "
                f"respiratory monitoring devices, telehealth platforms, ICU management "
                f"software, and infection control products in {state}."
            )

            signals.append(DemandSignal(
                source=SignalSource.CDC_WASTEWATER,
                source_record_id=f"nwss_{state}_{date_end}",
                signal_type=SignalType.SURVEILLANCE_ALERT,
                title=f"Wastewater COVID signal ({severity}): {state} — {detect_val:.0f}% sites positive",
                description=description,
                condition_or_topic="COVID-19 / SARS-CoV-2",
                innovation_category_hint="HARDWARE",
                keywords=[
                    "wastewater surveillance", "covid-19", "SARS-CoV-2",
                    "early warning", state.lower(), "outbreak detection"
                ],
                geographic_scope=GeographicScope.STATE,
                state_code=state,
                location_name=state,
                magnitude=detect_val,
                magnitude_unit="percent of monitoring sites positive",
                trend_direction=trend,
                trend_magnitude=ptc_val,
                data_year=int(date_end[:4]) if date_end else datetime.utcnow().year,
                data_period=date_end,
                data_freshness_days=7,
                source_url="https://www.cdc.gov/nwss/",
                confidence_score=0.88,
                raw_data={k: str(v)[:200] for k, v in latest.items()},
            ))

        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]


class CDCFluViewConnector(BaseConnector):
    """
    Flu/ILI/respiratory activity via CMU Delphi Epidata API.
    Weekly national and HHS regional surveillance.
    """
    source_name = "cdc_fluview"
    description = "CDC FluView ILI / respiratory activity via Delphi Epidata"
    update_frequency_hours = 24 * 7
    batch_size = 20

    DELPHI_URL = "https://api.delphi.cmu.edu/epidata/fluview/"

    # HHS regions + national
    REGIONS = [
        "nat", "hhs1", "hhs2", "hhs3", "hhs4",
        "hhs5", "hhs6", "hhs7", "hhs8", "hhs9", "hhs10"
    ]

    REGION_NAMES = {
        "nat":  "National",
        "hhs1": "HHS Region 1 (New England)",
        "hhs2": "HHS Region 2 (NY/NJ)",
        "hhs3": "HHS Region 3 (Mid-Atlantic)",
        "hhs4": "HHS Region 4 (Southeast)",
        "hhs5": "HHS Region 5 (Midwest)",
        "hhs6": "HHS Region 6 (South Central)",
        "hhs7": "HHS Region 7 (Plains)",
        "hhs8": "HHS Region 8 (Mountain)",
        "hhs9": "HHS Region 9 (Pacific)",
        "hhs10":"HHS Region 10 (Northwest)",
    }

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        """Fetch the last 4 weeks of ILI data for all regions."""
        # Get current epiweek range (last 4 weeks)
        now = datetime.utcnow()
        current_week = now.isocalendar()[1]
        current_year = now.year
        # Format: YYYYWW
        epiweeks = f"{current_year}{current_week:02d}-{current_year}{min(current_week+3, 52):02d}"

        params = {
            "regions": ",".join(self.REGIONS),
            "epiweeks": epiweeks,
        }

        try:
            data = await self._get_json(self.DELPHI_URL, params)
            results = data.get("epidata", [])
        except Exception as e:
            logger.error(f"FluView Delphi fetch failed: {e}")
            return

        if not results:
            return

        # Group by region, take most recent week
        by_region: dict[str, dict] = {}
        for r in results:
            reg = r.get("region", "")
            epiweek = r.get("epiweek", 0)
            if reg not in by_region or epiweek > by_region[reg].get("epiweek", 0):
                by_region[reg] = r

        signals = []
        for region, row in by_region.items():
            ili = row.get("wili")  # weighted ILI %
            num_patients = row.get("num_patients", 0)
            num_ili = row.get("num_ili", 0)
            epiweek = str(row.get("epiweek", ""))

            if ili is None:
                continue

            try:
                ili_val = float(ili)
            except (ValueError, TypeError):
                continue

            region_name = self.REGION_NAMES.get(region, region)
            week_str = f"{epiweek[:4]} Week {epiweek[4:]}" if len(epiweek) >= 6 else epiweek

            # Seasonal baseline: ~2.5% ILI is typical; flag above 4%
            severity = "high" if ili_val > 6 else "elevated" if ili_val > 4 else "moderate"

            if ili_val < 3.0 and region != "nat":
                continue  # filter noise

            description = (
                f"CDC FluView ({week_str}): {severity} influenza-like illness activity "
                f"in {region_name}. ILI rate: {ili_val:.2f}% of outpatient visits. "
                f"Reporting providers saw {num_ili:,} ILI cases out of {num_patients:,} total visits. "
                f"{'Above seasonal baseline' if ili_val > 3.5 else 'Near baseline'} for this time of year. "
                f"Elevated respiratory illness signals near-term demand for: "
                f"rapid flu/RSV diagnostics, antiviral prescribing decision support, "
                f"hospital capacity management tools, telemedicine platforms, "
                f"and home monitoring devices for high-risk patients."
            )

            signals.append(DemandSignal(
                source=SignalSource.CDC_FLUVIEW,
                source_record_id=f"fluview_{region}_{epiweek}",
                signal_type=SignalType.SURVEILLANCE_ALERT,
                title=f"ILI Activity ({severity}): {region_name} — {ili_val:.2f}% of visits",
                description=description,
                condition_or_topic="Influenza / Respiratory Illness",
                innovation_category_hint="HARDWARE",
                keywords=[
                    "influenza", "ILI", "flu season", "respiratory illness",
                    "surveillance", region_name.lower()
                ],
                geographic_scope=GeographicScope.NATIONAL if region == "nat" else GeographicScope.REGIONAL,
                magnitude=ili_val,
                magnitude_unit="percent of outpatient visits with ILI",
                national_average=2.5,
                data_year=int(epiweek[:4]) if epiweek else datetime.utcnow().year,
                data_period=week_str,
                data_freshness_days=7,
                source_url="https://www.cdc.gov/fluview/",
                confidence_score=0.92,
                raw_data={k: str(v)[:200] for k, v in row.items()},
            ))

        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]
