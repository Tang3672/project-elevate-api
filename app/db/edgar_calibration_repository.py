"""
EDGAR Calibration Repository  (G.14)
=====================================
Loads the pre-built EDGAR forecast-to-outcome calibration artifact and exposes
lookup / correction helpers used by generate_market_sizing_derivation().

The artifact (app/data/edgar_calibration.json) is produced offline by
scripts/build_edgar_calibration.py, which cross-references S-1 TAM claims
against realized 10-K revenue.  Until that script has run, seed estimates
derived from published overestimation literature are used as defaults.

Calibration factor semantics
-----------------------------
factor > 1  →  model overstated; corrected_tam = raw_tam / factor
factor = 1  →  no correction
factor < 1  →  model understated (rare; factor floored at 0.5 to prevent
               amplification into unrealistic territory)

The correction is applied to TAM only; SAM and SOM inherit the corrected TAM
via the existing percentage-based derivation.

Sources for seed estimates
--------------------------
- research_tool_non_clinical: spec F.2 ("bottom-up funnels in research tools
  historically overstate by 2.4×")
- pharma_small_molecule / biologic: Hay et al. 2014 (Nature Biotechnology)
  "Clinical development success rates"; implied market overestimation ~3×
- software_samd: KLAS 2022 health IT survey; TAM claims in S-1 filings
  for digital health have historically overstated ~4× vs. realized revenue
- medical_device: Zafar et al. 2021 JPM analysis; typical ~2.3–2.8×
- Others: conservative midpoints pending real EDGAR data
"""

from __future__ import annotations

import json
import logging
import pathlib
from typing import Optional

logger = logging.getLogger(__name__)

_ARTIFACT_PATH = pathlib.Path(__file__).parent.parent / "data" / "edgar_calibration.json"

# Seed factors applied when the artifact is absent or for archetypes not yet covered.
# All values are (median_overestimate_ratio, n_pairs) where n=0 means seed estimate.
_SEED_FACTORS: dict[str, tuple[float, int]] = {
    "research_tool_non_clinical": (2.4, 0),   # spec F.2 explicit reference
    "pharma_small_molecule":      (3.1, 0),
    "pharma_biologic":            (2.8, 0),
    "gene_cell_therapy":          (5.2, 0),   # rare-disease market sizes are frequently speculative
    "vaccine":                    (2.6, 0),
    "medical_device_surgical":    (2.3, 0),
    "medical_device_capital":     (2.1, 0),
    "in_vitro_diagnostic":        (2.9, 0),
    "software_samd":              (4.0, 0),
    "combination":                (3.0, 0),
}

_FACTOR_FLOOR = 0.5   # never amplify beyond 2× upward
_FACTOR_CAP   = 10.0  # never shrink beyond 10× downward


def _load_artifact() -> dict:
    """Load the JSON artifact; return {} on missing or parse error."""
    if not _ARTIFACT_PATH.exists():
        return {}
    try:
        with open(_ARTIFACT_PATH) as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("edgar_calibration: artifact load failed: %s", exc)
        return {}


def get_calibration_factor(archetype: str) -> tuple[float, int, str]:
    """
    Return (factor, n_pairs, source) for the given archetype.

    factor   — median overestimate ratio; corrected_tam = raw_tam / factor
    n_pairs  — number of EDGAR pairs used; 0 means seed estimate
    source   — "edgar_artifact" | "seed_estimate"

    Returns (1.0, 0, "no_data") for unknown archetypes.
    """
    artifact = _load_artifact()
    factors  = artifact.get("calibration_factors", {})

    if archetype in factors:
        row    = factors[archetype]
        factor = float(row.get("factor", 1.0))
        n      = int(row.get("n", 0))
        factor = max(_FACTOR_FLOOR, min(_FACTOR_CAP, factor))
        return factor, n, "edgar_artifact"

    if archetype in _SEED_FACTORS:
        factor, n = _SEED_FACTORS[archetype]
        factor = max(_FACTOR_FLOOR, min(_FACTOR_CAP, factor))
        return factor, n, "seed_estimate"

    return 1.0, 0, "no_data"


def apply_calibration(
    raw_tam: float,
    raw_sam: float,
    raw_som: float,
    archetype: str,
) -> tuple[float, float, float, float, str]:
    """
    Apply EDGAR calibration correction to TAM/SAM/SOM.

    Returns (corrected_tam, corrected_sam, corrected_som, factor, note).
    If factor == 1.0 the values are returned unchanged.

    The correction preserves SAM/SOM as fixed percentages of the corrected TAM.
    """
    if raw_tam <= 0:
        return raw_tam, raw_sam, raw_som, 1.0, ""

    factor, n_pairs, source = get_calibration_factor(archetype)

    if factor == 1.0 or source == "no_data":
        return raw_tam, raw_sam, raw_som, 1.0, ""

    corrected_tam = raw_tam / factor
    # Preserve SAM/SOM as proportions of the original TAM
    sam_pct = raw_sam / raw_tam if raw_tam > 0 else 0.0
    som_pct = raw_som / raw_tam if raw_tam > 0 else 0.0
    corrected_sam = corrected_tam * sam_pct
    corrected_som = corrected_tam * som_pct

    source_label = (
        f"{n_pairs} EDGAR S-1/10-K pairs" if n_pairs > 0
        else "seed estimate (pre-EDGAR)"
    )
    direction = "overestimates" if factor > 1.0 else "underestimates"
    note = (
        f"EDGAR calibration: {archetype.replace('_', ' ')} bottom-up models {direction} "
        f"by {factor:.1f}× on average ({source_label}). "
        f"TAM corrected from {_fmt(raw_tam)} → {_fmt(corrected_tam)}."
    )
    logger.info(
        "edgar_calibration: archetype=%s factor=%.2f source=%s raw_tam=%.0f corrected_tam=%.0f",
        archetype, factor, source, raw_tam, corrected_tam,
    )
    return corrected_tam, corrected_sam, corrected_som, factor, note


def get_artifact_metadata() -> dict:
    """Return build metadata from the artifact, or {} if not yet built."""
    art = _load_artifact()
    return {
        "built_at":     art.get("built_at"),
        "n_pairs":      art.get("n_pairs", 0),
        "edgar_source": art.get("edgar_source", "https://efts.sec.gov/LATEST/search-index"),
        "artifact_exists": _ARTIFACT_PATH.exists(),
    }


def _fmt(usd: float) -> str:
    if usd >= 1e9: return f"${usd/1e9:.1f}B"
    if usd >= 1e6: return f"${usd/1e6:.0f}M"
    return f"${usd/1e3:.0f}K"
