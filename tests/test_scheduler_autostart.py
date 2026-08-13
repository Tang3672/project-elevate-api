"""Tests for automatic scheduler activation on Railway.

Root cause: ENABLE_SCHEDULER defaults to False in config.py, so the ingestion
pipeline never ran on Railway and demand_signals stayed frozen at 12,788.

Fix: get_settings() now auto-sets ENABLE_SCHEDULER=True when RAILWAY_ENVIRONMENT
is present in the environment (Railway sets this automatically on every deploy).
Explicit ENABLE_SCHEDULER=false in env still wins because pydantic reads it first.
"""
from __future__ import annotations

import os
from unittest.mock import patch


class TestSchedulerAutoStart:
    """
    Tests for _ON_RAILWAY detection logic in config.py.

    Strategy: test _ON_RAILWAY directly via the module-level computation rather than
    through get_settings(), because the local .env file has ENABLE_SCHEDULER=false
    which correctly overrides the field default in dev — so testing through Settings()
    would always return False locally. On Railway there is no .env file, so the field
    default (_ON_RAILWAY=True) is used.
    """

    def test_no_railway_vars_means_off_railway(self):
        """Without Railway env vars, _ON_RAILWAY is False (local dev)."""
        with patch.dict(os.environ, {}, clear=False):
            env_backup_d = os.environ.pop("RAILWAY_DEPLOYMENT_ID", None)
            env_backup_e = os.environ.pop("RAILWAY_ENVIRONMENT", None)
            try:
                import app.core.config as cfg_mod
                from importlib import reload
                reload(cfg_mod)
                assert not cfg_mod._ON_RAILWAY, (
                    "_ON_RAILWAY must be False when no Railway env vars are set"
                )
            finally:
                if env_backup_d is not None:
                    os.environ["RAILWAY_DEPLOYMENT_ID"] = env_backup_d
                if env_backup_e is not None:
                    os.environ["RAILWAY_ENVIRONMENT"] = env_backup_e

    def test_railway_deployment_id_sets_on_railway_true(self):
        """RAILWAY_DEPLOYMENT_ID present → _ON_RAILWAY is True."""
        with patch.dict(os.environ, {"RAILWAY_DEPLOYMENT_ID": "abc-uuid-123"}):
            from importlib import reload
            import app.core.config as cfg_mod
            reload(cfg_mod)
            assert cfg_mod._ON_RAILWAY, (
                "_ON_RAILWAY must be True when RAILWAY_DEPLOYMENT_ID is set; "
                "this is the field default that makes ENABLE_SCHEDULER True on Railway "
                "when no .env file is present"
            )

    def test_railway_environment_sets_on_railway_true(self):
        """RAILWAY_ENVIRONMENT present → _ON_RAILWAY is True (fallback signal)."""
        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT": "production"}):
            from importlib import reload
            import app.core.config as cfg_mod
            reload(cfg_mod)
            assert cfg_mod._ON_RAILWAY

    def test_on_railway_is_field_default_for_enable_scheduler(self):
        """_ON_RAILWAY is wired as the default value for ENABLE_SCHEDULER field."""
        import inspect
        import app.core.config as cfg_mod
        src = inspect.getsource(cfg_mod)
        assert "ENABLE_SCHEDULER: bool = _ON_RAILWAY" in src, (
            "ENABLE_SCHEDULER field default must be _ON_RAILWAY so Railway gets True "
            "automatically (no .env file there) and local dev gets False (from .env)"
        )

    def test_env_var_enable_scheduler_true_still_works(self):
        """ENABLE_SCHEDULER=true env var always wins regardless of _ON_RAILWAY."""
        with patch.dict(os.environ, {"ENABLE_SCHEDULER": "true"}, clear=False):
            from importlib import reload
            import app.core.config as cfg_mod
            reload(cfg_mod)
            s = cfg_mod.get_settings()
            assert s.ENABLE_SCHEDULER

    def test_local_dotenv_false_is_correct_local_behavior(self):
        """
        The local .env has ENABLE_SCHEDULER=false — this is intentional.
        On Railway there is no .env file so the field default (_ON_RAILWAY=True) wins.
        This test documents that contract.
        """
        # Confirm .env file exists and has the right value
        import pathlib
        dotenv = pathlib.Path(__file__).parent.parent / ".env"
        if dotenv.exists():
            content = dotenv.read_text()
            assert "ENABLE_SCHEDULER=false" in content.lower() or "enable_scheduler=false" in content.lower(), (
                "Local .env should keep ENABLE_SCHEDULER=false so the scheduler "
                "doesn't start automatically in local dev"
            )


class TestSignalIngestionEndpoints:
    """Verify the new /etl/signals endpoints are wired up correctly."""

    def test_signal_ingestion_status_route_registered(self):
        from app.api.etl import router
        paths = [r.path for r in router.routes]
        assert "/signals" in paths, (
            "GET /etl/signals must exist so operators can check signal ingestion health"
        )

    def test_signal_pipeline_trigger_route_registered(self):
        from app.api.etl import router
        paths = [r.path for r in router.routes]
        assert "/signals/run" in paths, (
            "POST /etl/signals/run must exist for manual pipeline triggers"
        )

    def test_get_signal_counts_by_source_callable(self):
        from app.db.demand_repository import get_signal_counts_by_source
        import inspect
        assert inspect.iscoroutinefunction(get_signal_counts_by_source)

    def test_health_endpoint_has_signals_key(self):
        """Verify health endpoint code includes signal stats block."""
        import inspect
        import app.main as main_mod
        src = inspect.getsource(main_mod.health_check)
        assert "total_signals" in src, (
            "health_check must include total_signals so Railway health checks "
            "surface ingestion staleness without a separate monitoring tool"
        )
        assert "last_ingested_at" in src
