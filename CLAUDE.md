# Medlevate — Codebase Rules for Claude

## ⚠️ Most Important Rule: Where to Add Market Sizing Features

**ALWAYS add market sizing features to `app/services/market_sizing_derivation_service.py`.**

**NEVER add market sizing features to `app/services/market_sizing_orchestrator.py`.**

### Why this matters

`market_sizing_orchestrator.py` is dead code. It is not called during report generation.
Every feature added there is silently discarded and will never appear in a report.

The real production path is:

```
alignment_service.py
  └─ generate_market_sizing_derivation()   ← market_sizing_derivation_service.py
  └─ format_derivation_for_prompt()        ← market_sizing_derivation_service.py
```

The orchestrator is only used by offline validation scripts. It is preserved for
experimentation but must never be imported from `alignment_service.py`.

### How this is enforced

Three layers catch violations automatically:

1. **Pre-commit hook** (`.git/hooks/pre-commit`) — blocks any commit that imports the
   orchestrator from `alignment_service.py`.

2. **Test suite** (`tests/test_pipeline_wiring.py`) — 5 tests that fail loudly if the
   wrong module is wired, if the derivation service stops importing the triangulator,
   or if the prompt builder drops the cross-validation block.

3. **Runtime logger.error** — `orchestrator.run()` logs an ERROR with the caller stack
   if it is ever invoked during a real report, so it shows up immediately in Railway logs.

---

## Backend / Frontend Branching Rules

- **Backend changes** → commit to `develop`, run tests, merge to `main` only after
  explicit user approval ("merge it"). Never commit backend directly to `main`.
- **Frontend changes** → commit directly to `main`.
- Railway auto-deploys on push to `main`.

---

## Key Architecture

| File | Role |
|---|---|
| `alignment_service.py` | Main report generation coordinator |
| `market_sizing_derivation_service.py` | **Real** market sizing pipeline (MoE router + 9 formulas) |
| `market_sizing_triangulator.py` | Bottom-up vs top-down cross-validation |
| `market_sizing_engine.py` | Under-diagnosis correction + treatment funnel |
| `market_sizing_orchestrator.py` | ⚠️ Dead code — offline validation only |
| `database.py` | asyncpg connection pool (min 2, max 10) |
| `main.py` | FastAPI app entry point |

## Deployment

- Platform: Railway (auto-deploy on push to `main`)
- Database: PostgreSQL + pgvector (Railway managed)
- API key: `ANTHROPIC_API_KEY` in Railway environment variables
