"""ESAE test fixtures."""

import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def tmp_esae_home():
    """Provide a temporary ESAE home directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        esae_home = Path(tmpdir) / ".hermes" / "esae"
        esae_home.mkdir(parents=True, exist_ok=True)
        yield esae_home
