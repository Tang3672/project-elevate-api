# Medlevate — Production Readiness Status

Honest status of the standard production-hardening checklist. ✅ = in place,
🟡 = partial / just added, ⛔ = not code (infra / legal / process), ⬜ = TODO.

## Security
| Item | Status | Notes |
|---|---|---|
| Input sanitization & injection prevention | ✅ | Pydantic validates every request body; DB access is 100% parameterized (`asyncpg` `$1..$n`) — no string-built SQL. |
| Authentication, authorization, roles | 🟡 | JWT auth (`auth_service`), bearer tokens, dev-email allowlist, subscription gating. Fine-grained RBAC/roles: ⬜. |
| Session management & token expiry | ✅ | JWTs carry `exp`/`iat`; checked on every authed route. |
| Secrets management | 🟡 | All secrets from env (`settings`/`os.environ`), never committed. A managed secret store (Railway secrets / Vault) + rotation: ⛔ infra. |
| HTTPS / TLS / cert rotation | ⛔ | Terminated + auto-rotated by Railway (API) and Netlify (frontend). **HSTS now sent** (`security_headers.py`). |
| Rate limiting & abuse prevention | ✅ | `RateLimitMiddleware` protects the LLM-token budget. |
| Dependency scanning & vuln patching | 🟡 | **`pip-audit` now runs in CI** (informational). Make it a failing gate once the tree is clean. |
| Multi-tenancy & data isolation | 🟡 | Portfolio/reports now scoped by `user_id` (no cross-account leakage). Full row-level tenancy: ⬜. |
| PII handling / retention / deletion | ⬜ | No special-category PHI stored today (ideas + public data). Needs a retention/deletion policy before storing PHI. |
| Regulatory compliance (GDPR, HIPAA) | ⛔ | A legal + organizational program (BAAs, DPAs, audits), not a code change. Don't market as compliant until certified. |
| Audit trails & tamper-evident logging | ⬜ | `report_outcomes` logs decisions; a dedicated append-only audit log is ⬜. |
| Security response headers | ✅ | **Added**: HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, CORP. |
| CORS | ✅ | **Tightened** from `*` to the Netlify frontends + localhost (regex) + `ALLOWED_ORIGINS` env. |

## Testing & quality
| Item | Status | Notes |
|---|---|---|
| Unit / integration / e2e tests | 🟡 | 70 unit tests (pure logic). Integration/e2e against a live stack: ⬜. |
| Regression tests | ✅ | The suite **now runs in CI** on every push/PR to `main`/`develop`. |
| Load & stress testing | ⛔ | Separate tooling (k6/Locust) + environment. |
| Chaos / resilience testing | ⛔ | Separate practice; partial resilience already built (timeouts, retries, graceful degradation). |
| Coverage thresholds in CI | 🟡 | Coverage **reported** in CI; a hard threshold is off until coverage is built up (would block all PRs today). |
| Code review process | 🟡 | CI gates PRs; branch protection / required reviews is a repo-settings step. |

## Resilience & ops
| Item | Status | Notes |
|---|---|---|
| Error handling & graceful degradation | ✅ | Every external call wrapped + degrades; **global exception handler** returns clean JSON 500 (no stack-trace leak). |
| Retry logic w/ backoff & idempotency | 🟡 | Synthesis retry; URL-check retry; Keychain/HTTP retries. Systematic idempotency keys: ⬜. |
| Circuit breakers & fallback | 🟡 | Fallbacks everywhere (timeouts → "unavailable", partial data). Formal circuit breakers: ⬜. |
| Concurrency / race conditions | 🟡 | Async job store is single-worker + DB-backed; report jobs are idempotent on `job_id`. |
| Caching & invalidation | 🟡 | `cache_warmer` + world-model 90-day expiry. A formal cache layer (Redis) + invalidation: ⬜. |
| RTO / RPO / disaster recovery | ⛔ | Managed Postgres backups (Railway). A documented DR plan + drills: ⬜ process. |
| Accessibility | ⬜ | Frontend a11y audit (labels, contrast, keyboard nav) not yet done. |
| Architecture diagrams / ADRs | 🟡 | `MEDLEVATE_TECHNICAL_OVERVIEW.md` documents the architecture; formal ADRs: ⬜. |

## What was added in this pass (code)
- `app/middleware/security_headers.py` — security response headers.
- `app/main.py` — CORS restricted to known origins; global exception handler.
- `.github/workflows/ci.yml` — pytest (regression gate) + coverage + `pip-audit` on every push/PR.

## Recommended next (highest value, code-level)
1. Branch protection on `main` requiring CI to pass (repo setting).
2. A real audit-log table (who/what/when) for report + outcome mutations.
3. Idempotency keys on mutating endpoints (`/feedback`, `/review-update`).
4. Frontend accessibility pass.
5. A PHI retention/deletion policy *before* storing any patient-level data.
