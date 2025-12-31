"""
Offer utilities for Supabase integration.

Provides:
- Offer number generation (OE-2025-12-XXXX format)
- Offer record formatting for Supabase
- Line item formatting

Based on EMAIL_WORKFLOW_INTEGRATION_REQUIREMENTS.md Section A5.
"""

from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Any, Dict, List, Optional

import pytz

from backend.workflows.io.config_store import get_timezone


def _get_venue_tz() -> pytz.BaseTzInfo:
    """Return venue timezone from config as pytz timezone."""
    return pytz.timezone(get_timezone())


def generate_offer_number(team_prefix: str = "OE") -> str:
    """
    Generate a unique offer number in the required format.

    Format: {PREFIX}-{YEAR}-{MONTH}-{SHORT_UUID}
    Example: OE-2025-12-A3F7

    Args:
        team_prefix: Prefix for the offer number (default: "OE" for OpenEvent)

    Returns:
        Unique offer number string

    Example:
        >>> offer_num = generate_offer_number()
        >>> offer_num.startswith("OE-")
        True
        >>> len(offer_num.split("-"))
        4
    """
    now = datetime.now(_get_venue_tz())
    short_id = str(uuid.uuid4())[:4].upper()
    return f"{team_prefix}-{now.year}-{now.month:02d}-{short_id}"


def generate_offer_subject(event_title: str) -> str:
    """
    Generate a standard offer subject line.

    Args:
        event_title: Title of the event

    Returns:
        Formatted subject string

    Example:
        >>> generate_offer_subject("Corporate Meeting - Acme Inc")
        'Event Offer - Corporate Meeting - Acme Inc'
    """
    return f"Event Offer - {event_title}"


def format_date_for_supabase(dt: Optional[date] = None) -> str:
    """
    Format a date for Supabase storage (YYYY-MM-DD).

    Args:
        dt: Date object (defaults to today in Zurich timezone)

    Returns:
        Date string in YYYY-MM-DD format

    Example:
        >>> from datetime import date
        >>> format_date_for_supabase(date(2025, 2, 15))
        '2025-02-15'
    """
    if dt is None:
        dt = datetime.now(_get_venue_tz()).date()
    return dt.strftime("%Y-%m-%d")


def calculate_valid_until(
    offer_date: Optional[date] = None,
    validity_days: int = 14
) -> str:
    """
    Calculate offer validity end date.

    Args:
        offer_date: Start date (defaults to today)
        validity_days: Number of days the offer is valid

    Returns:
        Valid until date in YYYY-MM-DD format
    """
    from datetime import timedelta

    if offer_date is None:
        offer_date = datetime.now(_get_venue_tz()).date()

    valid_until = offer_date + timedelta(days=validity_days)
    return format_date_for_supabase(valid_until)


# =============================================================================
# Offer Record Formatting
# =============================================================================

def create_offer_record(
    event_id: str,
    user_id: str,
    event_title: str,
    client_name: Optional[str] = None,
    client_email: Optional[str] = None,
    client_company: Optional[str] = None,
    subtotal: float = 0.0,
    vat_amount: float = 0.0,
    total_amount: float = 0.0,
    deposit_enabled: bool = False,
    deposit_type: str = "percentage",
    deposit_percentage: Optional[float] = None,
    deposit_amount: Optional[float] = None,
    deposit_deadline_days: int = 10,
    validity_days: int = 14,
    team_prefix: str = "OE",
) -> Dict[str, Any]:
    """
    Create a properly formatted offer record for Supabase.

    Args:
        event_id: UUID of the linked event
        user_id: UUID of the user creating the offer (system user)
        event_title: Title of the event (for subject generation)
        client_name: Client's name
        client_email: Client's email
        client_company: Client's company
        subtotal: Subtotal before VAT
        vat_amount: VAT amount
        total_amount: Total including VAT
        deposit_enabled: Whether deposit is required
        deposit_type: "percentage" or "fixed"
        deposit_percentage: Deposit percentage (if type=percentage)
        deposit_amount: Deposit amount (if type=fixed, or calculated)
        deposit_deadline_days: Days until deposit is due
        validity_days: Days the offer is valid
        team_prefix: Prefix for offer number

    Returns:
        Dictionary ready for Supabase insertion

    Example:
        >>> offer = create_offer_record(
        ...     event_id="uuid-123",
        ...     user_id="uuid-456",
        ...     event_title="Corporate Dinner",
        ...     total_amount=5000.0,
        ...     deposit_enabled=True,
        ...     deposit_percentage=30.0
        ... )
        >>> "offer_number" in offer
        True
    """
    offer_date = format_date_for_supabase()
    valid_until = calculate_valid_until(validity_days=validity_days)

    record = {
        # Required fields
        "offer_number": generate_offer_number(team_prefix),
        "subject": generate_offer_subject(event_title),
        "offer_date": offer_date,
        "user_id": user_id,

        # Event link
        "event_id": event_id,

        # Client info (stored on offer for historical record)
        "client_name": client_name,
        "client_email": client_email,
        "client_company": client_company,

        # Dates
        "valid_until": valid_until,

        # Amounts
        "subtotal": subtotal,
        "vat_amount": vat_amount,
        "total_amount": total_amount,

        # Deposit settings
        "deposit_enabled": deposit_enabled,
        "deposit_type": deposit_type,
        "deposit_percentage": deposit_percentage,
        "deposit_amount": deposit_amount,
        "deposit_deadline_days": deposit_deadline_days,

        # Status (will be set by Supabase default or explicitly)
        "status": "draft",
    }

    # Calculate deposit amount if percentage-based and not provided
    if deposit_enabled and deposit_type == "percentage" and deposit_percentage:
        if not deposit_amount:
            record["deposit_amount"] = round(total_amount * (deposit_percentage / 100), 2)

    return record


# =============================================================================
# Line Item Formatting
# =============================================================================

def create_line_item(
    offer_id: str,
    name: str,
    quantity: int,
    unit_price: float,
    description: Optional[str] = None,
    product_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a properly formatted offer line item for Supabase.

    Args:
        offer_id: UUID of the parent offer
        name: Product/room/service name
        quantity: Number of units
        unit_price: Price per unit
        description: Optional description
        product_id: UUID of linked product (None for room or custom items)

    Returns:
        Dictionary ready for Supabase insertion

    Example:
        >>> item = create_line_item(
        ...     offer_id="uuid-123",
        ...     name="Conference Room A",
        ...     quantity=1,
        ...     unit_price=500.0
        ... )
        >>> item["total"]
        500.0
    """
    return {
        "offer_id": offer_id,
        "name": name,
        "quantity": quantity,
        "unit_price": unit_price,
        "total": quantity * unit_price,
        "description": description,
        "product_id": product_id,
    }


def create_room_line_item(
    offer_id: str,
    room_name: str,
    room_rate: float,
    rate_type: str = "daily",
    quantity: int = 1,
    room_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a line item specifically for room charges.

    Args:
        offer_id: UUID of the parent offer
        room_name: Name of the room
        room_rate: Room rate
        rate_type: "hourly", "daily", or "fixed"
        quantity: Duration in hours/days (or 1 for fixed)
        room_id: UUID of the room (optional - rooms aren't in products table)

    Returns:
        Dictionary ready for Supabase insertion
    """
    description = f"Room rental ({rate_type})"

    return {
        "offer_id": offer_id,
        "name": room_name,
        "quantity": quantity,
        "unit_price": room_rate,
        "total": quantity * room_rate,
        "description": description,
        "product_id": None,  # Rooms are not products
    }


def create_product_line_item(
    offer_id: str,
    product: Dict[str, Any],
    quantity: int = 1,
) -> Dict[str, Any]:
    """
    Create a line item from a product record.

    Args:
        offer_id: UUID of the parent offer
        product: Product record from Supabase (must have id, name, base_price)
        quantity: Number of units

    Returns:
        Dictionary ready for Supabase insertion
    """
    return {
        "offer_id": offer_id,
        "name": product.get("name", "Unknown Product"),
        "quantity": quantity,
        "unit_price": product.get("base_price", 0),
        "total": quantity * product.get("base_price", 0),
        "description": product.get("description"),
        "product_id": product.get("id"),
    }


# =============================================================================
# Offer Amount Calculations
# =============================================================================

def calculate_offer_totals(
    line_items: List[Dict[str, Any]],
    vat_rate: float = 8.1,  # Swiss VAT
    vat_included: bool = True,
) -> Dict[str, float]:
    """
    Calculate offer totals from line items.

    Args:
        line_items: List of line item dictionaries with 'total' field
        vat_rate: VAT percentage (default: 8.1% Swiss VAT)
        vat_included: Whether prices include VAT

    Returns:
        Dictionary with subtotal, vat_amount, total_amount

    Example:
        >>> items = [{"total": 500.0}, {"total": 300.0}]
        >>> totals = calculate_offer_totals(items, vat_rate=8.1)
        >>> totals["total_amount"]
        800.0
    """
    items_total = sum(item.get("total", 0) for item in line_items)

    if vat_included:
        # VAT is already included in prices
        # Back-calculate VAT portion
        vat_divisor = 1 + (vat_rate / 100)
        subtotal = round(items_total / vat_divisor, 2)
        vat_amount = round(items_total - subtotal, 2)
        total_amount = items_total
    else:
        # VAT needs to be added
        subtotal = items_total
        vat_amount = round(items_total * (vat_rate / 100), 2)
        total_amount = round(subtotal + vat_amount, 2)

    return {
        "subtotal": subtotal,
        "vat_amount": vat_amount,
        "total_amount": total_amount,
    }


def calculate_deposit_amount(
    total_amount: float,
    deposit_percentage: Optional[float] = None,
    deposit_fixed: Optional[float] = None,
) -> float:
    """
    Calculate deposit amount.

    Args:
        total_amount: Total offer amount
        deposit_percentage: Percentage for deposit (e.g., 30 for 30%)
        deposit_fixed: Fixed deposit amount (takes precedence if both provided)

    Returns:
        Calculated deposit amount
    """
    if deposit_fixed is not None:
        return deposit_fixed

    if deposit_percentage is not None:
        return round(total_amount * (deposit_percentage / 100), 2)

    return 0.0