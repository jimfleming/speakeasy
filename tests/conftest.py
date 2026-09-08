"""Point config at a throwaway file before speakeasy.config is imported, so
tests never read or write the developer's real config.json."""
import importlib
import os
import tempfile

import pytest

os.environ["SPEAKEASY_CONFIG"] = os.path.join(
    tempfile.mkdtemp(prefix="speakeasy_tests_"), "config.json")


@pytest.fixture(autouse=True)
def restore_config():
    """Reload speakeasy.config back to defaults after any test that reloaded
    it, so module-level globals do not leak between tests."""
    yield
    import speakeasy.config
    importlib.reload(speakeasy.config)
