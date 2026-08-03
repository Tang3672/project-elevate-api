"""
tests/test_moe_routing.py
==========================
Tests for the MoE extension of app/services/expert_router_v2.py
(Build Spec v6, Part 3).

All tests use pytest-asyncio for the async route_to_experts() function.
Heuristic tests (apply_heuristics) are synchronous.

Key assertions:
  • route_to_experts returns ≥1 ExpertActivation
  • Weights sum to ~1.0 (within floating-point tolerance)
  • reconcile() returns ExpertConsensus with has_disagreement set correctly
  • apply_heuristics fires on "stroke" and "antibiotic" keywords
  • Heuristics do not fire for unrelated product/idea combinations
"""

from __future__ import annotations

import math
import pytest
import pytest_asyncio

from app.services.expert_router_v2 import (
    ExpertActivation,
    ExpertConsensus,
    FiredHeuristic,
    HEURISTIC_LIBRARY,
    apply_heuristics,
    reconcile,
    route_to_experts,
)


# ──────────────────────────────────────────────────────────────────────────────
# 1. route_to_experts — returns ≥1 activation with valid weights
# ──────────────────────────────────────────────────────────────────────────────

class TestRouteToExperts:

    @pytest.mark.asyncio
    async def test_returns_at_least_one_activation(self):
        activations = await route_to_experts(
            idea="novel monoclonal antibody for HER2+ breast cancer",
            tier1_category="biologic",
        )
        assert len(activations) >= 1, "route_to_experts must return ≥1 ExpertActivation"

    @pytest.mark.asyncio
    async def test_weights_sum_to_one(self):
        activations = await route_to_experts(
            idea="oral antibiotic for MRSA",
            tier1_category="drug_small_molecule",
        )
        total_w = sum(a.weight for a in activations)
        assert math.isclose(total_w, 1.0, abs_tol=0.01), (
            f"ExpertActivation weights must sum to 1.0 (±0.01); got {total_w:.4f}"
        )

    @pytest.mark.asyncio
    async def test_all_activations_have_valid_multipliers(self):
        activations = await route_to_experts(
            idea="AAV gene therapy for rare CNS disease",
            tier1_category="gene_cell_therapy",
        )
        for a in activations:
            assert a.sam_multiplier > 0, f"SAM multiplier must be positive: {a.sub_expert_id}"
            assert a.som_multiplier > 0, f"SOM multiplier must be positive: {a.sub_expert_id}"

    @pytest.mark.asyncio
    async def test_all_activations_have_reasoning(self):
        activations = await route_to_experts(
            idea="diagnostic test for NSCLC biomarker selection",
            tier1_category="diagnostic",
        )
        for a in activations:
            assert a.reasoning, f"ExpertActivation {a.sub_expert_id} must have non-empty reasoning"

    @pytest.mark.asyncio
    async def test_primary_expert_has_highest_weight(self):
        """Primary expert should have the highest individual weight."""
        activations = await route_to_experts(
            idea="hospital clinical decision support AI",
            tier1_category="digital_health",
        )
        if len(activations) > 1:
            weights = [a.weight for a in activations]
            assert weights[0] == max(weights), (
                "Primary expert (index 0) should have the highest weight"
            )

    @pytest.mark.asyncio
    async def test_to_dict_on_each_activation(self):
        import json
        activations = await route_to_experts(
            idea="bispecific antibody for hematology",
            tier1_category="biologic",
        )
        for a in activations:
            d = a.to_dict()
            json.dumps(d)  # must not raise
            assert "sub_expert_id" in d
            assert "weight" in d


# ──────────────────────────────────────────────────────────────────────────────
# 2. reconcile — consensus is weighted average; disagreement detected correctly
# ──────────────────────────────────────────────────────────────────────────────

class TestReconcile:

    def _make_activation(self, sub_id: str, weight: float,
                         sam: float, som: float) -> ExpertActivation:
        from app.services.expert_profiles_v2 import SUB_EXPERT_REGISTRY
        expert = SUB_EXPERT_REGISTRY.get(sub_id)
        if expert is None:
            # Use any available expert as a stub
            expert = list(SUB_EXPERT_REGISTRY.values())[0]
        return ExpertActivation(
            sub_expert_id=sub_id,
            expert=expert,
            weight=weight,
            sam_multiplier=sam,
            som_multiplier=som,
            reasoning="test",
        )

    def test_consensus_is_weighted_average_sam(self):
        a1 = self._make_activation("drug_oncology",   0.60, sam=1.0, som=1.0)
        a2 = self._make_activation("drug_rare_disease", 0.40, sam=0.7, som=1.1)
        consensus = reconcile([a1, a2])
        expected_sam = 0.60 * 1.0 + 0.40 * 0.7
        assert math.isclose(consensus.consensus_sam_multiplier, expected_sam, rel_tol=1e-4), (
            f"Consensus SAM {consensus.consensus_sam_multiplier:.4f} ≠ expected {expected_sam:.4f}"
        )

    def test_no_disagreement_when_similar_multipliers(self):
        a1 = self._make_activation("drug_oncology",   0.60, sam=1.0, som=1.0)
        a2 = self._make_activation("drug_cardiology",  0.40, sam=0.95, som=1.02)
        consensus = reconcile([a1, a2])
        assert not consensus.has_disagreement, (
            "Small multiplier differences (< 30%) should not flag disagreement"
        )

    def test_disagreement_detected_large_som_spread(self):
        """
        When two experts differ by > 30% on SOM multiplier, disagreement must be flagged.
        digital_cds SOM = 0.40; drug_oncology SOM = 1.0 → spread > 1.3×
        """
        a1 = self._make_activation("drug_oncology",  0.50, sam=1.0, som=1.0)
        a2 = self._make_activation("digital_cds",    0.50, sam=1.0, som=0.40)
        consensus = reconcile([a1, a2])
        assert consensus.has_disagreement, (
            "SOM spread of 2.5× (1.0 vs 0.40) should flag disagreement"
        )

    def test_disagreement_note_non_empty_when_flagged(self):
        a1 = self._make_activation("gene_therapy_rare",     0.50, sam=0.50, som=1.30)
        a2 = self._make_activation("biologic_oncology",     0.50, sam=1.0,  som=1.0)
        consensus = reconcile([a1, a2])
        if consensus.has_disagreement:
            assert consensus.disagreement_note, "Disagreement note must be non-empty when flagged"

    def test_single_expert_no_disagreement(self):
        a1 = self._make_activation("drug_oncology", 1.0, sam=1.0, som=1.0)
        consensus = reconcile([a1])
        assert not consensus.has_disagreement
        assert math.isclose(consensus.consensus_sam_multiplier, 1.0)

    def test_reconcile_raises_on_empty_list(self):
        with pytest.raises((ValueError, IndexError, Exception)):
            reconcile([])

    def test_consensus_to_dict_json_serializable(self):
        import json
        a1 = self._make_activation("drug_oncology",   0.70, sam=1.0, som=1.0)
        a2 = self._make_activation("drug_cardiology",  0.30, sam=0.9, som=0.95)
        consensus = reconcile([a1, a2])
        d = consensus.to_dict()
        json.dumps(d)  # must not raise
        assert "has_disagreement" in d
        assert "consensus_sam_multiplier" in d


# ──────────────────────────────────────────────────────────────────────────────
# 3. apply_heuristics — fires on stroke and antibiotic keywords
# ──────────────────────────────────────────────────────────────────────────────

class TestApplyHeuristics:

    def test_antibiotic_fires_stewardship_rule(self):
        fired = apply_heuristics(
            idea_text="novel antibiotic for MRSA gram-negative infections",
            product_type="drug_small_molecule",
        )
        names = [h.rule_name for h in fired]
        assert "stewardship_restriction" in names, (
            "Antibiotic keyword must fire the stewardship_restriction heuristic"
        )

    def test_stroke_fires_acute_episodic_rule(self):
        fired = apply_heuristics(
            idea_text="acute ischemic stroke treatment emergency IV infusion",
            product_type="drug_small_molecule",
        )
        names = [h.rule_name for h in fired]
        assert "acute_episodic_use" in names, (
            "Stroke keyword must fire the acute_episodic_use heuristic"
        )

    def test_antibiotic_som_penalty_applied(self):
        fired = apply_heuristics(
            idea_text="carbapenem antibiotic amr last-resort antibacterial",
            product_type="drug_small_molecule",
        )
        steward = next((h for h in fired if h.rule_name == "stewardship_restriction"), None)
        assert steward is not None
        assert steward.som_adjustment < 1.0, (
            "Stewardship heuristic must apply a SOM penalty (som_adjustment < 1.0)"
        )

    def test_stroke_som_penalty_applied(self):
        fired = apply_heuristics(
            idea_text="acute stroke emergency intervention single infusion",
            product_type="biologic",
        )
        acute = next((h for h in fired if h.rule_name == "acute_episodic_use"), None)
        assert acute is not None
        assert acute.som_adjustment < 1.0, (
            "Acute episodic heuristic must apply a SOM penalty"
        )

    def test_biomarker_fires_on_companion_diagnostic_keyword(self):
        fired = apply_heuristics(
            idea_text="companion diagnostic biomarker-positive patient selection HER2+",
            product_type="diagnostic",
        )
        names = [h.rule_name for h in fired]
        assert "biomarker_defined_population" in names, (
            "CDx/biomarker keywords must fire the biomarker_defined_population heuristic"
        )

    def test_late_entrant_fires_on_second_to_market(self):
        fired = apply_heuristics(
            idea_text="second-to-market biosimilar entrenched competition",
            product_type="biologic",
        )
        names = [h.rule_name for h in fired]
        assert "order_of_entry_penalty" in names

    def test_samd_fires_on_hospital_ai(self):
        fired = apply_heuristics(
            idea_text="hospital ai clinical decision support radiology",
            product_type="digital_health",
        )
        names = [h.rule_name for h in fired]
        assert "samd_no_reimbursement_code" in names

    def test_oncology_drug_no_spurious_device_heuristic(self):
        """Oncology biologic should NOT fire device-specific heuristics."""
        fired = apply_heuristics(
            idea_text="first-in-class bispecific antibody for NSCLC first-line",
            product_type="biologic",
        )
        names = [h.rule_name for h in fired]
        assert "samd_no_reimbursement_code" not in names, (
            "Device/SaMD heuristic must not fire for a drug product"
        )

    def test_all_fired_heuristics_have_source(self):
        fired = apply_heuristics(
            idea_text="antibiotic oral pill hospital infection AMR",
            product_type="drug_small_molecule",
        )
        for h in fired:
            assert h.source, f"Heuristic {h.rule_name} must cite a source"

    def test_fired_heuristic_has_note(self):
        fired = apply_heuristics(
            idea_text="rare disease orphan narrow indication initial label",
            product_type="drug_small_molecule",
        )
        narrow = next((h for h in fired if h.rule_name == "narrow_indication_first"), None)
        assert narrow is not None
        assert len(narrow.note) > 20, "Fired heuristic note must be substantive"

    def test_empty_idea_fires_nothing(self):
        fired = apply_heuristics(idea_text="", product_type="biologic")
        assert fired == [], "Empty idea text should not fire any heuristics"

    def test_to_dict_json_serializable(self):
        import json
        fired = apply_heuristics(
            idea_text="antibiotic amr reserve-tier stewardship",
            product_type="drug_small_molecule",
        )
        for h in fired:
            d = h.to_dict()
            json.dumps(d)  # must not raise
            assert "rule_name" in d and "sam_adjustment" in d and "som_adjustment" in d


# ──────────────────────────────────────────────────────────────────────────────
# 4. HEURISTIC_LIBRARY completeness
# ──────────────────────────────────────────────────────────────────────────────

class TestHeuristicLibrary:

    def test_library_has_required_rules(self):
        names = [h.name for h in HEURISTIC_LIBRARY]
        required = [
            "stewardship_restriction",
            "acute_episodic_use",
            "narrow_indication_first",
            "order_of_entry_penalty",
            "roa_stickiness",
            "biomarker_defined_population",
            "combination_product_complexity",
            "samd_no_reimbursement_code",
        ]
        for r in required:
            assert r in names, f"HEURISTIC_LIBRARY missing required rule: {r}"

    def test_all_rules_have_nonempty_note(self):
        for rule in HEURISTIC_LIBRARY:
            assert rule.note, f"Heuristic rule '{rule.name}' must have a non-empty note"

    def test_all_rules_have_source(self):
        for rule in HEURISTIC_LIBRARY:
            assert rule.source, f"Heuristic rule '{rule.name}' must cite a source"

    def test_all_rules_have_valid_confidence(self):
        valid = {"high", "medium", "low"}
        for rule in HEURISTIC_LIBRARY:
            assert rule.confidence in valid, (
                f"Heuristic rule '{rule.name}' has invalid confidence: {rule.confidence}"
            )

    def test_no_rule_has_zero_sam_and_zero_som(self):
        for rule in HEURISTIC_LIBRARY:
            assert not (rule.sam_adjustment == 0 and rule.som_adjustment == 0), (
                f"Heuristic rule '{rule.name}' would zero out both SAM and SOM — "
                "use a small multiplier instead"
            )
