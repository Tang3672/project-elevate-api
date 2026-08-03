"""
Tests for the Segmented TAM Engine  (Part G of Build Spec v2)

Pure unit tests — no DB, no API key, no network.
The compute_market_size and segment_resolver scoring functions are pure logic.
DB-dependent tests are marked with a skip unless DATABASE_URL is set.

Run: pytest tests/test_segment_engine.py -v
"""

import pytest
from types import SimpleNamespace


# ── Fixtures ──────────────────────────────────────────────────────────────────

STROKE_LVO_SEGMENT = {
    "id": 1,
    "disease_name": "Stroke (acute ischemic, neuroprotection)",
    "segment_name": "LVO thrombectomy-eligible acute ischemic stroke",
    "pathway_tag": "mechanical_thrombectomy",
    "product_fit_keywords": [
        "thrombectomy", "LVO", "large vessel occlusion", "clot retrieval",
        "stentriever", "aspiration catheter", "neurointervention",
    ],
    "funnel": [
        {"gate": "total_incidence", "label": "US ischemic stroke incidence/yr",
         "value": 690000, "type": "absolute",
         "source": "CDC/AHA Heart & Stroke Statistics 2024"},
        {"gate": "lvo_fraction", "label": "large-vessel occlusion share",
         "rate": 0.33, "type": "rate",
         "source": "Malhotra et al. 2017 (lit)"},
        {"gate": "eligibility", "label": "thrombectomy-eligible",
         "rate": 0.48, "type": "rate",
         "source": "DAWN/DEFUSE-3 extrapolation — REVIEW"},
        {"gate": "access", "label": "reachable at comprehensive stroke centers",
         "rate": 0.70, "type": "rate",
         "source": "analyst estimate — CSC coverage — REVIEW"},
    ],
    "som_penetration_pct": 0.35,
    "som_penetration_src": "analyst estimate",
    "care_setting": "comprehensive_stroke_center",
    "site_count": 300,
    "site_count_src": "Joint Commission",
    "data_quality": "seed",
    "source_type": "literature",
}

NEUROPROTECTION_SEGMENT = {
    "id": 2,
    "disease_name": "Stroke (acute ischemic, neuroprotection)",
    "segment_name": "tPA-eligible ischemic stroke (neuroprotection window)",
    "pathway_tag": "iv_thrombolytic_plus_neuroprotection",
    "product_fit_keywords": [
        "neuroprotection", "tPA", "alteplase", "thrombolytic",
        "acute ischemic", "penumbra", "NIHSS",
    ],
    "funnel": [
        {"gate": "total_incidence", "label": "US ischemic stroke incidence/yr",
         "value": 690000, "type": "absolute",
         "source": "CDC/AHA 2024"},
        {"gate": "acute_presentation", "label": "within 4.5h window",
         "rate": 0.35, "type": "rate", "source": "NINDS — REVIEW"},
        {"gate": "tpa_eligible", "label": "IV tPA eligible",
         "rate": 0.60, "type": "rate", "source": "AHA/ASA 2023 — REVIEW"},
        {"gate": "access", "label": "stroke-ready hospital",
         "rate": 0.80, "type": "rate", "source": "analyst estimate — REVIEW"},
    ],
    "som_penetration_pct": 0.25,
    "care_setting": "stroke_ready_hospital",
    "site_count": 2000,
    "data_quality": "seed",
    "source_type": "literature",
}

NET_PRICE = 50000  # $50K/yr example


# ── compute_market_size: funnel math ─────────────────────────────────────────

class TestComputeMarketSize:
    def test_funnel_math_correct(self):
        from app.services.market_sizing import compute_market_size
        result = compute_market_size(STROKE_LVO_SEGMENT, net_price_usd=NET_PRICE)

        # Walk expected values manually:
        # 690,000 × 0.33 = 227,700 → × 0.48 = 109,296 → TAM pop (before access)
        # → × 0.70 = 76,507 → SAM pop
        # SOM = 76,507 × 0.35 = 26,777
        assert result.tam_population == 109296
        assert result.sam_population == 76507
        assert result.som_population == int(76507 * 0.35)

    def test_tam_ne_sam_ne_som(self):
        from app.services.market_sizing import compute_market_size
        result = compute_market_size(STROKE_LVO_SEGMENT, net_price_usd=NET_PRICE)
        assert result.tam_usd != result.sam_usd, "TAM must differ from SAM (access gate narrows)"
        assert result.sam_usd != result.som_usd, "SAM must differ from SOM (penetration narrows)"
        assert result.tam_usd > result.sam_usd > result.som_usd

    def test_every_step_has_source(self):
        from app.services.market_sizing import compute_market_size
        result = compute_market_size(STROKE_LVO_SEGMENT, net_price_usd=NET_PRICE)
        for step in result.funnel_steps:
            assert step.source, f"Step '{step.gate}' is missing a source"
            assert step.source != "unknown source" or step.gate == "total_incidence"

    def test_override_changes_result(self):
        from app.services.market_sizing import compute_market_size
        baseline = compute_market_size(STROKE_LVO_SEGMENT, net_price_usd=NET_PRICE)
        overridden = compute_market_size(
            STROKE_LVO_SEGMENT,
            net_price_usd=NET_PRICE,
            overrides={"lvo_fraction": {"rate": 0.50}},  # increase from 0.33 to 0.50
        )
        assert overridden.tam_population > baseline.tam_population
        assert overridden.sam_population > baseline.sam_population

    def test_combine_two_segments_sums_correctly(self):
        from app.services.market_sizing import compute_market_size
        single = compute_market_size(STROKE_LVO_SEGMENT, net_price_usd=NET_PRICE)
        extra = compute_market_size(NEUROPROTECTION_SEGMENT, net_price_usd=NET_PRICE)
        combined = compute_market_size(
            STROKE_LVO_SEGMENT,
            net_price_usd=NET_PRICE,
            extra_segments=[NEUROPROTECTION_SEGMENT],
        )
        assert combined.sam_population == single.sam_population + extra.sam_population
        assert len(combined.segments_used) == 2

    def test_confidence_band_wider_with_analyst_estimates(self):
        from app.services.market_sizing import compute_market_size
        # All analyst estimates → wide band
        all_analyst = {**STROKE_LVO_SEGMENT, "funnel": [
            {"gate": "total_incidence", "label": "test", "value": 100000,
             "type": "absolute", "source": "analyst estimate — REVIEW"},
            {"gate": "rate1", "label": "r1", "rate": 0.5, "type": "rate",
             "source": "analyst estimate — REVIEW"},
        ]}
        result = compute_market_size(all_analyst, net_price_usd=NET_PRICE)
        # All analyst → max band
        assert result.confidence_high_usd > result.confidence_low_usd
        assert result.confidence_high_usd > result.som_usd
        assert result.confidence_low_usd < result.som_usd

    def test_weakest_assumptions_populated(self):
        from app.services.market_sizing import compute_market_size
        result = compute_market_size(STROKE_LVO_SEGMENT, net_price_usd=NET_PRICE)
        # eligibility and access gates are marked REVIEW → should appear
        assert len(result.weakest_assumptions) >= 2

    def test_expert_report_overrides_gate_rate(self):
        from app.services.market_sizing import compute_market_size
        expert_report = {
            "verified": True,
            "structured_claims": [
                {"gate": "lvo_fraction", "value": 0.40, "type": "rate",
                 "claim": "LVO is closer to 40% per our stroke KOL"},
            ],
        }
        baseline = compute_market_size(STROKE_LVO_SEGMENT, net_price_usd=NET_PRICE)
        with_expert = compute_market_size(
            STROKE_LVO_SEGMENT, net_price_usd=NET_PRICE, expert_report=expert_report
        )
        assert with_expert.tam_population > baseline.tam_population
        assert with_expert.has_expert_report is True


# ── segment_resolver: keyword scoring ────────────────────────────────────────

class TestSegmentScorerUnit:
    """Tests the pure keyword-scoring logic without DB."""

    def _score(self, seg, idea_text):
        from app.services.segment_resolver import _score_segment, _normalize
        return _score_segment(seg, _normalize(idea_text))

    def test_thrombectomy_product_scores_lvo_segment(self):
        score, matched = self._score(
            STROKE_LVO_SEGMENT,
            "We developed a stentriever device for LVO thrombectomy in ischemic stroke",
        )
        assert score >= 0.30, f"Expected ≥0.30, got {score}"
        assert len(matched) >= 2

    def test_thrombectomy_product_scores_higher_than_neuroprotection(self):
        idea = "stentriever LVO thrombectomy clot retrieval device"
        score_lvo, _ = self._score(STROKE_LVO_SEGMENT, idea)
        score_neuro, _ = self._score(NEUROPROTECTION_SEGMENT, idea)
        assert score_lvo > score_neuro, (
            f"Thrombectomy product should rank LVO segment higher: "
            f"LVO={score_lvo:.2f} vs neuro={score_neuro:.2f}"
        )

    def test_neuroprotection_product_scores_neuro_segment(self):
        score, matched = self._score(
            NEUROPROTECTION_SEGMENT,
            "novel neuroprotection agent targeting penumbra tissue after tPA administration",
        )
        assert score >= 0.20, f"Expected ≥0.20, got {score}"

    def test_vague_product_scores_low(self):
        score_lvo, _ = self._score(STROKE_LVO_SEGMENT, "generic stroke app for patient tracking")
        score_neuro, _ = self._score(NEUROPROTECTION_SEGMENT, "generic stroke app for patient tracking")
        # Neither should score high for a vague description
        assert max(score_lvo, score_neuro) < 0.30

    def test_normalize_handles_punctuation(self):
        from app.services.segment_resolver import _normalize
        assert "lvo" in _normalize("LVO")
        assert "stentriever" in _normalize("Stentriever®")


# ── resolve_segment: integration (DB-free, using monkeypatch) ────────────────

class TestResolveSegment:
    @pytest.fixture
    def mock_db_two_segments(self, monkeypatch):
        async def _fake_get(disease_name):
            return [STROKE_LVO_SEGMENT, NEUROPROTECTION_SEGMENT]
        # Patch on the DB module — segment_resolver imports it with `from ... import`
        # inside the function, so we must patch the source, not the importer.
        monkeypatch.setattr(
            "app.db.market_segment_repository.get_segments_for_disease",
            _fake_get,
        )

    @pytest.fixture
    def mock_db_empty(self, monkeypatch):
        async def _fake_get(disease_name):
            return []
        monkeypatch.setattr(
            "app.db.market_segment_repository.get_segments_for_disease",
            _fake_get,
        )

    @pytest.mark.asyncio
    async def test_thrombectomy_product_resolves_to_lvo_segment(self, mock_db_two_segments):
        from app.services.segment_resolver import resolve_segment
        result = await resolve_segment(
            idea_text="We built a stentriever device for LVO thrombectomy in acute ischemic stroke",
            disease_name="Stroke (acute ischemic, neuroprotection)",
        )
        assert result["segment"] is not None
        assert "thrombectomy" in result["segment"]["segment_name"].lower()
        assert result["needs_clarification"] is False

    @pytest.mark.asyncio
    async def test_vague_stroke_app_triggers_clarification(self, mock_db_two_segments):
        from app.services.segment_resolver import resolve_segment
        result = await resolve_segment(
            idea_text="a mobile app for stroke patient rehabilitation monitoring",
            disease_name="Stroke (acute ischemic, neuroprotection)",
        )
        assert result["needs_clarification"] is True

    @pytest.mark.asyncio
    async def test_no_segments_returns_no_clarification_needed(self, mock_db_empty):
        """No seeded segments → fall back gracefully, don't crash."""
        from app.services.segment_resolver import resolve_segment
        result = await resolve_segment(
            idea_text="some drug for some disease",
            disease_name="Rare Orphan Disease XYZ",
        )
        assert result["segment"] is None
        assert result["needs_clarification"] is False  # no data → existing engine


# ── Seed data smoke test ──────────────────────────────────────────────────────

class TestSeedData:
    def test_seed_segments_list_not_empty(self):
        from app.data.seed_segments import SEED_SEGMENTS
        assert len(SEED_SEGMENTS) >= 10

    def test_all_seeds_have_required_fields(self):
        from app.data.seed_segments import SEED_SEGMENTS
        required = {"disease_name", "segment_name", "pathway_tag",
                    "product_fit_keywords", "funnel"}
        for seg in SEED_SEGMENTS:
            missing = required - set(seg.keys())
            assert not missing, f"Segment '{seg.get('segment_name')}' missing: {missing}"

    def test_all_funnel_gates_have_sources(self):
        from app.data.seed_segments import SEED_SEGMENTS
        for seg in SEED_SEGMENTS:
            for gate in seg.get("funnel", []):
                assert gate.get("source"), (
                    f"Gate '{gate.get('gate')}' in segment '{seg['segment_name']}' "
                    f"has no source"
                )

    def test_stroke_has_two_segments(self):
        from app.data.seed_segments import SEED_SEGMENTS
        stroke_segs = [s for s in SEED_SEGMENTS
                       if "stroke" in s["disease_name"].lower()]
        assert len(stroke_segs) >= 2, "Stroke needs at least 2 segments (thrombectomy + neuro)"

    def test_first_gate_is_always_absolute(self):
        """Every funnel must start with an absolute value, not a rate."""
        from app.data.seed_segments import SEED_SEGMENTS
        for seg in SEED_SEGMENTS:
            funnel = seg.get("funnel", [])
            assert funnel, f"Segment '{seg['segment_name']}' has empty funnel"
            assert funnel[0].get("type") == "absolute", (
                f"First gate of '{seg['segment_name']}' must be type='absolute'"
            )


# ── format_segment_for_prompt smoke test ─────────────────────────────────────

class TestFormatSegment:
    def test_block_contains_tam_sam_som(self):
        from app.services.market_sizing import compute_market_size, format_segment_for_prompt
        result = compute_market_size(STROKE_LVO_SEGMENT, net_price_usd=NET_PRICE)
        block = format_segment_for_prompt(STROKE_LVO_SEGMENT, result)
        assert "TAM" in block
        assert "SAM" in block
        assert "SOM" in block
        assert "SEGMENTED MARKET SIZING" in block

    def test_block_contains_segment_name(self):
        from app.services.market_sizing import compute_market_size, format_segment_for_prompt
        result = compute_market_size(STROKE_LVO_SEGMENT, net_price_usd=NET_PRICE)
        block = format_segment_for_prompt(STROKE_LVO_SEGMENT, result)
        assert "LVO thrombectomy" in block

    def test_block_contains_each_gate_source(self):
        from app.services.market_sizing import compute_market_size, format_segment_for_prompt
        result = compute_market_size(STROKE_LVO_SEGMENT, net_price_usd=NET_PRICE)
        block = format_segment_for_prompt(STROKE_LVO_SEGMENT, result)
        assert "CDC/AHA" in block
        assert "Malhotra" in block
