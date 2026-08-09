"""
F-15 — Research SaaS / data-platform intake questions.

research_infrastructure_saas and research_saas must route to
_RESEARCH_SAAS_QUESTIONS, not to the instrumentation-focused
_RESEARCH_QUESTIONS.

Spec: "the questions aren't tailored anymore" — data platforms
(cloud sync, ELNs, data management) received instrument-centric
options like 'Short acute recordings' and 'Bonsai, Spike2'.

All tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import pytest

from app.services.product_classifier import (
    Classification,
    _RESEARCH_QUESTIONS,
    _RESEARCH_SAAS_QUESTIONS,
    get_conditioned_questions,
)

_FORBIDDEN_IN_SAAS = [
    "Bonsai", "Spike2",            # instrumentation-specific DAQ tools
    "Short acute recordings",      # experiment-type framing irrelevant for sync platforms
    "Long-duration unattended",    # same
    "High-throughput batch",       # same
    "Real-time analysis",          # same
]

_REQUIRED_IN_SAAS = [
    "SD card",                     # data transfer origin that Hublink specifically addresses
    "Dropbox",                     # most common status-quo consumer cloud
    "ELN",                         # commercial ELN as incumbent category
    "data",                        # the platform's subject matter
]


def _cls(archetype: str) -> Classification:
    return Classification(
        product_name="Test Product",
        one_line="A research data platform for academic labs.",
        trl=5,
        ambiguities=[],
        domain="LIFE_SCIENCES_RESEARCH",
        archetype=archetype,
        confidence=0.75,
    )


# ── 1. Routing ────────────────────────────────────────────────────────────────

class TestRoutingToSaasBank:

    def test_research_infrastructure_saas_routes_to_saas_questions(self):
        qs = get_conditioned_questions(_cls("research_infrastructure_saas"))
        ids = {q.id for q in qs}
        assert ids != {q.id for q in _RESEARCH_QUESTIONS}, (
            "research_infrastructure_saas must NOT return the instrumentation question bank"
        )
        assert ids == {q.id for q in _RESEARCH_SAAS_QUESTIONS}, (
            "research_infrastructure_saas must return _RESEARCH_SAAS_QUESTIONS"
        )

    def test_research_saas_routes_to_saas_questions(self):
        qs = get_conditioned_questions(_cls("research_saas"))
        ids = {q.id for q in qs}
        assert ids == {q.id for q in _RESEARCH_SAAS_QUESTIONS}, (
            "research_saas must return _RESEARCH_SAAS_QUESTIONS"
        )

    def test_research_tool_non_clinical_routes_to_instrument_questions(self):
        qs = get_conditioned_questions(_cls("research_tool_non_clinical"))
        ids = {q.id for q in qs}
        assert ids == {q.id for q in _RESEARCH_QUESTIONS}, (
            "research_tool_non_clinical must still return the instrumentation question bank"
        )

    def test_saas_and_instrument_banks_are_different(self):
        saas_ids  = {q.id for q in _RESEARCH_SAAS_QUESTIONS}
        inst_ids  = {q.id for q in _RESEARCH_QUESTIONS}
        assert saas_ids != inst_ids, (
            "SaaS and instrument question banks must have different question IDs"
        )


# ── 2. SaaS question bank content ────────────────────────────────────────────

class TestSaasQuestionBankContent:

    def test_saas_bank_has_six_questions(self):
        assert len(_RESEARCH_SAAS_QUESTIONS) == 6

    def test_saas_bank_has_no_forbidden_strings(self):
        full_text = "\n".join(
            q.text + "\n" + "\n".join(q.options or [])
            for q in _RESEARCH_SAAS_QUESTIONS
        )
        for token in _FORBIDDEN_IN_SAAS:
            assert token not in full_text, (
                f"SaaS question bank must not contain instrumentation token {token!r}"
            )

    def test_saas_bank_mentions_data_transfer_status_quo(self):
        status_quo_q = next(
            (q for q in _RESEARCH_SAAS_QUESTIONS if "status_quo" in q.binds_to), None
        )
        assert status_quo_q is not None, "SaaS bank must have a status_quo question"
        opts_text = " ".join(status_quo_q.options or [])
        for req in _REQUIRED_IN_SAAS:
            assert req.lower() in opts_text.lower(), (
                f"Status-quo question options must mention {req!r}; got: {opts_text!r}"
            )

    def test_saas_bank_has_data_type_question(self):
        data_q = next(
            (q for q in _RESEARCH_SAAS_QUESTIONS if "data_type" in q.binds_to), None
        )
        assert data_q is not None, "SaaS bank must have a question binding to 'data_type'"

    def test_saas_bank_all_questions_have_binds_to(self):
        for q in _RESEARCH_SAAS_QUESTIONS:
            assert q.binds_to, f"SaaS question {q.id!r} must have a non-empty binds_to"

    def test_saas_bank_all_questions_have_four_options(self):
        for q in _RESEARCH_SAAS_QUESTIONS:
            assert q.options and len(q.options) == 4, (
                f"SaaS question {q.id!r} must have exactly 4 options; got {len(q.options or [])}"
            )

    def test_saas_bank_no_product_specific_strings(self):
        forbidden = ["Hublink", "Gaidica", "WashU", "Neurotech Hub", "REDCap", "LabKey"]
        full_text = "\n".join(
            q.text + "\n" + "\n".join(q.options or []) + "\n" + (q.why_asked or "")
            for q in _RESEARCH_SAAS_QUESTIONS
        )
        for name in forbidden:
            assert name not in full_text, (
                f"SaaS question bank must not name specific product {name!r} (Rule 8)"
            )

    def test_saas_bank_has_regulatory_gate_question(self):
        reg_q = next(
            (q for q in _RESEARCH_SAAS_QUESTIONS if "reg." in q.binds_to), None
        )
        assert reg_q is not None, "SaaS bank must include a regulatory/HIPAA gate question"

    def test_saas_bank_has_grant_funding_question(self):
        grant_q = next(
            (q for q in _RESEARCH_SAAS_QUESTIONS if "budget_source" in q.binds_to), None
        )
        assert grant_q is not None, "SaaS bank must include a grant-funding mechanism question"

    def test_saas_price_question_includes_subscription_framing(self):
        price_q = next(
            (q for q in _RESEARCH_SAAS_QUESTIONS if "price" in q.binds_to), None
        )
        assert price_q is not None, "SaaS bank must have a price question"
        opts_text = " ".join(price_q.options or [])
        assert "yr" in opts_text or "year" in opts_text.lower(), (
            "SaaS price options must use annual (per-year) framing, not one-time capital"
        )

    def test_impact_ranks_are_unique(self):
        ranks = [q.impact_rank for q in _RESEARCH_SAAS_QUESTIONS]
        assert len(ranks) == len(set(ranks)), "impact_rank values must be unique in SaaS bank"
