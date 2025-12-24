from __future__ import annotations

import math
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from backend.utils import json_io
from backend.workflows.steps.step3_room_availability.db_pers import load_rooms_config


# ---------------------------------------------------------------------------
# Deposit Calculation Functions
# ---------------------------------------------------------------------------
# These functions calculate deposit amounts based on the global deposit
# configuration set by the manager. The deposit is applied to offers and
# must be paid before the client can confirm the booking.
#
# INTEGRATION NOTE (for Supabase/production):
# ------------------------------------------
# By default, deposit is DISABLED (deposit_enabled=False). Deposits are only
# applied when the manager configures them via the frontend settings panel.
#
# Two deposit types are supported:
# 1. FIXED: A fixed CHF amount (e.g., CHF 500)
#    - Set deposit_type="fixed" and deposit_fixed_amount=500.0
#    - Amount does NOT depend on room price or offer total
#
# 2. PERCENTAGE: A percentage of the selected room's price / offer total
#    - Set deposit_type="percentage" and deposit_percentage=30 (for 30%)
#    - Amount is calculated as: total_amount * (percentage / 100.0)
#    - Example: 30% of CHF 680 room = CHF 204 deposit
#
# The frontend settings panel allows managers to toggle between these modes.
# When integrating with Supabase, store the config in a settings table and
# load it on startup. The default should be deposit_enabled=False until
# explicitly configured by the manager.
#
# See docs/internal/OPEN_DECISIONS.md for related design decisions:
# - DECISION-001: Deposit Changes After Payment
# - DECISION-002: LLM vs Template for Deposit Reminders
# - DECISION-003: Deposit Payment Verification
# ---------------------------------------------------------------------------

# Swiss VAT rate (8.1% as of 2024)
SWISS_VAT_RATE = 0.081


def calculate_vat_included(gross_amount: float) -> float:
    """Calculate the VAT portion included in a gross amount (Swiss VAT 8.1%)."""
    return round(gross_amount * SWISS_VAT_RATE / (1 + SWISS_VAT_RATE), 2)


def calculate_deposit_amount(
    total_amount: float,
    deposit_config: Dict[str, Any],
) -> Optional[float]:
    """
    Calculate the deposit amount based on configuration.

    Args:
        total_amount: The total offer amount in CHF
        deposit_config: The global deposit configuration dict containing:
            - deposit_enabled: bool
            - deposit_type: "percentage" | "fixed"
            - deposit_percentage: int (1-100)
            - deposit_fixed_amount: float

    Returns:
        The deposit amount in CHF, or None if deposit is not enabled.
    """
    if not deposit_config or not deposit_config.get("deposit_enabled"):
        return None

    deposit_type = deposit_config.get("deposit_type", "percentage")

    if deposit_type == "fixed":
        fixed_amount = deposit_config.get("deposit_fixed_amount", 0.0)
        return round(float(fixed_amount), 2) if fixed_amount else None

    # Percentage-based deposit
    percentage = deposit_config.get("deposit_percentage", 30)
    if not percentage or percentage <= 0:
        return None

    deposit = total_amount * (percentage / 100.0)
    return round(deposit, 2)


def calculate_deposit_due_date(
    deposit_config: Dict[str, Any],
    from_date: Optional[datetime] = None,
) -> Optional[str]:
    """
    Calculate the deposit due date based on configuration.

    Args:
        deposit_config: The global deposit configuration dict containing:
            - deposit_deadline_days: int (days until payment due)
        from_date: The date to calculate from (defaults to today)

    Returns:
        The due date as ISO string (YYYY-MM-DD), or None if not configured.
    """
    if not deposit_config or not deposit_config.get("deposit_enabled"):
        return None

    deadline_days = deposit_config.get("deposit_deadline_days", 10)
    if not deadline_days or deadline_days <= 0:
        deadline_days = 10

    base_date = from_date or datetime.now()
    due_date = base_date + timedelta(days=deadline_days)
    return due_date.strftime("%Y-%m-%d")


def build_deposit_info(
    total_amount: float,
    deposit_config: Dict[str, Any],
    from_date: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """
    Build complete deposit information for an offer.

    Args:
        total_amount: The total offer amount in CHF
        deposit_config: The global deposit configuration
        from_date: The date to calculate due date from

    Returns:
        A dict with deposit details, or None if deposit not enabled:
        {
            "deposit_required": True,
            "deposit_amount": float,
            "deposit_vat_included": float,
            "deposit_type": "percentage" | "fixed",
            "deposit_percentage": int | None,
            "deposit_due_date": "YYYY-MM-DD",
            "deposit_deadline_days": int,
            "deposit_paid": False,
            "deposit_paid_at": None
        }
    """
    if not deposit_config or not deposit_config.get("deposit_enabled"):
        return None

    deposit_amount = calculate_deposit_amount(total_amount, deposit_config)
    if deposit_amount is None or deposit_amount <= 0:
        return None

    due_date = calculate_deposit_due_date(deposit_config, from_date)

    return {
        "deposit_required": True,
        "deposit_amount": deposit_amount,
        "deposit_vat_included": calculate_vat_included(deposit_amount),
        "deposit_type": deposit_config.get("deposit_type", "percentage"),
        "deposit_percentage": deposit_config.get("deposit_percentage") if deposit_config.get("deposit_type") == "percentage" else None,
        "deposit_due_date": due_date,
        "deposit_deadline_days": deposit_config.get("deposit_deadline_days", 10),
        "deposit_paid": False,
        "deposit_paid_at": None,
    }


def format_deposit_for_offer(deposit_info: Dict[str, Any]) -> str:
    """
    Format deposit information for inclusion in offer message.

    Returns a markdown string like:
    ---
    **Payment Terms:**
    - Deposit required: CHF 150.00 (30% of total)
    - VAT included: CHF 11.17
    - Due by: 18 December 2025
    - Balance due: Upon event completion
    """
    if not deposit_info or not deposit_info.get("deposit_required"):
        return ""

    amount = deposit_info.get("deposit_amount", 0)
    vat = deposit_info.get("deposit_vat_included", 0)
    due_date = deposit_info.get("deposit_due_date")
    deposit_type = deposit_info.get("deposit_type", "percentage")
    percentage = deposit_info.get("deposit_percentage")

    # Format the deposit description
    if deposit_type == "percentage" and percentage:
        deposit_desc = f"CHF {amount:,.2f} ({percentage}% of total)"
    else:
        deposit_desc = f"CHF {amount:,.2f}"

    # Format due date nicely
    due_date_formatted = due_date
    if due_date:
        try:
            dt = datetime.strptime(due_date, "%Y-%m-%d")
            due_date_formatted = dt.strftime("%d %B %Y")
        except ValueError:
            pass

    lines = [
        "",
        "---",
        "**Payment Terms:**",
        f"- Deposit required: {deposit_desc}",
        f"- VAT included: CHF {vat:,.2f}",
    ]

    if due_date_formatted:
        lines.append(f"- Due by: {due_date_formatted}")

    lines.append("- Balance due: Upon event completion")

    return "\n".join(lines)

ROOM_RATE_FALLBACKS: Dict[str, float] = {
    "room a": 500.0,
    "room b": 750.0,
    "room c": 1100.0,
    "punkt.null": 1500.0,
}


def normalise_rate(value: Any) -> Optional[float]:
    """Parse a numeric rate and ignore empty/zero values."""

    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if rate <= 0:
        return None
    return rate


def _room_name_from_event(event_entry: Dict[str, Any]) -> Optional[str]:
    return (
        event_entry.get("locked_room_id")
        or (event_entry.get("room_pending_decision") or {}).get("selected_room")
        or (event_entry.get("requirements") or {}).get("preferred_room")
    )


@lru_cache(maxsize=1)
def _room_rate_map() -> Dict[str, float]:
    mapping: Dict[str, float] = {}
    info_path = Path(__file__).resolve().parents[3] / "room_info.json"
    if info_path.exists():
        try:
            with info_path.open("r", encoding="utf-8") as handle:
                payload = json_io.load(handle)
            for entry in payload.get("rooms") or []:
                name = str(entry.get("name") or "").strip()
                rate = normalise_rate(entry.get("full_day_rate"))
                if name and rate is not None:
                    mapping[name.lower()] = rate
        except Exception:
            # If room info cannot be loaded, fall back to defaults.
            pass

    for key, value in ROOM_RATE_FALLBACKS.items():
        mapping.setdefault(key, value)
    return mapping


@lru_cache(maxsize=1)
def _room_capacity_map() -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for entry in load_rooms_config() or []:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        capacity = (
            entry.get("capacity_max")
            or entry.get("capacity")
            or entry.get("max_capacity")
            or entry.get("capacity_maximum")
        )
        try:
            mapping[name.lower()] = int(capacity)
        except (TypeError, ValueError):
            continue
    return mapping


def _rate_from_capacity(room_name: str) -> Optional[float]:
    capacity = _room_capacity_map().get(room_name.lower())
    if not capacity:
        return None

    multiplier = 12.5 if capacity <= 60 else 13.75
    estimate = math.ceil((capacity * multiplier) / 50.0) * 50.0
    return normalise_rate(estimate)


def room_rate_for_name(room_name: Optional[str]) -> Optional[float]:
    """Return a daily room rate using configured or derived pricing."""

    if not room_name:
        return None
    cleaned = str(room_name).strip()
    if not cleaned:
        return None

    rate_map = _room_rate_map()
    explicit = normalise_rate(rate_map.get(cleaned.lower()))
    if explicit is not None:
        return explicit

    return _rate_from_capacity(cleaned)


def derive_room_rate(event_entry: Dict[str, Any]) -> Optional[float]:
    """Lookup the room rate for the selected/locked room on the event."""

    room_name = _room_name_from_event(event_entry)
    return room_rate_for_name(room_name)

