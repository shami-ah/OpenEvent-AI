"""Tests for authentication middleware."""

import os
import pytest
from unittest.mock import patch

from api.middleware.auth import (
    AuthMiddleware,
    _extract_bearer_token,
    _validate_api_key,
    get_current_user_id,
    get_current_user_role,
    ALLOWLIST_PREFIXES,
    ALLOWLIST_EXACT,
)


class TestExtractBearerToken:
    """Tests for bearer token extraction."""

    def test_valid_bearer_token(self):
        assert _extract_bearer_token("Bearer abc123") == "abc123"

    def test_bearer_with_spaces(self):
        assert _extract_bearer_token("Bearer   token_with_spaces  ") == "token_with_spaces"

    def test_empty_string(self):
        assert _extract_bearer_token("") is None

    def test_none(self):
        assert _extract_bearer_token(None) is None

    def test_no_bearer_prefix(self):
        assert _extract_bearer_token("abc123") is None

    def test_lowercase_bearer(self):
        # Should not match - Bearer is case-sensitive
        assert _extract_bearer_token("bearer abc123") is None


class TestValidateApiKey:
    """Tests for API key validation."""

    def test_valid_api_key(self):
        with patch.dict(os.environ, {"API_KEY": "secret123"}):
            is_valid, error = _validate_api_key("secret123")
            assert is_valid is True
            assert error == ""

    def test_invalid_api_key(self):
        with patch.dict(os.environ, {"API_KEY": "secret123"}):
            is_valid, error = _validate_api_key("wrong_key")
            assert is_valid is False
            assert error == "invalid_token"

    def test_missing_token(self):
        with patch.dict(os.environ, {"API_KEY": "secret123"}):
            is_valid, error = _validate_api_key(None)
            assert is_valid is False
            assert error == "missing_token"

    def test_empty_token(self):
        with patch.dict(os.environ, {"API_KEY": "secret123"}):
            is_valid, error = _validate_api_key("")
            assert is_valid is False
            assert error == "missing_token"

    def test_no_api_key_configured(self):
        with patch.dict(os.environ, {"API_KEY": ""}):
            is_valid, error = _validate_api_key("any_token")
            assert is_valid is False
            assert error == "server_misconfigured"


class TestAllowlistConfig:
    """Tests for allowlist configuration."""

    def test_health_in_allowlist(self):
        assert any("/health".startswith(prefix) for prefix in ALLOWLIST_PREFIXES)

    def test_docs_in_allowlist(self):
        assert any("/docs".startswith(prefix) for prefix in ALLOWLIST_PREFIXES)

    def test_workflow_health_in_allowlist(self):
        assert any("/api/workflow/health".startswith(prefix) for prefix in ALLOWLIST_PREFIXES)

    def test_qna_in_exact_allowlist(self):
        assert "/api/qna" in ALLOWLIST_EXACT


class TestContextVars:
    """Tests for auth context variables."""

    def test_default_user_id_is_none(self):
        # In a fresh context, should return None
        assert get_current_user_id() is None

    def test_default_user_role_is_none(self):
        assert get_current_user_role() is None


# Integration tests with FastAPI TestClient
@pytest.fixture
def test_client():
    """Create test client with fresh app instance."""
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


class TestAuthMiddlewareIntegration:
    """Integration tests for auth middleware with FastAPI."""

    def test_auth_disabled_passes_through(self, test_client):
        """With AUTH_ENABLED=0, all requests should pass without auth."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "0"}):
            response = test_client.get("/api/workflow/health")
            # Should not be 401
            assert response.status_code != 401

    def test_auth_enabled_blocks_without_token(self, test_client):
        """With AUTH_ENABLED=1, requests without token should be blocked."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "1", "API_KEY": "secret123", "AUTH_MODE": "api_key"}):
            response = test_client.post(
                "/api/start-conversation",
                json={"email_body": "test", "from_email": "test@test.com"}
            )
            assert response.status_code == 401
            assert response.json()["error"] == "unauthorized"

    def test_auth_enabled_allows_with_valid_token(self, test_client):
        """With AUTH_ENABLED=1, requests with valid token should pass."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "1", "API_KEY": "secret123", "AUTH_MODE": "api_key"}):
            response = test_client.get(
                "/api/tasks/pending",
                headers={"Authorization": "Bearer secret123"}
            )
            # Should not be 401 (might be other errors, but not auth)
            assert response.status_code != 401

    def test_auth_enabled_allows_x_api_key_header(self, test_client):
        """X-Api-Key header should work as fallback."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "1", "API_KEY": "secret123", "AUTH_MODE": "api_key"}):
            response = test_client.get(
                "/api/tasks/pending",
                headers={"X-Api-Key": "secret123"}
            )
            assert response.status_code != 401

    def test_health_endpoint_always_allowed(self, test_client):
        """Health endpoint should be accessible without auth."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "1", "API_KEY": "secret123"}):
            response = test_client.get("/api/workflow/health")
            assert response.status_code != 401

    def test_docs_endpoint_always_allowed(self, test_client):
        """Docs endpoint should be accessible without auth."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "1", "API_KEY": "secret123"}):
            response = test_client.get("/docs")
            assert response.status_code != 401

    def test_invalid_auth_mode_returns_500(self, test_client):
        """Invalid AUTH_MODE should return 500."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "1", "API_KEY": "secret", "AUTH_MODE": "invalid_mode"}):
            response = test_client.get(
                "/api/tasks/pending",
                headers={"Authorization": "Bearer secret"}
            )
            assert response.status_code == 500
            assert "invalid_auth_mode" in response.json().get("detail", "")
