"""
CDC Real-Time Surveillance Connectors (Fixed v2)
"""
import logging
from typing import AsyncIterator, List
from datetime import datetime, timedelta
from app.ingestion.connectors.base import BaseConnector
from app.models.demand_signal import (
    DemandSignal, SignalSource, SignalType, GeographicScope
)

logger = logging.getLogger(__name__)
SODA_BASE = "https://data.cdc.gov/resource"
NWSS_DATASET_IDS = ["2ew6-ywp6", "g653-rqe2"]


class CDCWastewaterConnector(BaseConnector):
    source_name = "cdc_wastewater"
    description = "CDC NWSS wastewater surveillance"
    update_frequency_hours = 24 * 7
    batch_size = 50

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        cutoff = (datetime.utcnow() - timedelta(days=45)).strftime("%Y-%m-%dT00:00:00")
        data = None
        for dataset_id in NWSS_DATASET_IDS:
            try:
                result = await self._get_json(f"{SODA_BASE}/{dataset_id}.json", {
                    "$where": f"date_end >= '{cutoff}'",
                    "$order": "date_end DESC",
                    "$limit": "1000",
                })
                if isinstance(result, list) and len(result) > 0:
                    data = result
                    logger.info(f"NWSS: using dataset {dataset_id}, {len(data)} rows")
                    break
            except Exception as e:
                logger.debug(f"NWSS dataset {dataset_id} failed: {e}")
                continue

        if not data:
            logger.warning("NWSS: no working dataset found")
            return

        by_state: dict[str, dict] = {}
        for row in data:
            state = (row.get("wwtp_jurisdiction") or row.get("reporting_jurisdiction") or "")
            if not state or len(state) > 30:
                continue
            date = row.get("date_end", "")
            if state not in by_state or date > by_state[state].get("date_end", ""):
                by_state[state] = row

        signals = []
        for state, row in by_state.items():
            signal = self._row_to_signal(state, row)
            if signal:
                signals.append(signal)

        logger.info(f"NWSS: {len(signals)} signals generated")
        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]

    def _row_to_signal(self, state, row):
        try:
            raw = (row.get("detect_prop_15d") or row.get("pct_15d") or
                   row.get("ptc_15d") or row.get("percentile"))
            if raw is None:
                return None
            detect_val = float(raw)
            if 0 < detect_val <= 1.0:
                detect_val *= 100
            if detect_val < 1.0:
                return None

            date_end = (row.get("date_end") or "")[:10] or datetime.utcnow().strftime("%Y-%m-%d")
            pct_val = float(row.get("percentile") or 50)
            ptc_val = float(row.get("ptc_15d") or row.get("pct_15d") or 0)

            if detect_val < 10 and pct_val < 50 and ptc_val < 30:
                return None

            trend = "increasing" if ptc_val > 5 else "decreasing" if ptc_val < -5 else "stable"
            severity = "high" if pct_val > 75 else "elevated" if pct_val > 50 else "moderate"
            year = int(date_end[:4]) if date_end else datetime.utcnow().year

            description = (
                f"CDC NWSS wastewater surveillance for {state} ({date_end}): "
                f"{severity} SARS-CoV-2 signal detected. "
                f"Detection rate: {detect_val:.1f}% of monitoring sites positive. "
                f"National percentile: {pct_val:.0f}th. "
                f"15-day trend: {ptc_val:+.1f}% ({trend}). "
                f"Wastewater signals precede clinical case increases by 5-7 days, "
                f"providing early warning for hospital surge capacity planning, "
                f"respiratory monitoring device demand, and infection control in {state}."
            )

            return DemandSignal(
                source=SignalSource.CDC_WASTEWATER,
                source_record_id=f"nwss_{state.lower().replace(' ','_')}_{date_end}",
                signal_type=SignalType.SURVEILLANCE_ALERT,
                title=f"Wastewater COVID signal ({severity}): {state} — {detect_val:.0f}% sites positive",
                description=description,
                condition_or_topic="COVID-19 / SARS-CoV-2",
                innovation_category_hint="HARDWARE",
                keywords=["wastewater", "covid-19", "early warning", state.lower()],
                geographic_scope=GeographicScope.STATE,
                state_code=state,
                location_name=state,
                magnitude=detect_val,
                magnitude_unit="percent of monitoring sites positive",
                trend_direction=trend,
                trend_magnitude=ptc_val,
                data_year=year,
                data_period=date_end,
                data_freshness_days=7,
                source_url="https://www.cdc.gov/nwss/",
                confidence_score=0.85,
                raw_data={k: str(v)[:200] for k, v in row.items()},
            )
        except Exception as e:
            logger.debug(f"NWSS row error for {state}: {e}")
            return None


class CDCFluViewConnector(BaseConnector):
    source_name = "cdc_fluview"
    description = "CDC FluView ILI / respiratory activity"
    update_frequency_hours = 24 * 7
    batch_size = 20

    DELPHI_URL = "https://api.delphi.cmu.edu/epidata/fluview/"
    REGION_NAMES = {
        "nat":"National","hhs1":"HHS Region 1 (New England)","hhs2":"HHS Region 2 (NY/NJ)",
        "hhs3":"HHS Region 3 (Mid-Atlantic)","hhs4":"HHS Region 4 (Southeast)",
        "hhs5":"HHS Region 5 (Midwest)","hhs6":"HHS Region 6 (South Central)",
        "hhs7":"HHS Region 7 (Plains)","hhs8":"HHS Region 8 (Mountain)",
        "hhs9":"HHS Region 9 (Pacific)","hhs10":"HHS Region 10 (Northwest)",
    }

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        signals = await self._fetch_delphi()
        if not signals:
            signals = self._fallback()
        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]

    async def _fetch_delphi(self):
        now = datetime.utcnow()
        week = now.isocalendar()[1]
        year = now.year
        epiweeks = f"{year}{week:02d}-{year}{min(week+3,52):02d}"
        try:
            data = await self._get_json(self.DELPHI_URL, {
                "regions": "nat,hhs1,hhs2,hhs3,hhs4,hhs5,hhs6,hhs7,hhs8,hhs9,hhs10",
                "epiweeks": epiweeks,
            })
            results = data.get("epidata", [])
            if not results:
                return []
            by_region = {}
            for r in results:
                reg = r.get("region","")
                ew = r.get("epiweek",0)
                if reg not in by_region or ew > by_region[reg].get("epiweek",0):
                    by_region[reg] = r
            signals = []
            for region, row in by_region.items():
                ili = row.get("wili") or row.get("ili")
                if ili is None:
                    continue
                try:
                    ili_val = float(ili)
                except (ValueError, TypeError):
                    continue
                if ili_val < 2.0 and region != "nat":
                    continue
                region_name = self.REGION_NAMES.get(region, region)
                epiweek = str(row.get("epiweek",""))
                week_str = f"{epiweek[:4]} Week {epiweek[4:]}" if len(epiweek) >= 6 else epiweek
                severity = "high" if ili_val > 6 else "elevated" if ili_val > 4 else "moderate"
                description = (
                    f"CDC FluView ({week_str}): {severity} influenza-like illness in {region_name}. "
                    f"ILI rate: {ili_val:.2f}% of outpatient visits. "
                    f"Signals demand for rapid flu diagnostics, antiviral prescribing support, "
                    f"hospital capacity tools, and telemedicine for high-risk patients."
                )
                signals.append(DemandSignal(
                    source=SignalSource.CDC_FLUVIEW,
                    source_record_id=f"fluview_{region}_{epiweek}",
                    signal_type=SignalType.SURVEILLANCE_ALERT,
                    title=f"ILI Activity ({severity}): {region_name} — {ili_val:.2f}%",
                    description=description,
                    condition_or_topic="Influenza / Respiratory Illness",
                    innovation_category_hint="HARDWARE",
                    keywords=["influenza","ILI","flu","respiratory",region_name.lower()],
                    geographic_scope=GeographicScope.NATIONAL if region=="nat" else GeographicScope.REGIONAL,
                    magnitude=ili_val,
                    magnitude_unit="percent of outpatient visits with ILI",
                    national_average=2.5,
                    data_year=int(epiweek[:4]) if epiweek else datetime.utcnow().year,
                    data_period=week_str,
                    data_freshness_days=7,
                    source_url="https://www.cdc.gov/fluview/",
                    confidence_score=0.9,
                    raw_data={k: str(v)[:200] for k, v in row.items()},
                ))
            return signals
        except Exception as e:
            logger.warning(f"FluView Delphi failed: {e}")
            return []

    def _fallback(self):
        description = (
            "CDC FluView national respiratory illness surveillance is active. "
            "Seasonal influenza signals ongoing demand for rapid diagnostics, "
            "antiviral prescribing support, and hospital capacity management tools."
        )
        return [DemandSignal(
            source=SignalSource.CDC_FLUVIEW,
            source_record_id=f"fluview_fallback_{datetime.utcnow().year}",
            signal_type=SignalType.SURVEILLANCE_ALERT,
            title="Respiratory Illness Surveillance: National monitoring active",
            description=description,
            condition_or_topic="Influenza / Respiratory Illness",
            innovation_category_hint="HARDWARE",
            keywords=["influenza","ILI","respiratory","national"],
            geographic_scope=GeographicScope.NATIONAL,
            data_year=datetime.utcnow().year,
            data_freshness_days=7,
            source_url="https://www.cdc.gov/fluview/",
            confidence_score=0.7,
        )]
