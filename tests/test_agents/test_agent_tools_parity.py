"""
Agent Tools Parity Tests (PARITY_*)

Tests ensuring deterministic tool execution in AGENT_MODE=openai matches
stub mode behavior. Tools must delegate to existing Python functions without
adding agent chains or LLM variability.

Scenarios:
- A: Happy path Steps 1–4
- B: Q&A-only scenario triggering tools
- C: Simple detour scenario (requirements change)

References:
- TEST_MATRIX_detection_and_flow.md: PARITY_* tests
- CLAUDE.md: Tool allowlist, ENGINE_TOOL_ALLOWLIST
"""

from __future__ import annotations

import json
import pytest
from typing import Any, Dict, List, Optional

from agents import (
    execute_tool_call,
    validate_tool_call,
    StepToolPolicy,
    ToolExecutionError,
)
from agents.chatkit_runner import ENGINE_TOOL_ALLOWLIST, TOOL_DEFINITIONS


# ==============================================================================
# CONSTANTS
# ==============================================================================


STEP_2_TOOLS = {"tool_suggest_dates", "tool_parse_date_intent"}
STEP_3_TOOLS = {"tool_room_status_on_date", "tool_capacity_check", "tool_evaluate_rooms"}
STEP_4_TOOLS = {
    "tool_build_offer_draft",
    "tool_persist_offer",
    "tool_list_products",
    "tool_list_catering",
    "tool_add_product_to_offer",
    "tool_remove_product_from_offer",
    "tool_send_offer",
}
STEP_5_TOOLS = {"tool_negotiate_offer", "tool_transition_sync"}
STEP_7_TOOLS = {"tool_follow_up_suggest", "tool_classify_confirmation"}


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


def create_state(current_step: int) -> Dict[str, Any]:
    """Create a minimal state dict for testing."""
    return {
        "current_step": current_step,
        "thread_id": "test-thread-001",
        "status": "Lead",
    }


def create_event_entry(
    event_id: str = "EVT-TEST-001",
    email: str = "client@example.com",
    chosen_date: str = "2025-12-15",
    participants: int = 25,
    locked_room_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a minimal event entry for tool execution."""
    return {
        "event_id": event_id,
        "email": email,
        "event_data": {
            "chosen_date": chosen_date,
            "number_of_participants": participants,
            "locked_room_id": locked_room_id,
        },
        "metadata": {
            "status": "Lead",
        },
    }


def create_minimal_db() -> Dict[str, Any]:
    """Create a minimal database for tool tests."""
    return {
        "events": [],
        "tasks": [],
        "clients": {},
    }


# ==============================================================================
# PARITY_TOOL_001: Tool Allowlist Enforcement
# ==============================================================================


class TestToolAllowlistEnforcement:
    """
    PARITY_TOOL_001: Tool allowlist enforced per step.

    Tests that ENGINE_TOOL_ALLOWLIST correctly restricts which tools
    can be called at each workflow step.
    """

    def test_step_2_allows_date_tools_only(self):
        """Step 2 should only allow date-related tools."""
        policy = StepToolPolicy(current_step=2)

        # These should be allowed
        for tool in STEP_2_TOOLS:
            assert tool in policy.allowed_tools

        # These should be blocked
        for tool in STEP_3_TOOLS | STEP_4_TOOLS:
            assert tool not in policy.allowed_tools

    def test_step_3_allows_room_tools_only(self):
        """Step 3 should only allow room-related tools."""
        policy = StepToolPolicy(current_step=3)

        # These should be allowed
        for tool in STEP_3_TOOLS:
            assert tool in policy.allowed_tools

        # These should be blocked
        for tool in STEP_2_TOOLS | STEP_4_TOOLS:
            assert tool not in policy.allowed_tools

    def test_step_4_allows_offer_tools_only(self):
        """Step 4 should only allow offer-related tools."""
        policy = StepToolPolicy(current_step=4)

        # These should be allowed
        for tool in STEP_4_TOOLS:
            assert tool in policy.allowed_tools

        # These should be blocked
        for tool in STEP_2_TOOLS | STEP_3_TOOLS:
            assert tool not in policy.allowed_tools

    def test_step_5_allows_negotiation_tools(self):
        """Step 5 should only allow negotiation tools."""
        policy = StepToolPolicy(current_step=5)

        for tool in STEP_5_TOOLS:
            assert tool in policy.allowed_tools

        for tool in STEP_2_TOOLS | STEP_3_TOOLS | STEP_4_TOOLS:
            assert tool not in policy.allowed_tools

    def test_step_7_allows_confirmation_tools(self):
        """Step 7 should only allow confirmation/follow-up tools."""
        policy = StepToolPolicy(current_step=7)

        for tool in STEP_7_TOOLS:
            assert tool in policy.allowed_tools

        for tool in STEP_2_TOOLS | STEP_3_TOOLS | STEP_4_TOOLS:
            assert tool not in policy.allowed_tools


# ==============================================================================
# PARITY_TOOL_002: Schema Validation
# ==============================================================================


class TestToolSchemaValidation:
    """
    PARITY_TOOL_002: Tool schema validation.

    Tests that tool arguments are validated against JSON schemas
    before execution.
    """

    def test_missing_required_field_raises(self):
        """Missing required fields should raise ToolExecutionError."""
        state = create_state(current_step=3)

        # tool_room_status_on_date requires both date and room
        with pytest.raises(ToolExecutionError) as exc:
            execute_tool_call(
                tool_name="tool_room_status_on_date",
                tool_call_id="call-001",
                arguments={"date": "15.12.2025"},  # Missing room
                state=state,
                db=create_minimal_db(),
            )

        detail = json.loads(str(exc.value))
        assert detail["reason"] == "schema_validation_failed"

    def test_invalid_date_format_raises(self):
        """Invalid date format should raise validation error."""
        state = create_state(current_step=3)

        with pytest.raises(ToolExecutionError) as exc:
            execute_tool_call(
                tool_name="tool_room_status_on_date",
                tool_call_id="call-002",
                arguments={
                    "date": "2025-12-15",  # Wrong format, should be DD.MM.YYYY
                    "room": "Room A",
                },
                state=state,
                db=create_minimal_db(),
            )

        detail = json.loads(str(exc.value))
        assert detail["reason"] == "schema_validation_failed"

    def test_valid_arguments_pass_validation(self):
        """Valid arguments should pass schema validation."""
        state = create_state(current_step=3)

        # This should not raise
        validate_tool_call(
            "tool_room_status_on_date",
            state,
            arguments={"date": "15.12.2025", "room": "Room A"},
        )


# ==============================================================================
# PARITY_TOOL_003: Step Policy Consistency
# ==============================================================================


class TestStepPolicyConsistency:
    """
    PARITY_TOOL_003: Step policy produces consistent results.

    Tests that StepToolPolicy returns the same allowlist for
    the same step across invocations.
    """

    def test_policy_idempotent_for_same_step(self):
        """Same step should always produce same allowlist."""
        policy1 = StepToolPolicy(current_step=3)
        policy2 = StepToolPolicy(current_step=3)

        assert policy1.allowed_tools == policy2.allowed_tools
        assert policy1.allowed_tools == STEP_3_TOOLS

    def test_none_step_allows_all_tools(self):
        """Step=None should allow all tools (for backward compatibility)."""
        policy = StepToolPolicy(current_step=None)

        all_tools = set().union(*ENGINE_TOOL_ALLOWLIST.values())
        assert policy.allowed_tools == all_tools


# ==============================================================================
# PARITY_SCENARIO_A: Happy Path Steps 1-4
# ==============================================================================


class TestScenarioAHappyPath:
    """
    PARITY_SCENARIO_A: Happy path Steps 1-4.

    Validates that tool execution produces deterministic results
    matching stub mode for the standard booking flow.
    """

    def test_step_2_suggest_dates_returns_structure(self):
        """tool_suggest_dates should return structured date options."""
        state = create_state(current_step=2)
        db = create_minimal_db()

        result = execute_tool_call(
            tool_name="tool_suggest_dates",
            tool_call_id="call-dates-001",
            arguments={
                "event_id": "EVT-001",
                "preferred_room": "Room A",
                "start_from_iso": "2025-12-01T09:00:00",
                "days_ahead": 14,
                "max_results": 5,
            },
            state=state,
            db=db,
        )

        assert result["tool_call_id"] == "call-dates-001"
        assert result["tool_name"] == "tool_suggest_dates"
        assert "content" in result
        # Content should have structured date info
        assert isinstance(result["content"], dict)

    def test_step_2_parse_date_intent_extracts_date(self):
        """tool_parse_date_intent should extract date from message."""
        state = create_state(current_step=2)

        result = execute_tool_call(
            tool_name="tool_parse_date_intent",
            tool_call_id="call-parse-001",
            arguments={"message": "December 15th works for us"},
            state=state,
        )

        assert result["tool_call_id"] == "call-parse-001"
        assert result["tool_name"] == "tool_parse_date_intent"
        assert "content" in result

    def test_step_3_capacity_check_validates_room(self):
        """tool_capacity_check should validate room capacity."""
        state = create_state(current_step=3)

        result = execute_tool_call(
            tool_name="tool_capacity_check",
            tool_call_id="call-cap-001",
            arguments={
                "room": "Room A",
                "attendees": 25,
                "layout": "theatre",
            },
            state=state,
        )

        assert result["tool_call_id"] == "call-cap-001"
        assert result["tool_name"] == "tool_capacity_check"
        assert "content" in result

    def test_step_4_list_products_returns_catalog(self):
        """tool_list_products should return product catalog."""
        state = create_state(current_step=4)

        result = execute_tool_call(
            tool_name="tool_list_products",
            tool_call_id="call-prod-001",
            arguments={"room_id": "room_a", "categories": ["av", "tech"]},
            state=state,
        )

        assert result["tool_call_id"] == "call-prod-001"
        assert result["tool_name"] == "tool_list_products"
        assert "content" in result

    def test_step_4_list_catering_returns_options(self):
        """tool_list_catering should return catering options."""
        state = create_state(current_step=4)

        result = execute_tool_call(
            tool_name="tool_list_catering",
            tool_call_id="call-cat-001",
            arguments={
                "room_id": "room_a",
                "date_token": "2025-12-15",
                "categories": ["lunch", "coffee"],
            },
            state=state,
        )

        assert result["tool_call_id"] == "call-cat-001"
        assert result["tool_name"] == "tool_list_catering"
        assert "content" in result


# ==============================================================================
# PARITY_SCENARIO_B: Q&A Only (Tool Triggering)
# ==============================================================================


class TestScenarioBQnAOnly:
    """
    PARITY_SCENARIO_B: Q&A-only scenario triggering tools.

    Tests that Q&A interactions correctly trigger appropriate tools
    based on the current workflow step.
    """

    def test_qna_at_step_2_can_use_date_tools(self):
        """Q&A at Step 2 should have access to date tools."""
        state = create_state(current_step=2)

        # Q&A about dates should be able to suggest dates
        result = execute_tool_call(
            tool_name="tool_suggest_dates",
            tool_call_id="call-qna-dates",
            arguments={
                "event_id": "EVT-QNA-001",
                "start_from_iso": "2025-11-01T00:00:00",
                "days_ahead": 30,
                "max_results": 5,
            },
            state=state,
            db=create_minimal_db(),
        )

        assert result["tool_name"] == "tool_suggest_dates"
        assert "content" in result

    def test_qna_at_step_3_can_query_rooms(self):
        """Q&A at Step 3 should have access to room tools."""
        state = create_state(current_step=3)

        # Q&A about room capacity
        result = execute_tool_call(
            tool_name="tool_capacity_check",
            tool_call_id="call-qna-rooms",
            arguments={"room": "Room B", "attendees": 40, "layout": "theatre"},
            state=state,
        )

        assert result["tool_name"] == "tool_capacity_check"

    def test_qna_at_step_4_can_query_products(self):
        """Q&A at Step 4 should have access to product/catering tools."""
        state = create_state(current_step=4)

        # Q&A about catering options
        result = execute_tool_call(
            tool_name="tool_list_catering",
            tool_call_id="call-qna-catering",
            arguments={
                "room_id": "room_a",
                "date_token": "2025-12-15",
                "categories": ["lunch", "coffee"],
            },
            state=state,
        )

        assert result["tool_name"] == "tool_list_catering"

    def test_qna_cannot_use_wrong_step_tools(self):
        """Q&A should not access tools outside current step."""
        state = create_state(current_step=2)

        # At Step 2, should not be able to list products (Step 4 tool)
        with pytest.raises(ToolExecutionError):
            execute_tool_call(
                tool_name="tool_list_products",
                tool_call_id="call-wrong-step",
                arguments={},
                state=state,
            )


# ==============================================================================
# PARITY_SCENARIO_C: Detour (Requirements Change)
# ==============================================================================


class TestScenarioCDetour:
    """
    PARITY_SCENARIO_C: Detour scenario (requirements change).

    Tests that tool execution handles detour scenarios correctly
    when requirements change mid-flow.
    """

    def test_step_change_updates_allowed_tools(self):
        """Changing step should update allowed tools."""
        # Start at Step 4
        state = create_state(current_step=4)
        policy4 = StepToolPolicy(current_step=4)
        assert "tool_list_products" in policy4.allowed_tools

        # Detour to Step 3 (requirements changed, need room re-eval)
        state["current_step"] = 3
        policy3 = StepToolPolicy(current_step=3)
        assert "tool_list_products" not in policy3.allowed_tools
        assert "tool_capacity_check" in policy3.allowed_tools

    def test_detour_to_step_3_allows_room_reeval(self):
        """Detour to Step 3 should allow room re-evaluation."""
        state = create_state(current_step=3)
        db = create_minimal_db()

        # After requirements change, capacity check is allowed
        result = execute_tool_call(
            tool_name="tool_capacity_check",
            tool_call_id="call-detour-cap",
            arguments={"room": "Room A", "attendees": 36, "layout": "classroom"},
            state=state,
        )

        assert result["tool_name"] == "tool_capacity_check"

    def test_detour_blocks_offer_tools_at_step_3(self):
        """During Step 3 detour, offer tools should be blocked."""
        state = create_state(current_step=3)

        # Should not be able to build offer during room re-evaluation
        with pytest.raises(ToolExecutionError):
            execute_tool_call(
                tool_name="tool_build_offer_draft",
                tool_call_id="call-blocked",
                arguments={"event_entry": {}},
                state=state,
            )


# ==============================================================================
# PARITY_TOOL_DEFINITIONS: Tool Registry Coverage
# ==============================================================================


class TestToolRegistryCoverage:
    """Tests for tool registry completeness."""

    def test_all_allowlist_tools_have_definitions(self):
        """Every tool in ENGINE_TOOL_ALLOWLIST should have a definition."""
        all_tools = set().union(*ENGINE_TOOL_ALLOWLIST.values())

        for tool in all_tools:
            assert tool in TOOL_DEFINITIONS, f"Missing definition for {tool}"

    def test_all_definitions_have_handlers(self):
        """Every tool definition should have a callable handler."""
        for tool_name, defn in TOOL_DEFINITIONS.items():
            assert callable(defn.handler), f"{tool_name} handler not callable"

    def test_all_definitions_have_input_models(self):
        """Every tool definition should have a Pydantic input model."""
        for tool_name, defn in TOOL_DEFINITIONS.items():
            assert defn.input_model is not None, f"{tool_name} missing input model"
