"""Tests for tenant context middleware."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from api.middleware.tenant_context import (
    CURRENT_TEAM_ID,
    CURRENT_MANAGER_ID,
    get_request_team_id,
    get_request_manager_id,
)


class TestTenantContextMiddleware:
    """Test tenant header extraction."""

    def test_headers_ignored_when_disabled(self):
        """Headers should be ignored when TENANT_HEADER_ENABLED != 1."""
        with patch.dict(os.environ, {"TENANT_HEADER_ENABLED": "0"}, clear=False):
            client = TestClient(app)
            response = client.get(
                "/",
                headers={"X-Team-Id": "test-team", "X-Manager-Id": "test-manager"},
            )
            assert response.status_code == 200

    def test_headers_parsed_when_enabled(self):
        """Headers should be parsed when TENANT_HEADER_ENABLED=1."""
        with patch.dict(os.environ, {"TENANT_HEADER_ENABLED": "1"}, clear=False):
            client = TestClient(app)
            response = client.get(
                "/",
                headers={"X-Team-Id": "team-123", "X-Manager-Id": "manager-456"},
            )
            assert response.status_code == 200

    def test_no_headers_still_works(self):
        """Requests without tenant headers should work normally."""
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200

    def test_partial_headers_work(self):
        """Only X-Team-Id without X-Manager-Id should work."""
        with patch.dict(os.environ, {"TENANT_HEADER_ENABLED": "1"}, clear=False):
            client = TestClient(app)
            response = client.get(
                "/",
                headers={"X-Team-Id": "team-only"},
            )
            assert response.status_code == 200


class TestContextvarHelpers:
    """Test contextvar helper functions."""

    def test_get_request_team_id_returns_none_by_default(self):
        """Helper should return None when no context is set."""
        # Reset contextvar to default
        CURRENT_TEAM_ID.set(None)
        assert get_request_team_id() is None

    def test_get_request_manager_id_returns_none_by_default(self):
        """Helper should return None when no context is set."""
        CURRENT_MANAGER_ID.set(None)
        assert get_request_manager_id() is None

    def test_contextvars_can_be_set_and_read(self):
        """Verify contextvars work as expected."""
        CURRENT_TEAM_ID.set("test-team-id")
        CURRENT_MANAGER_ID.set("test-manager-id")

        assert get_request_team_id() == "test-team-id"
        assert get_request_manager_id() == "test-manager-id"

        # Clean up
        CURRENT_TEAM_ID.set(None)
        CURRENT_MANAGER_ID.set(None)


class TestConfigIntegration:
    """Test that config.py respects contextvar (Phase 2A)."""

    def test_get_team_id_uses_contextvar_when_set(self):
        """get_team_id() should return contextvar value when set."""
        from workflows.io.integration.config import get_team_id

        # Set contextvar
        CURRENT_TEAM_ID.set("test-team-from-header")
        try:
            result = get_team_id()
            assert result == "test-team-from-header"
        finally:
            CURRENT_TEAM_ID.set(None)

    def test_get_team_id_falls_back_to_env_when_contextvar_none(self):
        """get_team_id() should fall back to env var when contextvar is None."""
        from workflows.io.integration.config import (
            get_team_id,
            INTEGRATION_CONFIG,
        )

        CURRENT_TEAM_ID.set(None)
        result = get_team_id()
        # Should return env var value (or None if not set)
        assert result == INTEGRATION_CONFIG.team_id

    def test_get_system_user_id_uses_contextvar_when_set(self):
        """get_system_user_id() should return contextvar value when set."""
        from workflows.io.integration.config import get_system_user_id

        CURRENT_MANAGER_ID.set("test-manager-from-header")
        try:
            result = get_system_user_id()
            assert result == "test-manager-from-header"
        finally:
            CURRENT_MANAGER_ID.set(None)

    def test_get_system_user_id_falls_back_to_env_when_contextvar_none(self):
        """get_system_user_id() should fall back to env var when contextvar is None."""
        from workflows.io.integration.config import (
            get_system_user_id,
            INTEGRATION_CONFIG,
        )

        CURRENT_MANAGER_ID.set(None)
        result = get_system_user_id()
        # Should return env var value (or None if not set)
        assert result == INTEGRATION_CONFIG.system_user_id

    def test_contextvar_takes_priority_over_env_var(self):
        """Contextvar should take priority even when env var is set."""
        from workflows.io.integration.config import get_team_id

        # Even if env var has a value, contextvar should win
        CURRENT_TEAM_ID.set("header-team-id")
        try:
            result = get_team_id()
            assert result == "header-team-id"
        finally:
            CURRENT_TEAM_ID.set(None)


class TestJSONDBRouting:
    """Test that JSON adapter routes to per-team files (Phase 2B)."""

    def test_adapter_uses_default_path_when_no_team_id(self):
        """Adapter should use default path when team_id is None."""
        from workflows.io.integration.adapter import JSONDatabaseAdapter

        CURRENT_TEAM_ID.set(None)
        adapter = JSONDatabaseAdapter()
        adapter.initialize()

        resolved = adapter._resolve_db_path()
        assert resolved.name == "events_database.json"

    def test_adapter_uses_team_path_when_team_id_set(self):
        """Adapter should use per-team path when team_id is set."""
        from workflows.io.integration.adapter import JSONDatabaseAdapter

        CURRENT_TEAM_ID.set("test-team-123")
        try:
            adapter = JSONDatabaseAdapter()
            adapter.initialize()

            resolved = adapter._resolve_db_path()
            assert resolved.name == "events_test-team-123.json"
        finally:
            CURRENT_TEAM_ID.set(None)

    def test_adapter_path_changes_with_contextvar(self):
        """Path should change dynamically as contextvar changes."""
        from workflows.io.integration.adapter import JSONDatabaseAdapter

        adapter = JSONDatabaseAdapter()
        adapter.initialize()

        # No team - default path
        CURRENT_TEAM_ID.set(None)
        assert adapter._resolve_db_path().name == "events_database.json"

        # Team A
        CURRENT_TEAM_ID.set("team-a")
        assert adapter._resolve_db_path().name == "events_team-a.json"

        # Team B
        CURRENT_TEAM_ID.set("team-b")
        assert adapter._resolve_db_path().name == "events_team-b.json"

        # Clean up
        CURRENT_TEAM_ID.set(None)

    def test_same_adapter_instance_different_paths(self):
        """Same adapter instance should resolve different paths per team."""
        from workflows.io.integration.adapter import JSONDatabaseAdapter

        adapter = JSONDatabaseAdapter()
        adapter.initialize()

        # Simulate request for Team A
        CURRENT_TEAM_ID.set("venue-alpha")
        path_a = adapter._resolve_db_path()

        # Simulate request for Team B (same adapter instance)
        CURRENT_TEAM_ID.set("venue-beta")
        path_b = adapter._resolve_db_path()

        # Paths should be different
        assert path_a.name == "events_venue-alpha.json"
        assert path_b.name == "events_venue-beta.json"
        assert path_a != path_b

        # Clean up
        CURRENT_TEAM_ID.set(None)
