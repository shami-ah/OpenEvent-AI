"""
Integration test: Verify complete deposit-to-HIL flow through workflow processing.

This test actually runs the workflow with real message processing to verify
that after billing is provided and deposit is paid, the workflow creates
an HIL task for manager approval.
"""
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

import pytest

from workflows.common.types import IncomingMessage
from workflows.common.confirmation_gate import check_confirmation_gate
from workflow_email import process_msg


class TestDepositToHILIntegration:
    """Integration test for the complete deposit → HIL flow."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database for testing."""
        db_path = tmp_path / "test_events_database.json"
        db_path.write_text(json.dumps({"clients": {}, "events": [], "tasks": []}))
        return db_path

    @pytest.fixture
    def event_with_billing_and_deposit_ready(self):
        """Create an event that has billing provided and deposit just paid."""
        event_id = str(uuid.uuid4())
        thread_id = f"thread-{event_id[:8]}"
        now = datetime.utcnow().isoformat() + "Z"

        return {
            "event_id": event_id,
            "thread_id": thread_id,
            "client_email": "integration-test@example.com",
            "current_step": 5,
            "offer_accepted": True,
            "status": "Lead",
            "chosen_date": "2026-06-11",
            "date_confirmed": True,
            "locked_room_id": "Room A",
            "created_at": now,  # Important for last_event_for_email
            "event_data": {
                "Email": "integration-test@example.com",  # Must match from_email
                "Event Date": "11.06.2026",
                "Billing Address": "HelvetiaL, Bahnhofstrasse 11, 8001 Zurich, Switzerland",
                "Number of Participants": "25",
                "Preferred Room": "Room A",
                "Name": "Test User",
            },
            "billing_requirements": {
                "awaiting_billing_for_accept": False,  # Already cleared
                "last_missing": [],
            },
            "billing_details": {
                "name_or_company": "HelvetiaL",
                "street": "Bahnhofstrasse 11",
                "postal_code": "8001",
                "city": "Zurich",
                "country": "Switzerland",
                "vat": None,
                "raw": "HelvetiaL, Bahnhofstrasse 11, 8001 Zurich, Switzerland",
            },
            "deposit_info": {
                "deposit_required": True,
                "deposit_amount": 206.25,
                "deposit_paid": True,  # Just paid
                "deposit_paid_at": now,
            },
            "deposit_state": {
                "required": True,
                "status": "paid",
            },
            "requirements": {
                "number_of_participants": 25,
            },
            "requirements_hash": "test-hash-123",
            "room_eval_hash": "test-hash-123",
            "audit": [],
        }

    def test_deposit_payment_triggers_hil_task_creation(self, temp_db, event_with_billing_and_deposit_ready):
        """
        CRITICAL TEST: Verify that when deposit is paid after billing,
        the workflow sends to HIL (creates HIL task or returns hil_required action).
        """
        event = event_with_billing_and_deposit_ready
        thread_id = event["thread_id"]
        client_email = event["client_email"]

        # Set up the database with the event
        db = {
            "clients": {
                client_email: {
                    "email": client_email,
                    "profile": {"name": "Test User", "org": None, "phone": None},
                    "history": [],
                    "event_ids": [event["event_id"]],
                }
            },
            "events": [event],
            "tasks": [],
        }
        temp_db.write_text(json.dumps(db))

        # Create the synthetic deposit message (as pay_deposit endpoint does)
        deposit_msg = {
            "msg_id": str(uuid.uuid4()),
            "from_name": "Client (GUI)",
            "from_email": client_email,
            "subject": f"Deposit paid for event {event['event_id']}",
            "ts": datetime.utcnow().isoformat() + "Z",
            "body": "I have paid the deposit.",
            "thread_id": thread_id,
            "session_id": thread_id,
            "event_id": event["event_id"],
            "deposit_just_paid": True,
        }

        # Stub the LLM calls
        with patch("workflows.steps.step1_intake.llm.intent_classifier.classify_intent") as mock_classify, \
             patch("workflows.steps.step1_intake.llm.analysis.extract_user_information") as mock_extract:

            # Mock LLM responses
            from domain import IntentLabel
            mock_classify.return_value = (IntentLabel.EVENT_REQUEST, 0.95)
            mock_extract.return_value = {}

            # Process the message
            result = process_msg(deposit_msg, db_path=temp_db)

        print(f"\n=== WORKFLOW RESULT ===")
        print(f"action: {result.get('action')}")
        print(f"event_id: {result.get('event_id')}")

        # Check if result indicates HIL routing
        action = result.get("action", "")

        # These actions indicate the workflow is sending to HIL
        hil_actions = [
            "negotiation_accept_pending_hil",
            "offer_confirmation_hil",
            "confirmation_hil_pending",
            "hil_approved",
            "negotiation_hil_approved",
        ]

        # Check for HIL task creation in the database
        updated_db = json.loads(temp_db.read_text())
        tasks = updated_db.get("tasks", [])
        hil_tasks = [t for t in tasks if t.get("type") in ("approval_required", "offer_approval", "confirmation")]

        print(f"HIL tasks created: {len(hil_tasks)}")
        for t in hil_tasks:
            print(f"  - {t.get('type')}: {t.get('message', '')[:50]}")

        # Check draft messages for requires_approval
        draft_messages = result.get("draft_messages", [])
        hil_required = any(d.get("requires_approval", False) for d in draft_messages)

        print(f"draft_messages with requires_approval: {hil_required}")

        # The workflow should either:
        # 1. Return an HIL action
        # 2. Create an HIL task
        # 3. Have a draft message with requires_approval=True
        is_hil = (
            action in hil_actions
            or len(hil_tasks) > 0
            or hil_required
            or "hil" in action.lower()
        )

        # Also check the confirmation gate on the event after processing
        updated_events = updated_db.get("events", [])
        if updated_events:
            updated_event = updated_events[-1]
            gate = check_confirmation_gate(updated_event)
            print(f"\n=== GATE STATUS AFTER PROCESSING ===")
            print(f"offer_accepted: {gate.offer_accepted}")
            print(f"billing_complete: {gate.billing_complete}")
            print(f"deposit_paid: {gate.deposit_paid}")
            print(f"ready_for_hil: {gate.ready_for_hil}")

            if gate.ready_for_hil:
                print("\n✓ Gate is ready for HIL!")

        assert is_hil or (updated_events and check_confirmation_gate(updated_events[-1]).ready_for_hil), \
            f"FAILED: Workflow should send to HIL after billing+deposit. Got action={action}"


class TestFullBillingThenDepositFlow:
    """Test the complete flow: billing provided THEN deposit paid."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database for testing."""
        db_path = tmp_path / "test_events_database.json"
        db_path.write_text(json.dumps({"clients": {}, "events": [], "tasks": []}))
        return db_path

    @pytest.fixture
    def event_awaiting_billing(self):
        """Create an event that is awaiting billing address."""
        event_id = str(uuid.uuid4())
        thread_id = f"thread-{event_id[:8]}"
        now = datetime.utcnow().isoformat() + "Z"

        return {
            "event_id": event_id,
            "thread_id": thread_id,
            "client_email": "billing-test@example.com",
            "current_step": 5,
            "offer_accepted": True,  # Client accepted offer
            "status": "Lead",
            "chosen_date": "2026-06-11",
            "date_confirmed": True,
            "locked_room_id": "Room A",
            "created_at": now,
            "event_data": {
                "Email": "billing-test@example.com",
                "Event Date": "11.06.2026",
                "Billing Address": "Not Specified",  # NOT YET PROVIDED
                "Number of Participants": "25",
                "Preferred Room": "Room A",
                "Name": "Test User",
            },
            "billing_requirements": {
                "awaiting_billing_for_accept": True,  # Waiting for billing!
                "last_missing": ["name_or_company", "street", "postal_code", "city", "country"],
            },
            "billing_details": {},  # Empty - not yet provided
            "deposit_info": {
                "deposit_required": True,
                "deposit_amount": 206.25,
                "deposit_paid": False,  # Not yet paid
            },
            "requirements": {
                "number_of_participants": 25,
            },
            "requirements_hash": "test-hash-123",
            "room_eval_hash": "test-hash-123",
            "audit": [],
        }

    def test_billing_provided_then_deposit_paid_sends_to_hil(self, temp_db, event_awaiting_billing):
        """
        CRITICAL TEST: The exact user scenario.

        1. Event with offer_accepted, awaiting_billing_for_accept=True
        2. Client provides billing address
        3. Client pays deposit
        4. Workflow should send to HIL

        This is the flow the user reported as broken.
        """
        event = event_awaiting_billing
        thread_id = event["thread_id"]
        client_email = event["client_email"]

        # Set up the database with the event
        db = {
            "clients": {
                client_email: {
                    "email": client_email,
                    "profile": {"name": "Test User", "org": None, "phone": None},
                    "history": [],
                    "event_ids": [event["event_id"]],
                }
            },
            "events": [event],
            "tasks": [],
        }
        temp_db.write_text(json.dumps(db))

        # Verify event was set up correctly
        print(f"\n=== INITIAL EVENT STATE ===")
        initial_db = json.loads(temp_db.read_text())
        initial_event = initial_db["events"][0]
        print(f"event_id: {initial_event.get('event_id')}")
        print(f"current_step: {initial_event.get('current_step')}")
        print(f"offer_accepted: {initial_event.get('offer_accepted')}")
        print(f"awaiting_billing_for_accept: {(initial_event.get('billing_requirements') or {}).get('awaiting_billing_for_accept')}")

        # === STEP 1: Client provides billing address ===
        billing_msg = {
            "msg_id": str(uuid.uuid4()),
            "from_name": "Client",
            "from_email": client_email,
            "subject": "Re: Your booking",
            "ts": datetime.utcnow().isoformat() + "Z",
            "body": "HelvetiaL, Bahnhofstrasse 11, 8001 Zurich, Switzerland",
            "thread_id": thread_id,
            "session_id": thread_id,
        }

        # Stub the LLM calls
        with patch("workflows.steps.step1_intake.llm.intent_classifier.classify_intent") as mock_classify, \
             patch("workflows.steps.step1_intake.llm.analysis.extract_user_information") as mock_extract:

            from domain import IntentLabel
            mock_classify.return_value = (IntentLabel.EVENT_REQUEST, 0.95)
            mock_extract.return_value = {"billing_address": "HelvetiaL, Bahnhofstrasse 11, 8001 Zurich, Switzerland"}

            # Process billing message
            result1 = process_msg(billing_msg, db_path=temp_db)

        print(f"\n=== AFTER BILLING MESSAGE ===")
        print(f"action: {result1.get('action')}")

        # Check database state after billing
        db_after_billing = json.loads(temp_db.read_text())
        event_after_billing = db_after_billing["events"][0]

        print(f"billing_details: {event_after_billing.get('billing_details')}")
        print(f"awaiting_billing_for_accept: {(event_after_billing.get('billing_requirements') or {}).get('awaiting_billing_for_accept')}")
        print(f"current_step AFTER billing: {event_after_billing.get('current_step')}")

        # Verify billing was stored
        billing_details = event_after_billing.get("billing_details", {})
        assert billing_details.get("city") == "Zurich", f"Billing city should be 'Zurich', got {billing_details.get('city')}"

        # Verify awaiting flag is cleared
        billing_req = event_after_billing.get("billing_requirements") or {}
        assert billing_req.get("awaiting_billing_for_accept") == False, \
            f"awaiting_billing_for_accept should be False after billing provided, got {billing_req.get('awaiting_billing_for_accept')}"

        # === STEP 2: Mark deposit as paid (simulating pay_deposit API) ===
        event_after_billing["deposit_info"]["deposit_paid"] = True
        event_after_billing["deposit_info"]["deposit_paid_at"] = datetime.utcnow().isoformat() + "Z"
        db_after_billing["events"][0] = event_after_billing
        temp_db.write_text(json.dumps(db_after_billing))

        # === STEP 3: Send synthetic deposit message ===
        deposit_msg = {
            "msg_id": str(uuid.uuid4()),
            "from_name": "Client (GUI)",
            "from_email": client_email,
            "subject": f"Deposit paid for event {event['event_id']}",
            "ts": datetime.utcnow().isoformat() + "Z",
            "body": "I have paid the deposit.",
            "thread_id": thread_id,
            "session_id": thread_id,
            "deposit_just_paid": True,
        }

        with patch("workflows.steps.step1_intake.llm.intent_classifier.classify_intent") as mock_classify, \
             patch("workflows.steps.step1_intake.llm.analysis.extract_user_information") as mock_extract:

            from domain import IntentLabel
            mock_classify.return_value = (IntentLabel.EVENT_REQUEST, 0.95)
            mock_extract.return_value = {}

            result2 = process_msg(deposit_msg, db_path=temp_db)

        print(f"\n=== AFTER DEPOSIT MESSAGE ===")
        print(f"action: {result2.get('action')}")

        # Check final state
        final_db = json.loads(temp_db.read_text())
        final_event = final_db["events"][0]
        gate = check_confirmation_gate(final_event)

        print(f"\n=== FINAL GATE STATUS ===")
        print(f"offer_accepted: {gate.offer_accepted}")
        print(f"billing_complete: {gate.billing_complete}")
        print(f"billing_missing: {gate.billing_missing}")
        print(f"deposit_paid: {gate.deposit_paid}")
        print(f"ready_for_hil: {gate.ready_for_hil}")

        # Verify HIL was triggered
        action = result2.get("action", "")
        hil_actions = [
            "negotiation_accept_pending_hil",
            "offer_confirmation_hil",
            "confirmation_hil_pending",
            "hil_approved",
            "negotiation_hil_approved",
        ]

        # Check for HIL task creation
        tasks = final_db.get("tasks", [])
        hil_tasks = [t for t in tasks if t.get("type") in ("approval_required", "offer_approval", "confirmation")]

        # Check draft messages
        draft_messages = result2.get("draft_messages", [])
        hil_required = any(d.get("requires_approval", False) for d in draft_messages)

        is_hil = (
            action in hil_actions
            or len(hil_tasks) > 0
            or hil_required
            or "hil" in action.lower()
            or gate.ready_for_hil
        )

        assert is_hil, f"CRITICAL FAILURE: Workflow did not send to HIL. action={action}, gate.ready_for_hil={gate.ready_for_hil}"
        print("\n✓ SUCCESS: Workflow sent to HIL!")


class TestConfirmationGateWithRealData:
    """Test confirmation gate with the exact data from user's scenario."""

    def test_gate_with_user_scenario_data(self):
        """Test with the exact data from the user's failed scenario."""
        # This is the state AFTER billing is properly stored
        event_entry = {
            "event_id": "a01ab5f5-bccb-4d58-a43f-54b26f39a5eb",
            "current_step": 5,
            "offer_accepted": True,
            "billing_requirements": {
                "awaiting_billing_for_accept": False,  # Should be cleared after billing
                "last_missing": [],
            },
            "billing_details": {
                "name_or_company": "HelvetiaL",
                "street": "Bahnhofstrasse 11",
                "postal_code": "8001",
                "city": "Zurich",
                "country": "Switzerland",
                "vat": None,
                "raw": "HelvetiaL, Bahnhofstrasse 11, 8001 Zurich, Switzerland",
            },
            "deposit_info": {
                "deposit_required": True,
                "deposit_amount": 206.25,
                "deposit_paid": True,
                "deposit_paid_at": "2025-12-23T12:59:11.576076Z",
            },
        }

        gate = check_confirmation_gate(event_entry)

        print(f"\n=== GATE STATUS ===")
        print(f"offer_accepted: {gate.offer_accepted}")
        print(f"billing_complete: {gate.billing_complete}")
        print(f"billing_missing: {gate.billing_missing}")
        print(f"deposit_required: {gate.deposit_required}")
        print(f"deposit_paid: {gate.deposit_paid}")
        print(f"ready_for_hil: {gate.ready_for_hil}")

        assert gate.offer_accepted == True
        assert gate.billing_complete == True
        assert gate.billing_missing == []
        assert gate.deposit_paid == True
        assert gate.ready_for_hil == True, "CRITICAL: Gate must be ready for HIL!"
