"""
Unit tests for the source URL validator (collector + nulling logic).
The network check itself (_check_one) is not unit-tested here.

Run with: pytest tests/test_url_validator.py -v
"""

import asyncio
from unittest.mock import patch

from app.services.url_validator import _collect_url_refs, clean_report_urls


def test_collect_url_refs_recursive():
    rep = {
        "sources": [{"name": "A", "url": "https://cdc.gov"}, {"name": "B", "url": None}],
        "market_sizing": {"steps": [{"source_url": "https://fda.gov/x"}]},
        "supporting_evidence": [{"source_url": "https://pubmed.gov/1"}],
        "note": "not a url", "n": 5,
    }
    refs = []
    _collect_url_refs(rep, refs)
    urls = sorted(obj[key] for obj, key in refs)
    assert urls == ["https://cdc.gov", "https://fda.gov/x", "https://pubmed.gov/1"]


def test_clean_nulls_dead_keeps_alive():
    rep = {"sources": [
        {"name": "alive", "url": "https://alive.test/a"},
        {"name": "dead", "url": "https://dead.test/b"},
    ]}

    async def fake_check(client, url):
        return url, url.endswith("/b")   # /b is "dead"

    async def run():
        with patch("app.services.url_validator._check_one", fake_check):
            return await clean_report_urls(rep)

    stats = asyncio.run(run())
    assert stats["checked"] == 2 and stats["dead"] == 1
    by_name = {s["name"]: s["url"] for s in rep["sources"]}
    assert by_name["alive"] == "https://alive.test/a"
    assert by_name["dead"] is None


def test_no_urls():
    stats = asyncio.run(clean_report_urls({"sources": [{"name": "x", "url": None}]}))
    assert stats == {"checked": 0, "dead": 0}
