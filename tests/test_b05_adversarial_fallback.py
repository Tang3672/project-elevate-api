"""B-05 — Adversarial review fallback must not expose internal error strings.

The spec requires that when the Anthropic API is unavailable (no key, timeout,
parse failure), the adversarial_review section is suppressed entirely rather
than showing 'API key not set' / 'Not assessed' to users.
"""
from __future__ import annotations

import pytest


_BANNED = [
    "api key",
    "not set",
    "not assessed",
    "pending verification",
    "manual review required",
    "dev mock",
    "no api tokens",
]


def _has_banned(text: str) -> list[str]:
    t = text.lower()
    return [b for b in _BANNED if b in t]


class TestAdversarialFallback:
    def test_fallback_returns_empty_list(self):
        from app.services.adversarial_review_service import _fallback_review
        assert _fallback_review([]) == []

    def test_fallback_with_recommendations_returns_empty_list(self):
        from app.services.adversarial_review_service import _fallback_review
        result = _fallback_review(["Pursue SBIR", "Build pilot with 3 labs"])
        assert result == [], f"Expected [], got {result!r}"

    def test_fallback_output_contains_no_banned_strings(self):
        from app.services.adversarial_review_service import _fallback_review
        result = _fallback_review(["Recommendation X", "Recommendation Y"])
        full = str(result)
        found = _has_banned(full)
        assert not found, f"Banned strings in fallback output: {found}\nOutput: {full}"

    def test_fallback_is_json_serializable(self):
        import json
        from app.services.adversarial_review_service import _fallback_review
        result = _fallback_review(["Step A"])
        json.dumps(result)  # must not raise

    @pytest.mark.asyncio
    async def test_run_adversarial_review_no_key_returns_empty(self, monkeypatch):
        """When ANTHROPIC_API_KEY is unset, run_adversarial_review returns []."""
        import os
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from app.services import adversarial_review_service as svc

        fake_report = {
            "recommended_next_steps": [
                "Pilot with 3 university labs",
                "Apply for SBIR Phase I",
            ],
        }
        result = await svc.run_adversarial_review(fake_report, idea="Test product")
        assert result == [], f"Expected [] when API key absent, got {result!r}"
        full = str(result)
        assert not _has_banned(full), f"Banned strings in result: {_has_banned(full)}"

    @pytest.mark.asyncio
    async def test_run_adversarial_review_http_error_returns_empty(self, monkeypatch):
        """When the HTTP call raises, run_adversarial_review falls back to []."""
        import os
        import httpx
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")

        async def _fake_post(*args, **kwargs):
            raise httpx.ConnectError("connection refused")

        import app.services.adversarial_review_service as svc

        class _FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self, *args, **kwargs):
                raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeClient())

        fake_report = {"recommended_next_steps": ["Do X", "Do Y"]}
        result = await svc.run_adversarial_review(fake_report, idea="Test")
        assert result == [], f"Expected [] on HTTP error, got {result!r}"
