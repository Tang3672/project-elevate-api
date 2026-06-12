# Medlevate (Project Elevate) - Technical & Impact Overview

*Prepared as a reference document for grant applications, accelerator applications, and AI-assisted Q&A. Last updated 2026-06-11.*

---

## 1. What Medlevate Is

Medlevate is a market intelligence platform that turns a researcher's raw idea ("we have a novel small molecule that targets X for Y disease") into a fully-cited, investor-grade go-to-market intelligence report: market sizing, FDA regulatory pathway, competitive landscape, funding strategy, IP landscape, and commercialization recommendations, in about 30-60 seconds.

It is built for two audiences:

- **Principal Investigators (PIs)**: academic researchers who have a discovery but no commercialization training, and need to know "is this worth pursuing, what's the regulatory path, who would fund it, and how do I write the grant/licensing pitch."
- **Tech Transfer Offices (TTOs)**: university offices that screen hundreds of invention disclosures per year and need fast, defensible, source-cited triage to decide what to patent, license, or spin out.

Medlevate is positioned against two categories of existing tools:

1. **PitchBook** ($24,000/seat/year): a financial database of VC deals, fund performance, and company data. Extremely strong on "who funds what" but has no biomedical domain reasoning, no regulatory pathway analysis, and is priced out of reach for most academic labs and TTOs.
2. **Edison Scientific / Kosmos** (~$200/run): an autonomous AI research agent that reads ~1,500 papers and runs ~42,000 lines of analysis code per run to do "6 months of PhD work in a day." Extremely strong on literature synthesis and data analysis, but not focused on commercialization, regulatory strategy, or investor/funding intelligence.

Medlevate's thesis: a PI or TTO officer using ChatGPT plus manual web searches cannot replicate this report, because (a) ChatGPT has no live access to clinical trial registries, SEC filings, patent databases, NIH grant databases, or FDA label databases, (b) ChatGPT does not run a calibrated, auditable market-sizing calculation, and (c) ChatGPT does not accumulate institutional memory across reports for the same PI or disease area. Medlevate does all three, automatically, on every report.

---

## 2. End-to-End Pipeline: From Idea to Report

This is the technical core of the product, and the part that differentiates it from "an LLM with a system prompt."

### Step 1: Intake and Embedding
The PI submits a free-text idea plus a coarse modality (small molecule, biologic, gene/cell therapy, medical device, diagnostic, digital health, etc.). The idea text is embedded (OpenAI `text-embedding-3-small`) and matched via pgvector cosine similarity against:
- A database of ~46,700+ federal demand signals (NIH grants, FDA actions, clinical trial gaps, etc.)
- A database of hospital-submitted unmet clinical needs (collected via a separate intake pipeline)

### Step 2: Mixture-of-Experts Routing
A lightweight Claude Haiku call (`expert_router.py`) classifies the idea into one of ~12 fine-grained subcategories (e.g., `drug_amr`, `oncology`, `gene_cell_therapy`, `medical_device`, `digital_health`), which roll up into 6 top-level domain experts (Antibiotic/AMR, Oncology, Cardiology, Neurology/CNS, Metabolic/Diabetes, Mental Health). Each expert profile carries its own system prompt, domain knowledge, and report structure. If the PI manually selected a domain and Claude's classification disagrees, the PI is shown a "mismatch warning" rather than silently overriding their choice.

### Step 3: Parallel Data-Gathering Layer (the "Multi-Source Retrieval Pipeline")
This is the largest engineering investment in the system. A single `asyncio.gather`, hard-capped at 20 seconds (well under Railway's ~60s proxy timeout), fires off roughly 10 independent async data-gathering tasks in parallel. Each task is wrapped so that a failure or timeout degrades gracefully (returns nothing) rather than crashing the report. The tasks include:

1. **Full competitive intelligence** - active clinical trials, competitor pipelines
2. **Landmark publications** - top-cited papers for the disease area
3. **Demand-signal competitive intelligence** - cross-referencing the federal demand-signal database
4. **Source aggregation** - merges results across all connectors into a deduplicated source list
5. **Chapter data service** - subcategory-specific structured data (pricing precedent, ICER assessments, OECD health stats, etc.)
6. **Retrieval Pipeline (MSRP)** - a tiered, adaptive retrieval system (described below)
7. **Expert Panel** - 3 parallel Haiku sub-analyses (described below)
8. **Funding Intelligence** - real-time fundraising signals (NIH SBIR/STTR awards, SEC EDGAR 8-K private placements, bioRxiv/medRxiv preprint velocity, ClinicalTrials.gov new-sponsor detection)
9. **Patent Landscape** - recent US patent filings and top assignees (Google Patents)
10. **Regulatory Precedent** - FDA-approved drugs already on label for this indication (openFDA)

#### The Multi-Source Retrieval Pipeline (MSRP)
This implements an **Adaptive RAG + CRAG (Corrective RAG)** pattern across **47 free, public data connectors** (`app/ingestion/connectors/`), including:

- **Clinical/regulatory**: ClinicalTrials.gov, openFDA, FDA Approvals, DailyMed, EMA EPAR, Health Canada, NICE HTA, Orphanet, NIH GARD
- **Genomics/biology**: ClinVar, UniProt, Reactome, STRING-DB, Open Targets, GTEx, Human Protein Atlas, cBioPortal, MONDO ontology, RxNorm, PubChem
- **Literature**: PubMed (canonical), OpenAlex, Semantic Scholar, bioRxiv/medRxiv
- **Funding/financial**: NIH Reporter (grants + SBIR/STTR), Grants.gov, USAspending.gov, SEC EDGAR, CMS (ASP, Open Payments, Part D prescriber data, formulary, spending, quality)
- **Epidemiology/health economics**: SEER Cancer, CDC PLACES, CDC Surveillance, AHRQ MEPS, County Health Rankings, Census SAHIE, OECD Health, WHO GHO
- **IP**: USPTO/Lens patent connectors, Google Patents
- **Other**: GDELT (news signals), RSS feeds, Reddit (clinical pain points)

Sources are organized into **tiers by latency** (Tier 0 = pre-loaded/instant lookup tables, Tier 1 = sub-800ms APIs, Tier 2 = sub-4s APIs, Tier 3 = sub-10s APIs), and which sources are even queried is determined by a **subcategory relevance map** - e.g., ClinVar is never queried for a metabolic-disease drug, Orphanet is never queried for a common-disease oncology drug. The pipeline starts with Tier 0/1 sources and only escalates to slower tiers if **coverage** (the fraction of required "facts" for that report chapter that have been satisfied) is below threshold. This is the CRAG part: the system evaluates the quality/completeness of what it has retrieved before deciding whether to spend more time retrieving.

The output is a set of **facts**, each tagged with its source, confidence, and the specific chapter of the report it supports, plus pre-formatted context blocks. If average coverage exceeds 20%, this block is **prepended** to the LLM context with an explicit instruction: *"Use these database-grounded facts. They override Claude's training data."* This is the mechanism that keeps numbers in the report grounded in real, current data rather than the LLM's (possibly stale or hallucinated) training knowledge.

### Step 4: The Expert Panel (Mixture-of-Experts sub-analysis)
Before the final synthesis, three **parallel Claude Haiku calls** run independent structured analyses, each from a different professional lens:

- **Clinical Validity Expert**: scores the mechanism of action, identifies scientific risks, flags red flags
- **Regulatory Pathway Expert**: recommends an FDA pathway and an approval-probability estimate, **anchored to a calibrated historical lookup table** (`ptrs_tables.py` - Phase Transition & Regulatory Success rates by therapeutic area and development phase, derived from published FDA approval-rate data). The LLM's estimate is clamped to within +/-10 percentage points of this historical baseline, so the model cannot produce wildly optimistic or pessimistic numbers untethered from real approval-rate data.
- **Commercial Viability Expert**: scores competitive moat and pricing, grounded in a **deal-comparables database** (`deal_comps.py` - upfront/milestone/royalty ranges by therapeutic area, sourced from AUTM FY2024 licensing surveys, BIO/Informa industry reports, and peer-reviewed deal-term studies)

Each sub-panel's output is structured JSON, not free text, and is injected into the final synthesis prompt as a **mandatory, high-priority context block** with explicit integration rules: the final report *must* reference the panel's findings, *must* use the panel's approval-probability as its baseline (only overridable with cited evidence), and *must* explicitly state any disagreement ("The panel assessed X; however, based on [evidence], my assessment is Y"). This is what makes it a genuine mixture-of-experts system rather than one model role-playing three personas in a single call: each panel is a separate API call with its own system prompt, its own grounding data, and its output is auditable independently of the final report.

### Step 5: Context Assembly
All of the above is assembled into a single context document for the final synthesis call, in priority order:

1. Persistent research world model (see Step 7)
2. TRL (Technology Readiness Level) assessment
3. Expert panel findings
4. Investor matches
5. VC fund performance benchmarks
6. Real-time funding intelligence
7. Patent landscape
8. Regulatory precedent (approved-drug landscape)
9. Key Opinion Leader network
10. Deep literature synthesis (PMID-traceable)
11. General competitive intelligence and market-sizing derivation

### Step 6: Final Synthesis (Claude Opus)
A single call to **`claude-opus-4-5`** receives the assembled context plus a detailed JSON schema (`EXPERT_JSON_SCHEMA`) and a domain-specific system prompt from the routed expert. The reporting instructions enforce:
- Every number must cite its source by name
- TAM/SAM/SOM figures must come *only* from the bottom-up derivation computed earlier (the LLM is not allowed to invent its own market-size numbers)
- Regulatory timelines must cite a comparable approved drug
- Market access pricing must cite CMS ASP or reimbursement data
- Uncertain figures must be given as a ranged estimate with sources for both ends

The response is parsed into a strongly-typed Pydantic model, `PIReport`, with structured sub-sections for disease intelligence, market sizing (with a full step-by-step calculation trail), regulatory pathway (with named designations like QIDP/Fast Track/Orphan Drug and their eligibility/benefit/timeline), market access strategy (buyer segments, KOLs, reimbursement pathway), supporting evidence items (each with a similarity score and source URL), and a strategic playbook.

### Step 7: Persistent Research World Model (cross-report learning)
After the report is generated, a background task extracts structured facts (competitor companies and trials, TAM/SAM figures, regulatory pathway, top cited papers) and writes them into a PostgreSQL table (`research_world_model`), keyed by disease area, with a 90-day expiry. The **next** report generated for that disease area loads this accumulated context first, so the system gets progressively better-informed about a given disease area over time, the same way a human analyst would build up domain knowledge across projects. This is explicitly modeled on Edison Scientific's "world model" concept but implemented with a simple Postgres table rather than a large persistent knowledge graph.

### Step 8: PI Institutional Memory
Separately, every report a given PI generates has key facts extracted and stored against that PI's account. Future reports for the same PI inject this memory, so after a few reports the system "knows" that PI's competitive landscape, regulatory strategy, and disease focus area without re-deriving it from scratch. This is explicitly the long-term retention moat: a fresh ChatGPT session has none of this continuity.

---

## 3. Full Feature Inventory

### Core report generation (`/api/v1/alignment/pi-report`)
The flagship feature described in Section 2. Output is a structured `PIReport` containing:
- Executive summary
- Disease intelligence (incidence/prevalence/mortality with sources, resistance/pipeline status)
- Bottom-up market sizing (every step shown: patient population x price x penetration = TAM, with source and URL for each input)
- FDA regulatory pathway (recommended pathway + rationale, eligible designations with how-to-apply guidance, phase-by-phase clinical trial requirements with cost estimates and FDA guidance documents, total timeline/cost estimates, friction points, "loopholes" like NTAP/PASTEUR Act/BARDA/CARB-X funding)
- Market access strategy (buyer segments, decision-makers, price per unit, annual spend per facility, KOLs, reimbursement pathway)
- Supporting evidence (every claim traceable to a source with a similarity score)
- Hospital need matches (does this idea address a real, documented clinical pain point)
- Recommended next steps and strategic playbook
- Full literature citation list

### Mixture-of-Experts intelligence layer
- **Expert Router**: Haiku-based domain classification across 6 top-level / ~12 fine-grained domains
- **Expert Panel**: 3 parallel Haiku sub-panels (clinical / regulatory / commercial), each grounded in calibrated reference tables
- **PTRS tables**: calibrated historical FDA approval-rate tables by therapeutic area and phase
- **Deal comps database**: licensing deal-term benchmarks (upfront/milestone/royalty) by therapeutic area, sourced from AUTM/BIO/peer-reviewed data

### Commercialization & investor-readiness tools
- **TRL (Technology Readiness Level) assessment**: maps the idea + development phase to a 1-9 TRL score using the NIH NHLBI Catalyze / BARDA framework, with cost-to-next-level estimates, SBIR Phase I/II readiness flags, and an "investor readiness" stage label
- **Investor matcher**: a curated database of 45 biomedical investors and funders (ARCH Venture, Flagship Pioneering, Third Rock, OrbiMed, Versant, RA Capital, Novo Ventures, Foresite Capital, J&J Innovation/JLABS, Leaps by Bayer, a16z Bio+Health, BARDA, CARB-X, NIH/NCI SBIR, etc.), scored and matched by therapeutic area, TRL fit, and academic-spinout friendliness
- **VC fund performance benchmarks**: published Cambridge Associates / NVCA / PitchBook-summary vintage-year IRR/TVPI/DPI data for biotech VC funds, plus stage-specific return expectations (e.g., "Series A biotech investors target 5-15x MOIC; comparable: Blueprint Medicines, ~125x") - so a PI knows what an investor needs to see to say yes
- **Non-Confidential Summary (NCS) generator**: produces a ready-to-send NCS document (title, technology summary, unmet need, applications, competitive advantages, development status, IP status, collaboration ask, tagline) for licensing outreach, via `claude-sonnet-4-6`
- **Grant Co-Pilot**: generates ready-to-paste NIH R01 (Significance/Innovation/Approach), NIH SBIR/STTR (Significance/Innovation/Commercialization), and NSF (Intellectual Merit/Broader Impacts) grant sections from the report

### Real-time competitive & market intelligence (all free public data)
- **Funding Intelligence**: recent NIH SBIR/STTR awards in the space (NIH Reporter API), recent private-placement signals from SEC 8-K filings (SEC EDGAR full-text search), bioRxiv/medRxiv preprint velocity (research-momentum signal), and first-time clinical trial sponsors entering the space (ClinicalTrials.gov)
- **Patent Landscape**: recent US patent filings related to the disease/technology, top assignees (companies and universities actively patenting), and an FTO/whitespace signal (CROWDED / ACTIVE / OPEN), via Google Patents' public search API
- **Regulatory Precedent**: FDA-approved drugs already on label for the target indication, their manufacturers, routes of administration, and label-update recency, via openFDA - establishes the standard-of-care bar and identifies potential partners/acquirers
- **KOL (Key Opinion Leader) network**: top authors by citation influence in the disease area, plus a literature-momentum signal, via Semantic Scholar
- **Deep literature synthesis**: a dedicated Haiku call that reads the retrieved publication set and produces PMID-traceable "proven findings," "open questions," a direct comparison of the PI's approach to the literature, and any conflicting evidence

### Data analysis ("Edison-lite")
- **Dataset analysis** (`/api/v1/alignment/analyze-data`): a PI uploads experimental data as CSV (up to 50,000 characters - e.g., IC50 tables, efficacy/survival data, binding affinity, gene expression). The service computes full descriptive statistics (mean/median/std/percentiles via numpy), auto-detects the data type (IC50, efficacy %, survival, binding, gene expression, clinical/PK, cytotoxicity), and uses Haiku plus a live PubMed search to contextualize the results against published benchmarks with specific PMIDs - e.g., "your median IC50 of 45nM is in the top quartile of published analogues for this target class (range 2-200nM, PMID XXXXXXXX)," including what this means for TRL and the investor narrative.

### Discovery, portfolio, and operational tools
- **Opportunity discovery**: a pre-scored universe of commercialization opportunities, ranked and filterable
- **Idea Builder**: interactive clarifying-question flow to help a PI articulate an underspecified idea
- **Competitive sweep**: on-demand competitive landscape refresh for a given idea
- **Lab Portfolio Discovery**: scores up to 10 ideas across demand, funding opportunity, competition, and feasibility, producing an innovation heatmap for lab directors/TTOs deciding what to prioritize
- **Trial Site Optimizer**: recommends the best Phase II/III recruitment sites by scoring hospitals against a CMS quality-deficit index across patient volume, quality deficit, and other criteria
- **Development Timeline Generator**: converts a PIReport into a date-anchored Gantt-style development plan (preclinical through Phase 3), with regulatory milestones, funding windows, and iCal export
- **Watchlists & Alerts**: PIs/TTOs can save a topic; a weekly scheduled job (`weekly_tracker.py`) compares newly ingested demand signals against all watchlists using a two-pass match (keyword, then embedding cosine similarity >= 0.65) and generates alerts
- **Hospital Need Ingestion**: a separate intake pipeline where hospital staff submit free-text clinical pain points, which are classified (department/category/urgency/impact) and embedded, forming the demand-signal database that every report is matched against

### Platform / SaaS infrastructure
- User accounts, auth, and subscription tiers (explorer / innovator / institution) with Stripe billing
- Rate limiting middleware to protect LLM API budgets
- Admin endpoints for ingestion monitoring and manual provisioning
- PostgreSQL + pgvector for semantic search across ~46,700+ federal demand signals

---

## 4. Technical Stack

- **Backend**: Python 3.12, FastAPI, asyncpg, Pydantic v2
- **Database**: PostgreSQL with pgvector extension (semantic search over demand signals, hospital needs, world model facts)
- **LLM providers/models**:
  - `claude-opus-4-5` - main report synthesis (highest quality, used once per report)
  - `claude-haiku-4-5-20251001` - expert routing, the 3-panel mixture-of-experts sub-analyses, literature synthesis, dataset interpretation (cheap and fast, used many times per report)
  - `claude-sonnet-4-6` - Non-Confidential Summary generation
  - OpenAI `text-embedding-3-small` - embeddings for semantic search
- **Deployment**: Railway (Nixpacks build), `uvicorn` with extended keep-alive, auto-deploy from `main` branch
- **Data sources**: 47 free, public, no-API-key (or free-tier) connectors spanning clinical trials, regulatory databases, genomics, literature, federal funding/financial filings, epidemiology, and patents (full list in Section 2)
- **Latency budget**: all parallel data-gathering is hard-capped at 20 seconds via `asyncio.wait_for`, individual connector timeouts of 8-12 seconds, `return_exceptions=True` so any single source failing does not fail the report - keeps total report generation comfortably under typical proxy/load-balancer timeouts (~60s)

---

## 5. Why This Is Not "a GPT Wrapper"

A "GPT wrapper" is, at minimum, a single LLM call with a system prompt over user input. Medlevate differs in every dimension:

| Dimension | GPT wrapper | Medlevate |
|---|---|---|
| LLM calls per report | 1 | ~6-8 (router, 3-panel MoE, literature synthesis, dataset interpretation if used, final synthesis) |
| Live external data | None (training data only, possibly stale) | 47 free public data connectors, queried live, in parallel, every report |
| Numeric grounding | LLM invents numbers | Market sizing computed by a deterministic derivation engine; regulatory approval probabilities anchored to calibrated historical tables (+/-10pp clamp); deal terms anchored to a sourced comps database |
| Citations | Often fabricated | Every fact is tagged with its source connector and, where applicable, a PMID, NCT ID, SEC filing, or patent number |
| Memory | None - every session starts cold | Persistent research world model (per disease area, 90-day rolling) and PI institutional memory (per user, across all their reports) |
| Output structure | Free text | Strongly-typed Pydantic schema with 10+ structured sub-sections, machine-readable for downstream tools (timeline generator, grant co-pilot, etc.) |
| Domain specialization | One generic prompt | 6 domain experts x ~12 subcategories, each with its own prompt, relevant-source map, and reference tables |

---

## 6. Impact on TTOs and PIs

**The problem Medlevate addresses**: most university research never reaches patients, not because the science is bad, but because of the "valley of death" between a lab discovery and a fundable, licensable, regulatorily-coherent commercialization plan. PIs are domain experts in their science, not in FDA pathways, market sizing, deal structures, or investor expectations. TTOs are understaffed relative to the volume of invention disclosures they receive (often hundreds per year per office, with only a handful of staff who must each cover every therapeutic area). The result: many disclosures are triaged based on incomplete information, good ideas stall for lack of a clear commercialization narrative, and PIs waste months on paths (wrong regulatory pathway, wrong investor type, wrong market-size assumptions) that an experienced analyst would have flagged in an afternoon.

**What Medlevate changes**:

- **Speed**: a report that would take a TTO analyst or consultant days (and cost thousands of dollars if outsourced) is generated in under a minute.
- **Cost**: PitchBook alone costs $24,000/year/seat and doesn't address regulatory or scientific questions at all; Edison Scientific charges ~$200/run and doesn't address commercialization. Medlevate is priced for individual labs and TTOs (explorer/innovator/institution tiers), making this kind of analysis accessible to institutions that could never afford either.
- **Consistency and auditability**: every number in the report traces to a named source. A TTO can defend a triage decision ("we deprioritized this because three competitors already have Phase 2 data and the regulatory pathway requires X") with citations, not vibes.
- **Earlier, better-informed decisions**: by surfacing FDA designations (Orphan Drug, Fast Track, QIDP, etc.), funding programs (BARDA, CARB-X, SBIR/STTR), and investor fit *before* a PI commits months to the wrong strategy, Medlevate shifts commercialization decisions earlier in the pipeline, when they're cheapest to change.
- **Compounding institutional knowledge**: the persistent world model and PI memory mean that as a TTO or lab uses Medlevate repeatedly, the system becomes a genuinely better-informed advisor for *that institution's* specific portfolio and disease areas, something no generic AI tool can offer.
- **Broader societal impact**: more translational research that successfully navigates from bench to commercialization means more therapies, diagnostics, and devices reaching patients, more efficient allocation of scarce TTO staff time, and better-targeted use of federal SBIR/STTR and grant funding (since applicants enter the process with a more realistic, evidence-based plan).

**Current traction**: Medlevate is live in production (Railway-hosted FastAPI backend) and is in early-access pilot use with tech transfer offices, including Washington University in St. Louis's Office of Technology Management.

---

## 7. Suggested Use of This Document

When asking Claude or ChatGPT for help with grant-application language (e.g., NSF I-Corps, NIH SBIR/STTR Phase I, state/regional accelerator programs), paste this document as context and then ask specific questions such as:
- "Help me write the Innovation section describing the mixture-of-experts architecture in Section 2-4."
- "Help me write the Commercial Potential / Broader Impacts section using the TTO/PI impact narrative in Section 6."
- "Help me describe our technical approach in plain language for a non-technical reviewer, based on Sections 2 and 3."
