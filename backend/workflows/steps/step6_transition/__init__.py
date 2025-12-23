"""
Step 6: Transition Checkpoint - Validate consistency before confirmation.

This step handles:
- Validating all prerequisites before Step 7 (Confirmation)
- Checking confirmed date, locked room, accepted offer
- Verifying deposit payment if required
- Setting transition_ready flag

CANONICAL LOCATION: backend/workflows/steps/step6_transition/
MIGRATED FROM: backend/workflows/groups/transition_checkpoint.py

Submodules:
    trigger/    - Main entry point (process function)
"""

from .trigger.process import process

__all__ = ["process"]
