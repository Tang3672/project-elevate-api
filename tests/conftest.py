import os
import pytest

_FRONTEND_HTML = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ProjectElevate-Frontend", "app.html")
)

def pytest_runtest_setup(item):
    """Skip frontend tests when ProjectElevate-Frontend/app.html is not checked out (CI)."""
    src = getattr(item, "fspath", None)
    if src is None:
        return
    try:
        text = src.read_text(encoding="utf-8")
    except Exception:
        return
    if ("ProjectElevate-Frontend" in text or "app.html" in text) and not os.path.exists(_FRONTEND_HTML):
        pytest.skip("ProjectElevate-Frontend/app.html not available — frontend tests require local checkout")
