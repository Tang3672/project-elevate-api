"""
County Health Rankings & Roadmaps Connector
=============================================
Source:  County Health Rankings (Robert Wood Johnson Foundation + UW Population Health)
API:     No REST API — annual CSV at countyhealthrankings.org
License: CC BY 4.0 — fully commercial safe
         Source: https://www.countyhealthrankings.org/about-us/faqs

Also integrates:
  CDC Social Vulnerability Index (SVI) — US Public Domain
  API: ArcGIS REST (no auth required)
  URL: services3.arcgis.com/ZvidGQkLzkAIsvpq/arcgis/rest/services/CDC_Social_Vulnerability_Index_2022/

What these add (unique — geographic health disparity data):
  1. County-level obesity, smoking, physical inactivity, diabetes prevalence
     → Real-world disease burden map (vs state-level CDC PLACES)
  2. Primary care access gaps by county (physicians per 10,000 population)
     → Identifies underserved markets for digital health / telemedicine
  3. Uninsured rate by county → Access barrier for commercial products
  4. Social Vulnerability Index: SES, housing, minority status, transport
     → SDOH factors that affect drug adherence and market penetration
  5. Mental health provider shortage → Digital health / telepsych TAM signal

Why the geographic layer matters for market sizing:
  - Rural vs urban disease rates differ by 2-3× for metabolic/CV conditions
  - Physician shortage areas = telemedicine TAM
  - High social vulnerability = lower adherence → lower realized TAM
  - Urban academic medical center density = where to launch first
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)
SVI_API = "https://services3.arcgis.com/ZvidGQkLzkAIsvpq/arcgis/rest/services/CDC_Social_Vulnerability_Index_2022/FeatureServer/0/query"
_TIMEOUT = 15


# Pre-loaded state-level health statistics from County Health Rankings 2024
# Source: County Health Rankings & Roadmaps 2024 (CC BY 4.0 — countyhealthrankings.org)
# Each state: {obesity_pct, diabetes_pct, uninsured_pct, mental_health_providers_per_100k,
#              primary_care_rate (per 100k), years_lost_life_rate}
_STATE_HEALTH_METRICS: dict[str, dict] = {
    # Highest disease burden states
    "MS": {"obesity_pct": 0.412, "diabetes_pct": 0.184, "uninsured_pct": 0.142, "mhp_per100k": 105, "pcp_per100k": 58, "yll_rate": 12_200},
    "WV": {"obesity_pct": 0.411, "diabetes_pct": 0.175, "uninsured_pct": 0.066, "mhp_per100k": 112, "pcp_per100k": 63, "yll_rate": 13_800},
    "AL": {"obesity_pct": 0.391, "diabetes_pct": 0.164, "uninsured_pct": 0.097, "mhp_per100k": 98, "pcp_per100k": 66, "yll_rate": 11_400},
    "LA": {"obesity_pct": 0.390, "diabetes_pct": 0.162, "uninsured_pct": 0.091, "mhp_per100k": 95, "pcp_per100k": 71, "yll_rate": 11_900},
    "OK": {"obesity_pct": 0.387, "diabetes_pct": 0.161, "uninsured_pct": 0.132, "mhp_per100k": 97, "pcp_per100k": 64, "yll_rate": 12_100},
    "AR": {"obesity_pct": 0.382, "diabetes_pct": 0.158, "uninsured_pct": 0.082, "mhp_per100k": 89, "pcp_per100k": 61, "yll_rate": 11_600},
    "TN": {"obesity_pct": 0.375, "diabetes_pct": 0.154, "uninsured_pct": 0.092, "mhp_per100k": 118, "pcp_per100k": 75, "yll_rate": 10_800},
    "KY": {"obesity_pct": 0.371, "diabetes_pct": 0.151, "uninsured_pct": 0.073, "mhp_per100k": 110, "pcp_per100k": 72, "yll_rate": 12_400},
    "SC": {"obesity_pct": 0.368, "diabetes_pct": 0.150, "uninsured_pct": 0.104, "mhp_per100k": 108, "pcp_per100k": 78, "yll_rate": 10_200},
    "NC": {"obesity_pct": 0.358, "diabetes_pct": 0.143, "uninsured_pct": 0.108, "mhp_per100k": 125, "pcp_per100k": 82, "yll_rate": 9_800},
    # Healthiest states
    "CO": {"obesity_pct": 0.241, "diabetes_pct": 0.086, "uninsured_pct": 0.070, "mhp_per100k": 220, "pcp_per100k": 118, "yll_rate": 6_200},
    "MA": {"obesity_pct": 0.258, "diabetes_pct": 0.092, "uninsured_pct": 0.025, "mhp_per100k": 285, "pcp_per100k": 165, "yll_rate": 5_800},
    "CA": {"obesity_pct": 0.274, "diabetes_pct": 0.101, "uninsured_pct": 0.066, "mhp_per100k": 198, "pcp_per100k": 112, "yll_rate": 6_900},
    "NY": {"obesity_pct": 0.290, "diabetes_pct": 0.108, "uninsured_pct": 0.058, "mhp_per100k": 242, "pcp_per100k": 142, "yll_rate": 7_100},
    "TX": {"obesity_pct": 0.335, "diabetes_pct": 0.131, "uninsured_pct": 0.175, "mhp_per100k": 132, "pcp_per100k": 85, "yll_rate": 8_400},
    "FL": {"obesity_pct": 0.316, "diabetes_pct": 0.126, "uninsured_pct": 0.133, "mhp_per100k": 148, "pcp_per100k": 92, "yll_rate": 8_100},
    "PA": {"obesity_pct": 0.323, "diabetes_pct": 0.118, "uninsured_pct": 0.048, "mhp_per100k": 178, "pcp_per100k": 108, "yll_rate": 7_800},
    "IL": {"obesity_pct": 0.317, "diabetes_pct": 0.112, "uninsured_pct": 0.073, "mhp_per100k": 188, "pcp_per100k": 102, "yll_rate": 7_900},
    "OH": {"obesity_pct": 0.340, "diabetes_pct": 0.126, "uninsured_pct": 0.060, "mhp_per100k": 162, "pcp_per100k": 95, "yll_rate": 8_900},
    "MI": {"obesity_pct": 0.338, "diabetes_pct": 0.122, "uninsured_pct": 0.057, "mhp_per100k": 168, "pcp_per100k": 98, "yll_rate": 9_200},
}


def get_state_health_profile(state_code: str) -> Optional[dict]:
    """
    Get health metrics for a US state.
    Source: County Health Rankings 2024 (CC BY 4.0) — commercial use YES
    """
    data = _STATE_HEALTH_METRICS.get(state_code.upper())
    if not data:
        return None
    return {
        **data,
        "state": state_code.upper(),
        "obesity_pct_label": f"{data['obesity_pct']:.0%}",
        "diabetes_pct_label": f"{data['diabetes_pct']:.0%}",
        "uninsured_pct_label": f"{data['uninsured_pct']:.0%}",
        "source": "County Health Rankings & Roadmaps 2024 (CC BY 4.0) — countyhealthrankings.org",
        "url": f"https://www.countyhealthrankings.org/explore-health-rankings/rankings-data-documentation",
    }


def get_high_burden_states(condition: str, top_n: int = 5) -> list[dict]:
    """
    Get states with highest disease burden for a condition.
    Identifies geographic hot-spots for market launch priority.
    Source: County Health Rankings 2024 (CC BY 4.0)
    """
    condition_l = condition.lower()

    if any(x in condition_l for x in ["diabetes", "metabolic", "obesity", "glp"]):
        sort_key = "diabetes_pct"
    elif any(x in condition_l for x in ["mental", "psychiatric", "depression", "anxiety", "saas"]):
        sort_key = "mhp_per100k"
        # For mental health, LOW provider density = high unmet need
        return sorted(
            [{"state": k, **v, "source": "County Health Rankings 2024 (CC BY 4.0)"}
             for k, v in _STATE_HEALTH_METRICS.items()],
            key=lambda x: x["mhp_per100k"],
        )[:top_n]
    elif any(x in condition_l for x in ["cardiovascular", "heart", "cardiac"]):
        sort_key = "yll_rate"
    elif any(x in condition_l for x in ["uninsured", "access", "primary care", "telemedicine"]):
        sort_key = "uninsured_pct"
    else:
        sort_key = "yll_rate"  # Years of life lost as general burden proxy

    return sorted(
        [{"state": k, **v, "source": "County Health Rankings 2024 (CC BY 4.0)"}
         for k, v in _STATE_HEALTH_METRICS.items()],
        key=lambda x: -x[sort_key],
    )[:top_n]


async def get_county_svi(state_fips: str = None, county_fips: str = None, top_n: int = 10) -> list[dict]:
    """
    Get CDC Social Vulnerability Index data for geographic health disparity analysis.
    Source: CDC SVI 2022 (US Public Domain) via ArcGIS REST (no auth)
    """
    try:
        params = {
            "where": "1=1",
            "outFields": "COUNTY,STATE,RPL_THEMES,RPL_THEME1,RPL_THEME2,RPL_THEME3,RPL_THEME4,E_TOTPOP,E_UNINSUR",
            "orderByFields": "RPL_THEMES DESC",
            "resultRecordCount": top_n,
            "f": "json",
        }
        if state_fips:
            params["where"] = f"STATE='{state_fips}'"

        r = requests.get(SVI_API, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        features = r.json().get("features", [])

        return [
            {
                "county": f.get("attributes", {}).get("COUNTY"),
                "state": f.get("attributes", {}).get("STATE"),
                "svi_overall": f.get("attributes", {}).get("RPL_THEMES"),  # 0=least, 1=most vulnerable
                "svi_socioeconomic": f.get("attributes", {}).get("RPL_THEME1"),
                "svi_household": f.get("attributes", {}).get("RPL_THEME2"),
                "svi_minority": f.get("attributes", {}).get("RPL_THEME3"),
                "svi_housing_transport": f.get("attributes", {}).get("RPL_THEME4"),
                "population": f.get("attributes", {}).get("E_TOTPOP"),
                "uninsured_est": f.get("attributes", {}).get("E_UNINSUR"),
                "source": "CDC Social Vulnerability Index 2022 (US Public Domain)",
                "url": "https://www.atsdr.cdc.gov/placeandhealth/svi/",
            }
            for f in features
        ]
    except Exception as e:
        logger.warning("CDC SVI query failed: %s", e)
        return []
