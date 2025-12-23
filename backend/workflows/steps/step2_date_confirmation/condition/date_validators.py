"""Condition helpers for the date confirmation workflow group."""

from __future__ import annotations

from backend.workflows.conditions.checks import is_valid_ddmmyyyy as _is_valid_ddmmyyyy

__workflow_role__ = "condition"

is_valid_ddmmyyyy = _is_valid_ddmmyyyy
is_valid_ddmmyyyy.__doc__ = """[Condition] Validate that a string follows the DD.MM.YYYY format."""
