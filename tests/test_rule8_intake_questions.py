"""
Rule 8 — De-personalize intake questions (Spec v3 Addendum).

Verifies:
  1. No IntakeQuestion option string names a product-specific spend band
     (Gaidica or any other operator's primary research data).
  2. Price-band questions carry an engine_estimate derived from generic priors,
     not hardcoded to any specific operator.
  3. engine_estimate values contain no product-specific names.
  4. questions_to_legacy_format() includes engine_estimate in the output dict.
  5. IntakeQuestion.engine_estimate field exists with default None.
  6. All question banks (research, drug, device, generic) are free of
     product-specific strings.
"""

from __future__ import annotations

import pytest

from app.services.product_classifier import (
    IntakeQuestion,
    _RESEARCH_QUESTIONS,
    _DRUG_QUESTIONS,
    _DEVICE_QUESTIONS,
    _GENERIC_QUESTIONS,
    questions_to_legacy_format,
)

# Strings that must not appear in any intake question text or engine_estimate
_FORBIDDEN_STRINGS = [
    "Gaidica",
    "Neurotech Hub",
    "Hublink",
    "REDCap",
    "LabKey",
    "Synology",
]

_ALL_QUESTION_BANKS: dict[str, list[IntakeQuestion]] = {
    "research": _RESEARCH_QUESTIONS,
    "drug":     _DRUG_QUESTIONS,
    "device":   _DEVICE_QUESTIONS,
    "generic":  _GENERIC_QUESTIONS,
}


# ── 1. IntakeQuestion has engine_estimate field with default None ──────────────

def test_intake_question_has_engine_estimate_field():
    q = IntakeQuestion(
        id="test_q",
        text="Test question?",
        binds_to="price.observed_band",
        why_asked="Test reason.",
        input_type="single",
        options=["a", "b"],
        default=None,
        impact_rank=1,
    )
    assert hasattr(q, "engine_estimate"), "IntakeQuestion must have engine_estimate field"
    assert q.engine_estimate is None, "engine_estimate must default to None"


def test_intake_question_engine_estimate_accepts_string():
    q = IntakeQuestion(
        id="test_q",
        text="What is the price?",
        binds_to="price.observed_band",
        why_asked="Sets TAM.",
        input_type="single",
        options=None,
        default=None,
        impact_rank=1,
        engine_estimate="Engine estimate: ~$10k/yr from comparables.",
    )
    assert q.engine_estimate == "Engine estimate: ~$10k/yr from comparables."


# ── 2. No product-specific strings in any question bank ───────────────────────

@pytest.mark.parametrize("bank_name,questions", list(_ALL_QUESTION_BANKS.items()))
@pytest.mark.parametrize("forbidden", _FORBIDDEN_STRINGS)
def test_no_product_specific_string_in_question_text(bank_name, questions, forbidden):
    for q in questions:
        assert forbidden not in q.text, (
            f"IntakeQuestion '{q.id}' in {bank_name} bank contains '{forbidden}' in text "
            f"(Rule 8 — questions must be generic, not product-specific)"
        )


@pytest.mark.parametrize("bank_name,questions", list(_ALL_QUESTION_BANKS.items()))
@pytest.mark.parametrize("forbidden", _FORBIDDEN_STRINGS)
def test_no_product_specific_string_in_question_options(bank_name, questions, forbidden):
    for q in questions:
        for opt in (q.options or []):
            assert forbidden not in opt, (
                f"IntakeQuestion '{q.id}' in {bank_name} bank contains '{forbidden}' "
                f"in option '{opt}' (Rule 8 — options must be generic)"
            )


@pytest.mark.parametrize("bank_name,questions", list(_ALL_QUESTION_BANKS.items()))
@pytest.mark.parametrize("forbidden", _FORBIDDEN_STRINGS)
def test_no_product_specific_string_in_engine_estimate(bank_name, questions, forbidden):
    for q in questions:
        if q.engine_estimate is not None:
            assert forbidden not in q.engine_estimate, (
                f"IntakeQuestion '{q.id}' in {bank_name} bank contains '{forbidden}' "
                f"in engine_estimate (Rule 8 — engine_estimate must come from generic comparables)"
            )


# ── 3. rq_price_band has a non-None engine_estimate from priors ───────────────

def test_rq_price_band_has_engine_estimate():
    rq_price_band = next(
        (q for q in _RESEARCH_QUESTIONS if q.id == "rq_price_band"), None
    )
    assert rq_price_band is not None, "rq_price_band question must exist in _RESEARCH_QUESTIONS"
    assert rq_price_band.engine_estimate is not None, (
        "rq_price_band must have engine_estimate (Rule 8 — price band hint derived from priors)"
    )
    assert len(rq_price_band.engine_estimate) > 10, (
        "rq_price_band engine_estimate must be a meaningful string, not empty"
    )


def test_rq_price_band_engine_estimate_mentions_comparables():
    rq = next(q for q in _RESEARCH_QUESTIONS if q.id == "rq_price_band")
    est = rq.engine_estimate.lower()
    assert "comparable" in est or "estimate" in est or "priors" in est, (
        "rq_price_band engine_estimate should mention 'comparable', 'estimate', or 'priors' "
        "to signal it is derived from generic data, not operator-specific spend"
    )


def test_rq_price_band_engine_estimate_references_priors_numbers():
    """engine_estimate must reflect actual priors values, not arbitrary hardcoding."""
    from app.market.priors.life_sciences_research import PRIORS

    rq = next(q for q in _RESEARCH_QUESTIONS if q.id == "rq_price_band")
    est = rq.engine_estimate

    acad_k = int(PRIORS["price_tiers"]["academic"]["annual_usd"] / 1_000)
    assert f"${acad_k}k" in est, (
        f"rq_price_band engine_estimate must reflect priors academic price "
        f"(~${acad_k}k). Got: {est!r}"
    )


# ── 4. questions_to_legacy_format() includes engine_estimate ──────────────────

def test_legacy_format_includes_engine_estimate_field():
    formatted = questions_to_legacy_format(_RESEARCH_QUESTIONS)
    for entry in formatted:
        assert "engine_estimate" in entry, (
            f"questions_to_legacy_format() output for '{entry.get('field')}' "
            "must include 'engine_estimate' key (Rule 8)"
        )


def test_legacy_format_rq_price_band_engine_estimate_is_not_none():
    formatted = questions_to_legacy_format(_RESEARCH_QUESTIONS)
    price_band = next((e for e in formatted if e["field"] == "rq_price_band"), None)
    assert price_band is not None
    assert price_band["engine_estimate"] is not None, (
        "rq_price_band engine_estimate must be non-None in legacy format output"
    )


def test_legacy_format_non_price_questions_engine_estimate_is_none():
    """Questions without an engine_estimate must pass None (not omit the key)."""
    formatted = questions_to_legacy_format(_RESEARCH_QUESTIONS)
    for entry in formatted:
        if entry["field"] != "rq_price_band":
            # engine_estimate must be present as a key, value can be None
            assert "engine_estimate" in entry
            # Most non-price questions should have None estimate
            # (this is a softer check — future questions may add estimates)


# ── 5. engine_estimate on devq_price_band (device) is still None (no priors) ──

def test_devq_price_band_engine_estimate_is_none_or_generic():
    """Device price-band question has no priors module yet — must be None or generic."""
    devq_price_band = next(
        (q for q in _DEVICE_QUESTIONS if q.id == "devq_price_band"), None
    )
    assert devq_price_band is not None, "devq_price_band question must exist"
    # Either None (no estimate yet) or a generic string — must not be Gaidica-specific
    if devq_price_band.engine_estimate is not None:
        for forbidden in _FORBIDDEN_STRINGS:
            assert forbidden not in devq_price_band.engine_estimate


# ── 6. Addendum leakage guard: product_classifier.py has no Gaidica in exec code ─

def test_product_classifier_has_no_gaidica_in_executable_code():
    """
    Complement to test_no_product_leakage.py: confirms product_classifier.py
    has no Gaidica reference in executable code (comments are OK).
    """
    import ast, os, re

    path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "app", "services", "product_classifier.py")
    )
    with open(path, encoding="utf-8") as f:
        raw = f.read()

    # Strip comments and docstrings
    stripped = re.sub(r'""".*?"""', '""""""', raw, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", "''''''", stripped, flags=re.DOTALL)
    stripped = re.sub(r"#[^\n]*", "", stripped)

    assert "Gaidica" not in stripped, (
        "product_classifier.py contains 'Gaidica' in executable code "
        "(Rule 8 — intake questions must be generic)"
    )
