"""
Step 2: Date Confirmation - Negotiate and confirm event dates with client.

This step handles:
- Presenting available date options to client
- Parsing client date preferences and confirmations
- Validating date availability against calendar
- Confirming final event date

CANONICAL LOCATION: backend/workflows/steps/step2_date_confirmation/
MIGRATED FROM: backend/workflows/groups/date_confirmation/

Submodules:
    trigger/    - Main entry point (process function)
    condition/  - Gate checks (is_valid_ddmmyyyy)
    llm/        - LLM-based analysis (compose_date_confirmation_reply)
"""

from .trigger.process import process
from .llm.analysis import compose_date_confirmation_reply
from .condition.decide import is_valid_ddmmyyyy

__all__ = ["process", "compose_date_confirmation_reply", "is_valid_ddmmyyyy"]
