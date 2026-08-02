"""
H-03 — Cross-project data leakage tests.

The defect: a Hublink report cited "The PI's prior Acute Ischemic Stroke diagnostic
report estimated similar De Novo costs for a clinical-grade diagnostic SaMD."
Nothing in the Hublink intake mentioned stroke. This is either cross-user retrieval
leakage (world model keyed by disease across all users) or LLM hallucination of
a plausible cross-reference.

Fixes verified here:
  1. research_world_model.load_world_model() requires user_id — returns "" without it.
  2. research_world_model.load_world_model() scopes query to user_id — verified by
     inspecting the SQL in the function source.
  3. research_world_model.update_world_model() writes user_id on every row.
  4. alignment_service.py reporting rules explicitly ban cross-report references.
  5. The world_model_ctx = "" assignment means reads are currently disabled globally.
"""

import ast
import inspect
import os
import re
import pytest

_APP_ROOT = os.path.join(os.path.dirname(__file__), "..", "app")


# ── 1. load_world_model requires user_id ─────────────────────────────────────

class TestLoadWorldModelScoping:

    def _get_source(self):
        from app.services.research_world_model import load_world_model
        return inspect.getsource(load_world_model)

    def test_load_world_model_returns_empty_when_no_user_id(self):
        """Without user_id, load_world_model must return '' (no cross-user reads)."""
        import asyncio
        from app.services.research_world_model import load_world_model
        # Call with no user_id — must short-circuit to "" without DB access
        result = asyncio.get_event_loop().run_until_complete(
            load_world_model("ischemic stroke")  # no user_id
        )
        assert result == "", (
            "load_world_model() without user_id must return '' to prevent cross-user reads"
        )

    def test_load_world_model_signature_has_user_id_param(self):
        from app.services.research_world_model import load_world_model
        import inspect
        sig = inspect.signature(load_world_model)
        assert "user_id" in sig.parameters, \
            "load_world_model() must have a user_id parameter (H-03 scoping)"

    def test_load_world_model_sql_filters_by_user_id(self):
        src = self._get_source()
        # The SQL must contain user_id filter
        assert "user_id" in src, \
            "load_world_model() SQL must filter by user_id (H-03 scoping)"

    def test_load_world_model_sql_does_not_query_all_users(self):
        src = self._get_source()
        # Must NOT have a query that selects without user_id filter in the WHERE
        # Look for the SELECT block — it must include user_id = $N
        select_blocks = re.findall(r'SELECT.*?LIMIT\s+\d+', src, re.DOTALL | re.I)
        for block in select_blocks:
            assert "user_id" in block, \
                f"SELECT block in load_world_model missing user_id filter: {block[:200]}"


# ── 2. update_world_model writes user_id ─────────────────────────────────────

class TestUpdateWorldModelScoping:

    def _get_source(self):
        from app.services.research_world_model import update_world_model
        return inspect.getsource(update_world_model)

    def test_update_world_model_signature_has_user_id(self):
        from app.services.research_world_model import update_world_model
        sig = inspect.signature(update_world_model)
        assert "user_id" in sig.parameters, \
            "update_world_model() must accept user_id parameter"

    def test_update_world_model_inserts_user_id(self):
        src = self._get_source()
        assert "user_id" in src, \
            "update_world_model() must include user_id in INSERT statement"

    def test_update_world_model_tags_unscoped_rows(self):
        src = self._get_source()
        # Facts without user_id should be tagged '__unscoped__' not left NULL
        assert "__unscoped__" in src, \
            "update_world_model() must tag rows without user_id as '__unscoped__'"


# ── 3. world_model reads are currently disabled in alignment_service ──────────

class TestWorldModelDisabledInAlignmentService:

    def _get_alignment_source(self):
        path = os.path.join(_APP_ROOT, "services", "alignment_service.py")
        with open(path) as f:
            return f.read()

    def test_world_model_ctx_is_assigned_empty_string(self):
        src = self._get_alignment_source()
        # The line 'world_model_ctx = ""' must exist (reads disabled)
        assert 'world_model_ctx = ""' in src, \
            "alignment_service.py must set world_model_ctx = '' (cross-user reads disabled)"

    def test_world_model_load_is_not_called(self):
        src = self._get_alignment_source()
        # load_world_model should not be called in alignment_service
        assert "load_world_model(" not in src, \
            "alignment_service.py must not call load_world_model() (H-03: reads disabled)"

    def test_update_world_model_is_not_called_from_report_path(self):
        src = self._get_alignment_source()
        # _update_world_model_bg should be defined but never called via create_task/await
        assert "create_task(_update_world_model_bg" not in src, \
            "alignment_service.py must not schedule world model writes (H-03: writes disabled)"
        assert "await _update_world_model_bg" not in src, \
            "alignment_service.py must not await world model writes (H-03: writes disabled)"


# ── 4. Synthesis prompt bans cross-report references ─────────────────────────

class TestCrossReportBanInSynthesisPrompt:

    def _get_alignment_source(self):
        path = os.path.join(_APP_ROOT, "services", "alignment_service.py")
        with open(path) as f:
            return f.read()

    def test_reporting_instruction_bans_cross_report_reference(self):
        src = self._get_alignment_source()
        assert "CROSS-REPORT ISOLATION" in src or "cross-report" in src.lower() or \
               "prior report" in src.lower(), \
            "alignment_service.py reporting instructions must ban cross-report references"

    def test_prior_pi_report_phrase_is_banned(self):
        src = self._get_alignment_source()
        assert "PI's prior" in src or "prior report" in src.lower(), \
            "The exact banned phrase 'PI's prior report' must appear in the ban instruction"

    def test_cross_report_isolation_label_present(self):
        src = self._get_alignment_source()
        assert "H-03" in src, \
            "alignment_service.py should reference H-03 in the cross-report isolation rule"


# ── 5. DB table schema includes user_id ──────────────────────────────────────

class TestWorldModelTableSchema:

    def _get_init_source(self):
        from app.services.research_world_model import init_world_model_table
        return inspect.getsource(init_world_model_table)

    def test_create_table_includes_user_id_column(self):
        src = self._get_init_source()
        assert "user_id" in src, \
            "research_world_model table CREATE must include user_id column"

    def test_table_has_composite_index_on_user_and_disease(self):
        src = self._get_init_source()
        assert "user_id, disease_name" in src or "user_disease" in src, \
            "research_world_model must have a composite index on (user_id, disease_name)"

    def test_migration_adds_user_id_to_existing_table(self):
        src = self._get_init_source()
        assert "ADD COLUMN IF NOT EXISTS user_id" in src, \
            "init_world_model_table() must add user_id to existing tables via ALTER TABLE"
