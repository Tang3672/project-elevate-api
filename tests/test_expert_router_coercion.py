"""
Regression test for the expert-router KeyError bug (Error: 'drug_amr').

The granular router ids (e.g. 'drug_amr') are NOT keys in the 6-key
EXPERT_REGISTRY, so any classifier output had to be coerced to a valid
top-level domain before the registry lookup, or route() raised KeyError.

Run with: pytest tests/test_expert_router_coercion.py -v
"""

from app.services.expert_router import (
    _coerce_to_registry,
    _ROUTER_TO_EXPERT,
    EXPERT_REGISTRY,
    _DEFAULT_DOMAIN,
)


def test_default_domain_is_valid():
    assert _DEFAULT_DOMAIN in EXPERT_REGISTRY


def test_every_known_id_coerces_to_valid_registry_key():
    ids = set(_ROUTER_TO_EXPERT.keys()) | set(_ROUTER_TO_EXPERT.values())
    for i in ids:
        assert _coerce_to_registry(i) in EXPERT_REGISTRY, i


def test_specific_mappings():
    assert _coerce_to_registry("drug_amr") == "antibiotic_amr"
    assert _coerce_to_registry("biologic_oncology") == "oncology"
    assert _coerce_to_registry("gene_therapy_cns") == "neurology_cns"
    assert _coerce_to_registry("device_cardiovascular") == "cardiology"
    assert _coerce_to_registry("drug_metabolic") == "metabolic_diabetes"
    assert _coerce_to_registry("drug_mental_health") == "mental_health"


def test_unknown_and_empty_fall_back_to_default():
    assert _coerce_to_registry("totally_unknown_id") == _DEFAULT_DOMAIN
    assert _coerce_to_registry("") == _DEFAULT_DOMAIN
    assert _coerce_to_registry(None) == _DEFAULT_DOMAIN


def test_valid_keys_pass_through():
    for k in EXPERT_REGISTRY:
        assert _coerce_to_registry(k) == k
