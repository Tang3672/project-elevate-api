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

    def test_enable_scheduler_false_by_default(self):
        """Baseline: without any env vars, scheduler is disabled."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("ENABLE_SCHEDULER", "RAILWAY_ENVIRONMENT")}
        with patch.dict(os.environ, env, clear=True):
            from importlib import reload
            import app.core.config as cfg_mod
            reload(cfg_mod)
            s = cfg_mod.get_settings()
            assert not s.ENABLE_SCHEDULER, (
                "ENABLE_SCHEDULER must default to False in local dev "
                "so the scheduler does not start without a DB connection"
            )

    def test_railway_environment_enables_scheduler(self):
        """RAILWAY_ENVIRONMENT present → get_settings() enables the scheduler."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("ENABLE_SCHEDULER", "RAILWAY_ENVIRONMENT")}
        env["RAILWAY_ENVIRONMENT"] = "production"
        with patch.dict(os.environ, env, clear=True):
            from importlib import reload
            import app.core.config as cfg_mod
            reload(cfg_mod)
            s = cfg_mod.get_settings()
            assert s.ENABLE_SCHEDULER, (
                "ENABLE_SCHEDULER must be True when RAILWAY_ENVIRONMENT is set; "
                "the scheduler was never starting on Railway because it was False"
            )

    def test_explicit_false_beats_railway_env(self):
        """ENABLE_SCHEDULER=false in env overrides Railway auto-detect."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("ENABLE_SCHEDULER", "RAILWAY_ENVIRONMENT")}
        env["RAILWAY_ENVIRONMENT"] = "production"
        env["ENABLE_SCHEDULER"] = "false"
        with patch.dict(os.environ, env, clear=True):
            from importlib import reload
            import app.core.config as cfg_mod
            reload(cfg_mod)
            s = cfg_mod.get_settings()
            assert not s.ENABLE_SCHEDULER, (
                "Explicit ENABLE_SCHEDULER=false must override Railway auto-detect, "
                "so operators can disable the scheduler for maintenance windows"
            )

    def test_railway_staging_also_enables_scheduler(self):
        """Any non-empty RAILWAY_ENVIRONMENT value (staging, production) enables it."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("ENABLE_SCHEDULER", "RAILWAY_ENVIRONMENT")}
        env["RAILWAY_ENVIRONMENT"] = "staging"
        with patch.dict(os.environ, env, clear=True):
            from importlib import reload
            import app.core.config as cfg_mod
            reload(cfg_mod)
            s = cfg_mod.get_settings()
            assert s.ENABLE_SCHEDULER

    def test_explicit_true_works_without_railway(self):
        """ENABLE_SCHEDULER=true in env works without RAILWAY_ENVIRONMENT."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("ENABLE_SCHEDULER", "RAILWAY_ENVIRONMENT")}
        env["ENABLE_SCHEDULER"] = "true"
        with patch.dict(os.environ, env, clear=True):
            from importlib import reload
            import app.core.config as cfg_mod
            reload(cfg_mod)
            s = cfg_mod.get_settings()
            assert s.ENABLE_SCHEDULER


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
