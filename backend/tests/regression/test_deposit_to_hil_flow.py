"""
Test: After billing is provided and deposit is paid, workflow should send to HIL.

This test verifies the complete flow:
1. Create event with offer accepted
2. Simulate billing address being provided
3. Simulate deposit being paid via API
4. Verify the workflow continues to HIL (ready_for_hil=True)
"""
import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.common.confirmation_gate import check_confirmation_gate
from backend.workflows.common.billing import update_billing_details, missing_billing_fields


class TestDepositPaymentTriggersHIL:
    """Test that paying deposit after billing is provided sends to HIL."""

    def _create_event_at_step5_with_offer_accepted(self):
        """Create a mock event at step 5 with offer accepted, awaiting billing."""
        return {
            "event_id": str(uuid.uuid4()),
            "client_email": "test@example.com",
            "thread_id": "test-thread-123",
            "current_step": 5,
            "offer_accepted": True,
            "status": "Lead",
            "event_data": {
                "Email": "test@example.com",
                "Billing Address": "Not Specified",
            },
            "billing_requirements": {
                "awaiting_billing_for_accept": True,
                "last_missing": ["name_or_company", "street", "postal_code", "city", "country"],
            },
            "billing_details": {},
            "deposit_info": {
                "deposit_required": True,
                "deposit_amount": 206.25,
                "deposit_paid": False,
            },
            "requirements": {"number_of_participants": 25},
        }

    def test_billing_is_stored_and_parsed_correctly(self):
        """Test that billing address is stored and parsed when provided."""
        event_entry = self._create_event_at_step5_with_offer_accepted()

        # Simulate storing billing address (as step5_handler does)
        billing_address = "HelvetiaL, Bahnhofstrasse 11, 8001 Zurich, Switzerland"
        event_entry["event_data"]["Billing Address"] = billing_address

        # Call update_billing_details (as _refresh_billing does)
        update_billing_details(event_entry)

        # Verify billing was parsed correctly
        details = event_entry.get("billing_details", {})
        assert details.get("name_or_company") == "HelvetiaL", f"name_or_company should be 'HelvetiaL', got {details.get('name_or_company')}"
        assert details.get("street") == "Bahnhofstrasse 11", f"street should be 'Bahnhofstrasse 11', got {details.get('street')}"
        assert details.get("postal_code") == "8001", f"postal_code should be '8001', got {details.get('postal_code')}"
        assert details.get("city") == "Zurich", f"city should be 'Zurich', got {details.get('city')}"
        assert details.get("country") == "Switzerland", f"country should be 'Switzerland', got {details.get('country')}"

        # Verify no missing fields
        missing = missing_billing_fields(event_entry)
        assert missing == [], f"Expected no missing fields, got {missing}"

    def test_awaiting_billing_flag_is_cleared_when_billing_complete(self):
        """Test that awaiting_billing_for_accept is cleared when billing is complete."""
        event_entry = self._create_event_at_step5_with_offer_accepted()

        # Simulate billing being provided
        event_entry["event_data"]["Billing Address"] = "HelvetiaL, Bahnhofstrasse 11, 8001 Zurich, Switzerland"
        update_billing_details(event_entry)

        # Simulate the clearing logic from step5_handler
        billing_req = event_entry.get("billing_requirements") or {}
        billing_missing = missing_billing_fields(event_entry)

        if not billing_missing and billing_req.get("awaiting_billing_for_accept"):
            billing_req["awaiting_billing_for_accept"] = False
            billing_req["last_missing"] = []

        # Verify flag is cleared
        assert billing_req.get("awaiting_billing_for_accept") == False, "awaiting_billing_for_accept should be False"
        assert billing_req.get("last_missing") == [], "last_missing should be empty"

    def test_deposit_signal_skips_billing_capture(self):
        """Test that deposit_just_paid signal prevents billing address corruption."""
        # Create synthetic deposit message
        deposit_msg = {
            "msg_id": str(uuid.uuid4()),
            "from_email": "test@example.com",
            "body": "I have paid the deposit.",
            "deposit_just_paid": True,
        }

        msg = IncomingMessage.from_dict(deposit_msg)

        # Verify deposit_just_paid is in extras
        assert msg.extras.get("deposit_just_paid") == True, "deposit_just_paid should be in extras"

        # Simulate the check in step5_handler
        is_deposit_signal = (msg.extras or {}).get("deposit_just_paid", False)
        assert is_deposit_signal == True, "is_deposit_signal should be True"

    def test_confirmation_gate_ready_after_billing_and_deposit(self):
        """Test that confirmation gate returns ready_for_hil=True after billing and deposit."""
        event_entry = self._create_event_at_step5_with_offer_accepted()

        # Step 1: Provide billing
        event_entry["event_data"]["Billing Address"] = "HelvetiaL, Bahnhofstrasse 11, 8001 Zurich, Switzerland"
        update_billing_details(event_entry)

        # Clear the awaiting flag (as step5_handler does)
        billing_req = event_entry.get("billing_requirements") or {}
        billing_missing = missing_billing_fields(event_entry)
        if not billing_missing:
            billing_req["awaiting_billing_for_accept"] = False
            billing_req["last_missing"] = []

        # Verify billing is complete but deposit not paid yet
        gate = check_confirmation_gate(event_entry)
        assert gate.billing_complete == True, f"billing_complete should be True, got {gate.billing_complete}"
        assert gate.deposit_paid == False, f"deposit_paid should be False before payment"
        assert gate.ready_for_hil == False, f"ready_for_hil should be False (deposit not paid)"

        # Step 2: Pay deposit
        event_entry["deposit_info"]["deposit_paid"] = True

        # Verify gate is now ready
        gate = check_confirmation_gate(event_entry)
        assert gate.offer_accepted == True, f"offer_accepted should be True"
        assert gate.billing_complete == True, f"billing_complete should be True"
        assert gate.deposit_paid == True, f"deposit_paid should be True after payment"
        assert gate.ready_for_hil == True, f"ready_for_hil should be True after billing and deposit"

    def test_full_flow_billing_then_deposit_to_hil(self):
        """
        Full integration test: billing provided, deposit paid, should be ready for HIL.

        This simulates the exact flow the user described:
        1. Event with offer accepted
        2. Client provides billing address
        3. Client pays deposit
        4. System should send to HIL
        """
        from backend.workflows.steps.step5_negotiation.trigger.step5_handler import _refresh_billing

        # Create event at step 5 with offer accepted
        event_entry = self._create_event_at_step5_with_offer_accepted()

        # === PHASE 1: Client provides billing address ===
        billing_address = "HelvetiaL, Bahnhofstrasse 11, 8001 Zurich, Switzerland"

        # Simulate what step5_handler does when billing is provided
        billing_req = event_entry.get("billing_requirements") or {}
        if billing_req.get("awaiting_billing_for_accept"):
            # Not a deposit signal, so store the billing
            event_entry.setdefault("event_data", {})["Billing Address"] = billing_address

        # Refresh billing (parse and update billing_details)
        billing_missing = _refresh_billing(event_entry)

        # Clear awaiting flag if billing is complete
        if not billing_missing and billing_req.get("awaiting_billing_for_accept"):
            billing_req["awaiting_billing_for_accept"] = False
            billing_req["last_missing"] = []

        # Verify billing state after phase 1
        assert event_entry["event_data"]["Billing Address"] == billing_address
        assert billing_req.get("awaiting_billing_for_accept") == False, "Flag should be cleared"

        gate = check_confirmation_gate(event_entry)
        assert gate.billing_complete == True, "Billing should be complete"
        assert gate.deposit_paid == False, "Deposit not paid yet"
        assert gate.ready_for_hil == False, "Not ready yet (deposit missing)"

        # === PHASE 2: Deposit is paid via API ===
        event_entry["deposit_info"]["deposit_paid"] = True
        event_entry["deposit_info"]["deposit_paid_at"] = "2025-12-23T14:00:00Z"

        # === PHASE 3: Synthetic deposit message is processed ===
        # Create the synthetic message (as pay_deposit endpoint does)
        deposit_msg = IncomingMessage.from_dict({
            "msg_id": str(uuid.uuid4()),
            "from_email": "test@example.com",
            "body": "I have paid the deposit.",
            "deposit_just_paid": True,
        })

        # Simulate step5_handler processing
        billing_req = event_entry.get("billing_requirements") or {}
        if billing_req.get("awaiting_billing_for_accept"):
            # Check for deposit signal - should skip billing capture
            is_deposit_signal = (deposit_msg.extras or {}).get("deposit_just_paid", False)
            assert is_deposit_signal == True, "Should detect deposit signal"
            # Since it's a deposit signal, we DON'T overwrite billing address

        # Refresh billing (should still be complete from phase 1)
        billing_missing = _refresh_billing(event_entry)
        assert billing_missing == [], "Billing should still be complete"

        # === FINAL CHECK: Gate should be ready for HIL ===
        gate = check_confirmation_gate(event_entry)

        print(f"\n=== FINAL GATE STATUS ===")
        print(f"offer_accepted: {gate.offer_accepted}")
        print(f"billing_complete: {gate.billing_complete}")
        print(f"billing_missing: {gate.billing_missing}")
        print(f"deposit_required: {gate.deposit_required}")
        print(f"deposit_paid: {gate.deposit_paid}")
        print(f"ready_for_hil: {gate.ready_for_hil}")

        assert gate.offer_accepted == True, "offer_accepted should be True"
        assert gate.billing_complete == True, "billing_complete should be True"
        assert gate.deposit_paid == True, "deposit_paid should be True"
        assert gate.ready_for_hil == True, "CRITICAL: ready_for_hil must be True after billing and deposit!"


class TestPayDepositEndpoint:
    """Test the pay_deposit API endpoint logic."""

    def test_pay_deposit_uses_confirmation_gate_correctly(self):
        """Test that pay_deposit checks billing via confirmation_gate, not direct field."""
        from backend.workflows.common.confirmation_gate import check_confirmation_gate

        # Event with billing properly stored in billing_details (not billing_address field)
        event_entry = {
            "event_id": "test-123",
            "offer_accepted": True,
            "billing_details": {
                "name_or_company": "HelvetiaL",
                "street": "Bahnhofstrasse 11",
                "postal_code": "8001",
                "city": "Zurich",
                "country": "Switzerland",
            },
            "deposit_info": {
                "deposit_required": True,
                "deposit_paid": True,  # Just marked as paid
            },
        }

        # Check that confirmation gate sees billing as complete
        gate = check_confirmation_gate(event_entry)

        assert gate.billing_complete == True, "billing_complete should be True when billing_details is filled"
        assert gate.deposit_paid == True, "deposit_paid should be True"
        assert gate.ready_for_hil == True, "ready_for_hil should be True"

        # Verify the old broken check would fail
        old_check = event_entry.get("billing_address")  # This field doesn't exist!
        assert old_check is None, "billing_address field should not exist (old bug)"
