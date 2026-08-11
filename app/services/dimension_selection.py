"""
Dimension candidacy filter + variance-based selection (Part D Revised).

Stage 1 — candidacy: filter DIMENSION_REGISTRY by candidate_when(classification, intake).
Stage 2 — selection: among candidates, select dimensions where between-group variance
           in `param` exceeds `threshold` fraction of total variance.

Outputs a DimensionReport with counts and full rejection list.
"""
from __future__ import annotations
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from app.services.dimensions import DIMENSION_REGISTRY, Dimension


@dataclass
class DimensionReport:
    dimensions_considered_count: int
    dimensions_selected:  List[dict]
    dimensions_rejected:  List[dict]
    renders_considered_count: bool = True  # always True — tested by spec


def get_candidates(classification: dict, intake: dict) -> List[Dimension]:
    return [
        dim for dim in DIMENSION_REGISTRY.values()
        if dim.candidate_when(classification, intake)
    ]


def selects(
    dim: Dimension,
    cells: List[Dict[str, Any]],
    param: str = "adoption",
    threshold: float = 0.10,
) -> tuple[bool, float]:
    """
    Returns (selected: bool, lift: float) where lift = between_group_var / total_var.
    cells: list of dicts; dim.id and param must be keys.
    """
    if not cells:
        return False, 0.0
    values = [float(c.get(param, 0.0)) for c in cells]
    if len(values) < 2:
        return False, 0.0
    total_var = statistics.pvariance(values)
    if total_var < 1e-12:
        return False, 0.0

    groups: dict[str, list[float]] = {}
    for cell in cells:
        key = str(cell.get(dim.id, "__missing__"))
        groups.setdefault(key, []).append(float(cell.get(param, 0.0)))
    if len(groups) < 2:
        return False, 0.0

    # Between-group variance: pvariance of weighted group means
    group_means_weighted: list[float] = []
    for gv in groups.values():
        gm = statistics.mean(gv)
        group_means_weighted.extend([gm] * len(gv))

    between_var = statistics.pvariance(group_means_weighted)
    lift = between_var / total_var
    return lift > threshold, round(lift, 4)


def run_selection(
    candidates: List[Dimension],
    cells: List[Dict[str, Any]],
    param: str = "adoption",
    threshold: float = 0.10,
) -> tuple[list, list]:
    selected, rejected = [], []
    for dim in candidates:
        passed, lift = selects(dim, cells, param=param, threshold=threshold)
        (selected if passed else rejected).append((dim, lift))
    rejected.sort(key=lambda x: x[1], reverse=True)
    selected.sort(key=lambda x: x[1], reverse=True)
    return selected, rejected


def build_dimension_report(
    classification: dict,
    intake: dict,
    cells: Optional[List[Dict[str, Any]]] = None,
    param: str = "adoption",
    threshold: float = 0.10,
) -> DimensionReport:
    candidates = get_candidates(classification, intake)

    if cells:
        selected_pairs, rejected_pairs = run_selection(candidates, cells, param=param, threshold=threshold)
    else:
        # Fallback: use may_differentiate declaration as a prior
        selected_pairs = [(d, 0.0) for d in candidates if param in d.may_differentiate]
        rejected_pairs = [(d, 0.0) for d in candidates if param not in d.may_differentiate]

    return DimensionReport(
        dimensions_considered_count=len(candidates),
        dimensions_selected=[
            {
                "id": d.id, "label": d.label, "family": d.family.value,
                "lift": lift, "may_differentiate": list(d.may_differentiate),
                "data_granularity": d.data_granularity,
            }
            for d, lift in selected_pairs
        ],
        dimensions_rejected=[
            {
                "id": d.id, "label": d.label, "family": d.family.value,
                "lift": lift,
                "reason": (
                    f"{lift:.1%} variance explained, below {threshold:.0%} threshold"
                    if lift > 0 else f"'{param}' not in declared may_differentiate set"
                ),
            }
            for d, lift in rejected_pairs
        ],
    )
