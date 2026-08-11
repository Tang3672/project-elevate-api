"""Dimension registry — open, extensible, auditable (Part D Revised)."""
from __future__ import annotations
import enum
from dataclasses import dataclass
from typing import Callable, FrozenSet, Literal, Optional

class DimensionFamily(str, enum.Enum):
    POPULATION_CLINICAL    = "population_clinical"
    GEOGRAPHIC             = "geographic"
    PAYER_ECONOMIC         = "payer_economic"
    CARE_DELIVERY          = "care_delivery"
    INSTITUTIONAL_RESEARCH = "institutional_research"
    FIRMOGRAPHIC           = "firmographic"
    BEHAVIORAL_ADOPTION    = "behavioral_adoption"

@dataclass
class Dimension:
    id:                str
    label:             str
    family:            DimensionFamily
    candidate_when:    Callable   # (classification_dict, intake_dict) -> bool
    may_differentiate: FrozenSet[Literal["price","adoption","timing","channel","access"]]
    data_granularity:  Literal["national","state","cbsa","facility","individual"]
    levels_source:     Optional[str] = None
    description:       str = ""

DIMENSION_REGISTRY: dict[str, Dimension] = {}

def register(dim: Dimension) -> Dimension:
    DIMENSION_REGISTRY[dim.id] = dim
    return dim

# Import family modules to populate the registry (must be at bottom to avoid circular imports)
from app.services.dimensions import (  # noqa: E402, F401
    population_clinical,
    geographic,
    payer_economic,
    care_delivery,
    institutional_research,
    firmographic,
    behavioral_adoption,
)
