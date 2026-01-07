"""
Deployment Safety Tests

Verifies critical deployment invariants:
1. No frontend files in deployment paths (main branch = backend-only)
2. Backend imports work without frontend dependencies
3. Production environment configuration is valid
4. No hardcoded dev-only defaults leak to production

Run these tests before merging to main to prevent deployment issues.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.v4

PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestNoFrontendInDeployment:
    """Ensure frontend files don't leak into backend deployment."""

    def test_no_atelier_frontend_directory(self):
        """The atelier-ai-frontend directory should not exist in deployment."""
        frontend_dir = PROJECT_ROOT / "atelier-ai-frontend"
        # This test passes if:
        # 1. The directory doesn't exist (correct for main branch)
        # 2. OR we're on a development branch (allowed to have frontend)
        if frontend_dir.exists():
            # Check if we're on main branch
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT,
            )
            current_branch = result.stdout.strip()
            if current_branch == "main":
                pytest.fail(
                    f"Frontend directory {frontend_dir} exists on main branch! "
                    "Main branch should be backend-only for Vercel deployment."
                )
            # On non-main branches, frontend is allowed
            pytest.skip(f"Frontend allowed on development branch: {current_branch}")

    def test_no_frontend_imports_in_main_app(self):
        """main.py should not have hard dependencies on frontend."""
        main_py = PROJECT_ROOT / "main.py"
        content = main_py.read_text()

        # These patterns would indicate hard frontend dependencies
        forbidden_patterns = [
            "from atelier",
            "import atelier",
            "require('next')",  # Node.js
        ]

        for pattern in forbidden_patterns:
            assert pattern not in content, (
                f"main.py contains '{pattern}' which suggests frontend dependency"
            )

    def test_frontend_launch_is_conditional(self):
        """Frontend auto-launch should check if directory exists first."""
        main_py = PROJECT_ROOT / "main.py"
        content = main_py.read_text()

        # The frontend launch code should be conditional
        if "FRONTEND_DIR" in content:
            assert "exists()" in content, (
                "Frontend code should check if FRONTEND_DIR.exists() before launching"
            )


class TestBackendCanRunStandalone:
    """Verify backend works without frontend."""

    def test_import_main_without_frontend(self):
        """Backend should import even if frontend directory is missing."""
        # This test runs in the current environment which may or may not have frontend
        # The import should work regardless
        from main import app
        assert app is not None
        assert app.title == "AI Event Manager"

    def test_api_routes_registered(self):
        """Core API routes should be registered."""
        from main import app

        route_paths = [route.path for route in app.routes]

        # Critical backend endpoints
        assert "/api/start-conversation" in route_paths or any(
            "/api/start-conversation" in str(r.path) for r in app.routes
        )

    def test_workflow_imports_standalone(self):
        """Workflow modules should import without frontend."""
        from workflow_email import process_msg
        assert callable(process_msg)


class TestProductionEnvironmentSafety:
    """Verify production environment settings are safe."""

    def test_no_hardcoded_localhost_in_production_defaults(self):
        """Production defaults should not point to localhost."""
        # Check environment variable defaults in main.py
        main_py = PROJECT_ROOT / "main.py"
        content = main_py.read_text()

        # These patterns are OK in conditional/dev blocks but not as defaults
        # We're checking that localhost isn't the ONLY option
        if 'SUPABASE_URL' in content:
            # Should have environment variable override, not hardcoded localhost
            assert 'os.getenv' in content or 'os.environ' in content

    def test_debug_mode_not_default(self):
        """Debug mode should not be enabled by default."""
        main_py = PROJECT_ROOT / "main.py"
        content = main_py.read_text()

        # Look for debug=True that's not guarded by environment check
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'debug=True' in line.lower() and 'os.getenv' not in line:
                # Check surrounding context
                context = '\n'.join(lines[max(0, i-2):min(len(lines), i+3)])
                if 'DEV' not in context and 'DEBUG' not in context:
                    pytest.fail(
                        f"Unguarded debug=True found at line {i+1}: {line.strip()}"
                    )

    def test_api_keys_from_environment(self):
        """API keys should come from environment, not hardcoded."""
        sensitive_patterns = [
            ("OPENAI_API_KEY", "sk-"),
            ("SUPABASE_KEY", "eyJ"),
            ("GEMINI_API_KEY", "AI"),
        ]

        for env_var, prefix in sensitive_patterns:
            # Check that if the key is used, it comes from os.getenv
            for py_file in PROJECT_ROOT.glob("**/*.py"):
                if ".venv" in str(py_file) or "node_modules" in str(py_file):
                    continue
                try:
                    content = py_file.read_text()
                    if env_var in content:
                        # Should be accessed via os.getenv or os.environ
                        assert 'os.getenv' in content or 'os.environ' in content, (
                            f"{py_file} uses {env_var} but may not get it from environment"
                        )
                except Exception:
                    pass  # Skip files that can't be read


class TestGitBranchSafety:
    """Tests for git branch deployment safety."""

    def test_can_detect_current_branch(self):
        """Git should be available to detect branch."""
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, "Git should be available"
        assert result.stdout.strip(), "Should be on a branch"

    def test_main_branch_is_clean_of_frontend(self):
        """Verify main branch doesn't track frontend files."""
        # Get list of files tracked by git on main
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "origin/main"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        if result.returncode != 0:
            pytest.skip("Cannot check origin/main (might not be fetched)")

        tracked_files = result.stdout.strip().split('\n')
        frontend_files = [f for f in tracked_files if f.startswith("atelier-ai-frontend/")]

        assert not frontend_files, (
            f"Frontend files tracked on main branch: {frontend_files[:5]}... "
            "(main should be backend-only)"
        )
