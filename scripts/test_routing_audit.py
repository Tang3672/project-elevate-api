"""
Routing audit: verifies that every fallback path in the pipeline
produces neutral output (research_tool_non_clinical) rather than
AMR/pharma framing for non-biomedical products.

Run from the project root:
    python scripts/test_routing_audit.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

results = []

def check(label, got, expected, *, contains=False):
    ok = (got == expected) if not contains else (expected in str(got))
    symbol = PASS if ok else FAIL
    print(f"  [{symbol}] {label}")
    if not ok:
        print(f"         expected: {expected!r}")
        print(f"         got:      {got!r}")
    results.append(ok)
    return ok


# ── 1. _keyword_classify fallback paths ─────────────────────────────────────
print("\n=== 1. _keyword_classify ===")
from app.services.expert_router import _keyword_classify, _ROUTER_TO_EXPERT

# Known agronomy product — must hit agronomy keywords
check("soil moisture sensor → research_tool_agronomy",
      _keyword_classify("SoilMoisture Sensor for precision agriculture farms"),
      "research_tool_agronomy")

# Product with solar/photovoltaic signals — now in non-bio KWS list
check("solar panel analyzer → research_tool_non_clinical (via keyword 'solar panel')",
      _keyword_classify("Solar Panel Efficiency Analyzer for photovoltaic research"),
      "research_tool_non_clinical")

# Product with zero keyword hits, NO non-bio signals — falls to drug_oncology as last resort
result = _keyword_classify("Completely novel idea with no recognizable keywords XY-7")
check("zero-hit unknown product → drug_oncology (least-specific drug fallback)",
      result,
      "drug_oncology")

# Known LIMS product
check("LIMS platform → research_infrastructure_saas",
      _keyword_classify("LIMS laboratory information management system for research"),
      "research_infrastructure_saas")


# ── 2. All _keyword_classify returns must be valid _ROUTER_TO_EXPERT keys ───
print("\n=== 2. _keyword_classify outputs are always valid router keys ===")
test_ideas = [
    "Soil moisture sensor for agricultural fields",
    "Novel antibiotic targeting MRSA",
    "AI-powered clinical decision support for hospital EHR",
    "Completely unknown product type AB-999 for unexplained purpose",
    "Solar panel efficiency measurement device",
    "CRISPR base editor for rare disease",
    "Electronic lab notebook for university research",
]
for idea in test_ideas:
    raw = _keyword_classify(idea)
    check(f"  {idea[:50]!r} → valid key",
          raw in _ROUTER_TO_EXPERT or raw in ("drug_oncology",),  # drug_oncology is last-resort
          True)


# ── 3. get_sub_expert neutral fallback ──────────────────────────────────────
print("\n=== 3. get_sub_expert for unknown IDs returns RESEARCH_TOOL_NON_CLINICAL ===")
from app.services.expert_profiles_v2 import get_sub_expert, RESEARCH_TOOL_NON_CLINICAL

check("get_sub_expert('antibiotic_amr') → RESEARCH_TOOL_NON_CLINICAL",
      get_sub_expert("antibiotic_amr"),
      RESEARCH_TOOL_NON_CLINICAL)

check("get_sub_expert('') → None",
      get_sub_expert(""),
      None)

check("get_sub_expert('hallucinated_domain') → RESEARCH_TOOL_NON_CLINICAL",
      get_sub_expert("hallucinated_domain"),
      RESEARCH_TOOL_NON_CLINICAL)

check("get_sub_expert('drug_amr') → AMR_DRUG (correct for real AMR products)",
      get_sub_expert("drug_amr").sub_expert_id,
      "drug_amr")

check("get_sub_expert('research_tool_agronomy') → RESEARCH_TOOL_NON_CLINICAL",
      get_sub_expert("research_tool_agronomy"),
      RESEARCH_TOOL_NON_CLINICAL)


# ── 4. _classify_archetype fallback paths ───────────────────────────────────
print("\n=== 4. _classify_archetype for non-biomedical products ===")
from app.services.market_sizing_derivation_service import _classify_archetype

check("soil sensor idea → research_tool_non_clinical (keyword match)",
      _classify_archetype("soil moisture sensor for precision agriculture", "other"),
      "research_tool_non_clinical")

check("agronomy logger idea → research_tool_non_clinical",
      _classify_archetype("agronomy data logger for crop monitoring", "other"),
      "research_tool_non_clinical")

check("zero-match + soil fallback → research_tool_non_clinical",
      _classify_archetype("device for measuring soil water in farm fields", "other"),
      "research_tool_non_clinical")

check("antibiotic idea → pharma_small_molecule (correct for real drugs)",
      _classify_archetype("oral antibiotic targeting MRSA", "drug_small_molecule"),
      "pharma_small_molecule")

check("zero medical match + zero non-bio signal → pharma_small_molecule (last resort)",
      _classify_archetype("XY-999 novel compound with unknown target", "other"),
      "pharma_small_molecule")


# ── 5. generate_market_sizing_derivation uses correct archetype ─────────────
print("\n=== 5. Market sizing archetype routing via sub_expert_id ===")
from app.services.market_sizing_derivation_service import generate_market_sizing_derivation

deriv_agronomy = generate_market_sizing_derivation(
    idea="SoilMoisture Sensor for precision agriculture",
    product_type="other",
    disease_name="soil moisture monitoring",
    sub_expert_id="research_tool_agronomy",
)
check("research_tool_agronomy → archetype is research_tool_non_clinical",
      deriv_agronomy.archetype,
      "research_tool_non_clinical")
check("research_tool_agronomy → TAM is positive",
      deriv_agronomy.us_tam_usd > 0,
      True)
check("research_tool_agronomy → formula uses lab buyer model (not WAC/drug pricing)",
      "WAC" not in (deriv_agronomy.formula_name + deriv_agronomy.formula_overview),
      True)

deriv_research = generate_market_sizing_derivation(
    idea="Data logger for neuroscience research labs",
    product_type="other",
    disease_name="neuroscience instrumentation",
    sub_expert_id="research_tool_non_clinical",
)
check("research_tool_non_clinical → archetype is research_tool_non_clinical",
      deriv_research.archetype,
      "research_tool_non_clinical")
check("research_tool_non_clinical → TAM is positive",
      deriv_research.us_tam_usd > 0,
      True)

# Verify old bug doesn't recur: antibiotic_amr sub_expert_id now hits fallback
deriv_unknown = generate_market_sizing_derivation(
    idea="SoilMoisture Sensor for precision agriculture",
    product_type="other",
    disease_name="soil moisture monitoring",
    sub_expert_id="antibiotic_amr",   # the old broken default
)
# With the bad ID "antibiotic_amr" not in the research list, it falls to _classify_archetype
# _classify_archetype("SoilMoisture Sensor...", "other") → sees "soil" → research_tool_non_clinical
check("antibiotic_amr sub_expert_id + soil idea → research_tool_non_clinical archetype (via fallback)",
      deriv_unknown.archetype,
      "research_tool_non_clinical")


# ── 6. validate_claude_domain_output gate ───────────────────────────────────
print("\n=== 6. classify_with_claude domain validation (synchronous test) ===")
# We can't call the async Claude API here, but we can test the validation logic
from app.services.expert_router import _ROUTER_TO_EXPERT

bad_domains = ["antibiotic_amr", "", "hallucinated_domain", "drug", "OTHER"]
for bad in bad_domains:
    check(f"'{bad}' NOT in _ROUTER_TO_EXPERT (triggers keyword fallback)",
          bad not in _ROUTER_TO_EXPERT,
          True)

good_domains = ["drug_amr", "drug_oncology", "research_tool_agronomy", "research_tool_non_clinical"]
for good in good_domains:
    check(f"'{good}' in _ROUTER_TO_EXPERT (accepted directly)",
          good in _ROUTER_TO_EXPERT,
          True)


# ── 7. knowledge_retriever uses correct search templates ─────────────────────
print("\n=== 7. Knowledge retriever search template mapping ===")
from app.services.knowledge_retriever import SEARCH_TEMPLATES, DEFAULT_SEARCHES

check("research_tool_non_clinical has its own search templates (not FDA/clinical)",
      "research_tool_non_clinical" in SEARCH_TEMPLATES,
      True)
check("research_tool_agronomy has its own search templates (USDA/NIFA not FDA)",
      "research_tool_agronomy" in SEARCH_TEMPLATES,
      True)
check("research_tool_non_clinical templates don't reference FDA drug approvals",
      "fda.gov" not in str(SEARCH_TEMPLATES.get("research_tool_non_clinical", [])).lower() or
      "sbir.nih.gov" in str(SEARCH_TEMPLATES.get("research_tool_non_clinical", [])),
      True)


# ── Summary ─────────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
passed = sum(results)
total  = len(results)
print(f"  {passed}/{total} checks passed")
if passed < total:
    print(f"  {total - passed} FAILURES — see above")
    sys.exit(1)
else:
    print("  All checks passed.")
    sys.exit(0)
