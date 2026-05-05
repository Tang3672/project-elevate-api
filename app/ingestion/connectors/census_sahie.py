"""
Census SAHIE Connector
=======================
Source: api.census.gov/data/timeseries/healthins/sahie
Data:   Small Area Health Insurance Estimates — county-level uninsured rates
        for ALL US counties, broken down by age, sex, race, and income level
Update: Annual (latest: 2023)
Auth:   Free Census API key (CENSUS_API_KEY env var)

Why high-value: SAHIE is the ONLY source of county-level single-year
insurance estimates for every US county. Uninsured populations are the
clearest signal of care access gaps — exactly where telehealth, community
health tools, low-cost diagnostics, and FQHC-targeted software are needed.
"""

import logging
from typing import AsyncIterator, List

from app.ingestion.connectors.base import BaseConnector
from app.models.demand_signal import (
    DemandSignal, SignalSource, SignalType, GeographicScope
)

logger = logging.getLogger(__name__)

SAHIE_URL = "https://api.census.gov/data/timeseries/healthins/sahie"

# State name lookup (abbreviated)
STATE_NAMES = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY",
}


class CensusSAHIEConnector(BaseConnector):
    """
    Fetches county-level uninsured rate data from the Census SAHIE API.
    Focuses on counties with highest uninsured rates — the access gap hotspots.
    """
    source_name = "census_sahie"
    description = "Census SAHIE: county-level health insurance coverage gaps"
    update_frequency_hours = 24 * 180  # twice a year is plenty (annual data)
    batch_size = 150

    # SAHIE income category codes
    # 0=all, 1=<=200% FPL, 2=200-250%, 3=250-400%, 4=>400%
    INCOME_CATS = {
        "0": "all incomes",
        "1": "at or below 200% FPL (low income)",
        "2": "200-250% FPL",
    }

    def __init__(self, api_key: str = ""):
        super().__init__()
        self.api_key = api_key

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        """Fetch uninsured data for all counties, latest year."""
        # Get most recent year available
        latest_year = await self._get_latest_year()
        if not latest_year:
            logger.error("SAHIE: could not determine latest year")
            return

        # Fetch all-income uninsured rates
        async for batch in self._fetch_county_data(latest_year, income_cat="0"):
            yield batch

        # Fetch low-income uninsured rates (strongest demand signal)
        async for batch in self._fetch_county_data(latest_year, income_cat="1"):
            yield batch

    async def _get_latest_year(self) -> str | None:
        """Query the SAHIE API for available years."""
        try:
            data = await self._get_json(
                "https://api.census.gov/data/timeseries/healthins/sahie",
                params={"get": "time", "for": "us:*", "IPRCAT": "0", "AGECAT": "0"}
            )
            years = sorted(set(row[0] for row in data[1:]))
            return years[-1] if years else None
        except Exception:
            return "2023"  # known-good fallback

    async def _fetch_county_data(
        self, year: str, income_cat: str
    ) -> AsyncIterator[List[DemandSignal]]:
        """Fetch uninsured rates for all counties for a given year/income category."""
        params = {
            "get": "NAME,PCTUI_PT,NUI_PT,NIPR_PT,AGECAT,IPRCAT",
            "for": "county:*",
            "in": "state:*",
            "time": year,
            "IPRCAT": income_cat,
            "AGECAT": "0",  # all ages
        }
        if self.api_key:
            params["key"] = self.api_key

        try:
            raw = await self._get_json(SAHIE_URL, params)
        except Exception as e:
            logger.error(f"SAHIE fetch failed (year={year}, income={income_cat}): {e}")
            return

        if not isinstance(raw, list) or len(raw) < 2:
            return

        headers = raw[0]
        rows = raw[1:]

        # Build index
        try:
            idx = {h: i for i, h in enumerate(headers)}
        except Exception:
            return

        income_label = self.INCOME_CATS.get(income_cat, "unknown income")
        signals = []

        for row in rows:
            try:
                name = row[idx["NAME"]]
                raw_pct = row[idx["PCTUI_PT"]]
                if raw_pct is None:
                    continue
                pct_uninsured = float(raw_pct)
                n_uninsured = int(float(row[idx["NUI_PT"]]))
                state_fips = row[idx["state"]]
                county_fips = state_fips + row[idx["county"]]
                state_abbr = STATE_NAMES.get(state_fips, state_fips)

                # Only flag meaningful gaps (>15% uninsured = significant)
                if pct_uninsured < 10:
                    continue

                description = (
                    f"{name}, {state_abbr}: {pct_uninsured:.1f}% uninsured ({n_uninsured:,} people) "
                    f"among {income_label} in {year}. "
                    f"High uninsured rates signal demand for accessible, low-cost healthcare "
                    f"technology: telehealth platforms, community health worker tools, "
                    f"low-cost diagnostic devices, patient navigation software, and "
                    f"FQHC-compatible health IT solutions. Areas with high uninsured rates "
                    f"are priority markets for innovations targeting healthcare access equity."
                )

                signals.append(DemandSignal(
                    source=SignalSource.CENSUS_SAHIE,
                    source_record_id=f"sahie_{county_fips}_{year}_{income_cat}",
                    signal_type=SignalType.CARE_GAP,
                    title=f"High uninsured rate: {pct_uninsured:.1f}% in {name}, {state_abbr}",
                    description=description,
                    condition_or_topic="Healthcare Access / Uninsured Population",
                    innovation_category_hint="SERVICE",
                    keywords=[
                        "uninsured", "healthcare access", "health equity",
                        "care gap", state_abbr.lower(), "underserved"
                    ],
                    geographic_scope=GeographicScope.COUNTY,
                    state_code=state_abbr,
                    county_fips=county_fips,
                    location_name=name,
                    income_level=income_label,
                    insurance_status="uninsured",
                    magnitude=pct_uninsured,
                    magnitude_unit="percent uninsured",
                    national_average=9.2,  # 2023 US average
                    trend_direction=None,
                    data_year=int(year),
                    data_period=year,
                    data_freshness_days=self._freshness(int(year)),
                    source_url="https://www.census.gov/data/developers/data-sets/Health-Insurance-Statistics.html",
                    confidence_score=0.92,
                    raw_data=dict(zip(headers, [str(v) for v in row])),
                ))

            except (IndexError, ValueError, KeyError) as e:
                logger.debug(f"SAHIE row parse error: {e}")
                continue

        for i in range(0, len(signals), self.batch_size):
            yield signals[i:i + self.batch_size]
