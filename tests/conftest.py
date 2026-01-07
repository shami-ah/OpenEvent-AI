"""Pytest configuration for backend tests."""

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on PYTHONPATH
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Force plain verbalizer tone for deterministic test output
os.environ.setdefault("VERBALIZER_TONE", "plain")


def pytest_collection_modifyitems(items):
    """Auto-add v4 marker to all tests without explicit markers."""
    v4_marker = pytest.mark.v4
    for item in items:
        # Skip if test already has v4 or legacy marker
        if "v4" not in [m.name for m in item.iter_markers()]:
            if "legacy" not in [m.name for m in item.iter_markers()]:
                item.add_marker(v4_marker)
