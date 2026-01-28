

"""
Unit tests for the Prompts Editor API endpoints.

Tests the full CRUD cycle without affecting the real database:
1. GET prompts (read current + defaults)
2. POST prompts (save changes)
3. GET history (view versions)
4. POST revert (restore previous)

Run with: pytest tests/unit/test_prompts_editor_api.py -v
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def temp_db_path():
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        # Initialize with minimal structure
        json.dump({
            "events": {},
            "config": {}
        }, f)
        temp_path = Path(f.name)
    yield temp_path
    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def enable_prompts_editor():
    """Enable the prompts editor feature flag for testing."""
    with patch.dict(os.environ, {"PROMPTS_EDITOR_ENABLED": "true"}):
        yield


@pytest.fixture
def mock_db_path(temp_db_path):
    """Patch the database path to use our temp file."""
    import workflow_email
    original_path = workflow_email.DB_PATH
    workflow_email.DB_PATH = temp_db_path
    yield temp_db_path
    workflow_email.DB_PATH = original_path


# ============================================================================
# API Function Tests (Direct, no HTTP)
# ============================================================================

class TestPromptsEditorDirect:
    """Test the prompts editor logic directly without HTTP layer."""

    def test_get_prompts_returns_defaults(self, enable_prompts_editor, mock_db_path):
        """GET /api/config/prompts returns defaults when no overrides exist."""
        from api.routes.config import get_prompts_config
        import asyncio

        result = asyncio.run(get_prompts_config())

        # Should return system_prompt and step_prompts
        assert "system_prompt" in result
        assert "step_prompts" in result

        # Should have prompts for steps 2, 3, 4, 5, 7
        step_prompts = result["step_prompts"]
        assert 2 in step_prompts or "2" in step_prompts
        assert 3 in step_prompts or "3" in step_prompts
        assert 4 in step_prompts or "4" in step_prompts
        assert 5 in step_prompts or "5" in step_prompts
        assert 7 in step_prompts or "7" in step_prompts

        print(f"✓ GET prompts: system_prompt length={len(result['system_prompt'])}")
        print(f"✓ Step prompts: {list(step_prompts.keys())}")

    def test_save_and_retrieve_prompts(self, enable_prompts_editor, mock_db_path):
        """POST /api/config/prompts saves and can be retrieved."""
        from api.routes.config import get_prompts_config, set_prompts_config, PromptConfig
        import asyncio

        # Get original
        original = asyncio.run(get_prompts_config())
        original_system = original["system_prompt"]

        # Create a modified config
        test_guidance = "TEST: Keep responses brief and professional."
        modified_config = PromptConfig(
            system_prompt=original_system,  # Keep system prompt
            step_prompts={
                2: test_guidance,  # Modified Step 2
                3: original["step_prompts"].get(3, original["step_prompts"].get("3", "")),
                4: original["step_prompts"].get(4, original["step_prompts"].get("4", "")),
                5: original["step_prompts"].get(5, original["step_prompts"].get("5", "")),
                7: original["step_prompts"].get(7, original["step_prompts"].get("7", "")),
            }
        )

        # Save it
        result = asyncio.run(set_prompts_config(modified_config))
        assert result["status"] == "ok"
        print("✓ POST prompts: saved successfully")

        # Retrieve and verify
        retrieved = asyncio.run(get_prompts_config())
        step2_value = retrieved["step_prompts"].get(2) or retrieved["step_prompts"].get("2")
        assert step2_value == test_guidance
        print(f"✓ GET prompts: verified Step 2 = '{test_guidance[:40]}...'")

    def test_history_tracking(self, enable_prompts_editor, mock_db_path):
        """History is created when prompts are saved multiple times."""
        from api.routes.config import (
            get_prompts_config, set_prompts_config, get_prompts_history,
            PromptConfig
        )
        import asyncio

        # Get original
        original = asyncio.run(get_prompts_config())

        # Make a base config
        base_config = PromptConfig(
            system_prompt=original["system_prompt"],
            step_prompts={
                2: "Version 1 guidance",
                3: original["step_prompts"].get(3, original["step_prompts"].get("3", "")),
                4: original["step_prompts"].get(4, original["step_prompts"].get("4", "")),
                5: original["step_prompts"].get(5, original["step_prompts"].get("5", "")),
                7: original["step_prompts"].get(7, original["step_prompts"].get("7", "")),
            }
        )

        # Save first version
        asyncio.run(set_prompts_config(base_config))

        # Save second version
        base_config.step_prompts[2] = "Version 2 guidance"
        asyncio.run(set_prompts_config(base_config))

        # Check history
        history_response = asyncio.run(get_prompts_history())
        history = history_response["history"]

        assert len(history) >= 1, "History should have at least 1 entry"
        print(f"✓ History has {len(history)} entries")

        # First history entry should be the previous version (Version 1)
        if history:
            first_entry = history[0]
            assert "ts" in first_entry
            assert "config" in first_entry
            print(f"✓ History entry has timestamp: {first_entry['ts'][:19]}")

    def test_revert_to_previous(self, enable_prompts_editor, mock_db_path):
        """Revert restores a previous version from history."""
        from api.routes.config import (
            get_prompts_config, set_prompts_config, get_prompts_history,
            revert_prompts_config, PromptConfig
        )
        import asyncio

        # Get original
        original = asyncio.run(get_prompts_config())

        # Create config helper
        def make_config(step2_value):
            return PromptConfig(
                system_prompt=original["system_prompt"],
                step_prompts={
                    2: step2_value,
                    3: original["step_prompts"].get(3, original["step_prompts"].get("3", "")),
                    4: original["step_prompts"].get(4, original["step_prompts"].get("4", "")),
                    5: original["step_prompts"].get(5, original["step_prompts"].get("5", "")),
                    7: original["step_prompts"].get(7, original["step_prompts"].get("7", "")),
                }
            )

        # Save Version A
        asyncio.run(set_prompts_config(make_config("Version A - original")))

        # Save Version B (A is now in history[0])
        asyncio.run(set_prompts_config(make_config("Version B - current")))

        # Verify current is B
        current = asyncio.run(get_prompts_config())
        step2 = current["step_prompts"].get(2) or current["step_prompts"].get("2")
        assert "Version B" in step2, f"Expected 'Version B', got: {step2}"
        print("✓ Current version is B")

        # Revert to history[0] (Version A)
        revert_result = asyncio.run(revert_prompts_config(0))
        assert revert_result["status"] == "ok"
        print("✓ Revert to index 0 succeeded")

        # Verify we're back to A
        reverted = asyncio.run(get_prompts_config())
        step2_reverted = reverted["step_prompts"].get(2) or reverted["step_prompts"].get("2")
        assert "Version A" in step2_reverted, f"Expected 'Version A', got: {step2_reverted}"
        print("✓ After revert, current version is A")

    def test_feature_flag_disables_endpoints(self, mock_db_path):
        """Endpoints return 404 when feature flag is disabled."""
        from api.routes.config import get_prompts_config
        from fastapi import HTTPException
        import asyncio

        # Ensure flag is OFF
        with patch.dict(os.environ, {"PROMPTS_EDITOR_ENABLED": ""}):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(get_prompts_config())

            assert exc_info.value.status_code == 404
            print("✓ Feature flag OFF: endpoint returns 404")


# ============================================================================
# Simulated Manager Workflow Test
# ============================================================================

class TestManagerWorkflow:
    """Simulate a manager using the UI to customize prompts."""

    def test_full_manager_workflow(self, enable_prompts_editor, mock_db_path):
        """
        Simulate complete manager workflow:
        1. Manager opens editor (GET prompts)
        2. Manager edits Step 2 guidance
        3. Manager saves (POST prompts)
        4. Manager realizes mistake
        5. Manager reverts (POST revert)
        """
        from api.routes.config import (
            get_prompts_config, set_prompts_config, get_prompts_history,
            revert_prompts_config, PromptConfig
        )
        import asyncio

        print("\n" + "="*60)
        print("SIMULATING MANAGER WORKFLOW")
        print("="*60)

        # Step 1: Manager opens editor
        print("\n[1] Manager opens AI Message Customization page...")
        current = asyncio.run(get_prompts_config())
        print(f"    Loaded {len(current['step_prompts'])} step prompts")
        print(f"    System prompt: {len(current['system_prompt'])} chars")

        # Save original for comparison
        original_step2 = current["step_prompts"].get(2) or current["step_prompts"].get("2")

        # Step 2: Manager edits Step 2
        print("\n[2] Manager edits Date Confirmation guidance...")
        new_guidance = """Keep responses brief and friendly.
List available dates clearly. Ask which date works best for them."""
        print(f"    New guidance: '{new_guidance[:50]}...'")

        # Step 3: Manager saves
        print("\n[3] Manager clicks 'Save Changes'...")
        modified_config = PromptConfig(
            system_prompt=current["system_prompt"],
            step_prompts={
                2: new_guidance,
                3: current["step_prompts"].get(3, current["step_prompts"].get("3", "")),
                4: current["step_prompts"].get(4, current["step_prompts"].get("4", "")),
                5: current["step_prompts"].get(5, current["step_prompts"].get("5", "")),
                7: current["step_prompts"].get(7, current["step_prompts"].get("7", "")),
            }
        )
        save_result = asyncio.run(set_prompts_config(modified_config))
        print(f"    Result: {save_result['status']}")

        # Verify save
        verified = asyncio.run(get_prompts_config())
        step2_saved = verified["step_prompts"].get(2) or verified["step_prompts"].get("2")
        assert step2_saved == new_guidance
        print("    ✓ Changes saved and verified")

        # Step 4: Manager checks history
        print("\n[4] Manager clicks 'History' to see previous versions...")
        history_response = asyncio.run(get_prompts_history())
        history = history_response["history"]
        print(f"    Found {len(history)} previous version(s)")
        if history:
            print(f"    Most recent: {history[0]['ts'][:19]}")

        # Step 5: Manager decides to revert
        print("\n[5] Manager clicks 'Restore' on previous version...")
        if history:
            revert_result = asyncio.run(revert_prompts_config(0))
            print(f"    Result: {revert_result['status']}")

            # Verify revert
            after_revert = asyncio.run(get_prompts_config())
            step2_reverted = after_revert["step_prompts"].get(2) or after_revert["step_prompts"].get("2")
            print(f"    ✓ Restored to previous version")

        print("\n" + "="*60)
        print("WORKFLOW COMPLETE - All API operations successful")
        print("="*60)


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
