"""
Adapter switcher - routes database calls to JSON or Supabase.

This is the main entry point for the integration layer. Import from here
to get the correct implementation based on the current mode.

Usage:
    from backend.workflows.io.integration.adapter import db

    # These calls will route to JSON or Supabase based on OE_INTEGRATION_MODE
    client = db.upsert_client(email, name)
    event_id = db.create_event(event_data)

Or for more explicit control:

    from backend.workflows.io.integration.adapter import (
        get_database_adapter,
        is_using_supabase,
    )

    adapter = get_database_adapter()
    adapter.upsert_client(email, name)

Environment:
    OE_INTEGRATION_MODE=json     -> Use local JSON file (default, current behavior)
    OE_INTEGRATION_MODE=supabase -> Use Supabase database
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .config import INTEGRATION_CONFIG, is_integration_mode

if TYPE_CHECKING:
    from pathlib import Path


logger = logging.getLogger(__name__)


# =============================================================================
# Database Adapter Interface
# =============================================================================

class DatabaseAdapter:
    """
    Abstract interface for database operations.

    Both JSON and Supabase adapters implement this interface,
    allowing seamless switching between backends.
    """

    def __init__(self):
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the adapter (called lazily on first use)."""
        raise NotImplementedError

    # Client operations
    def upsert_client(
        self,
        email: str,
        name: Optional[str] = None,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or return a client profile."""
        raise NotImplementedError

    # Event operations
    def create_event(self, event_data: Dict[str, Any]) -> str:
        """Create a new event and return its ID."""
        raise NotImplementedError

    def find_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Find an event by ID."""
        raise NotImplementedError

    def find_event_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find the most recent event for a client email."""
        raise NotImplementedError

    def update_event(self, event_id: str, **fields: Any) -> Dict[str, Any]:
        """Update event fields."""
        raise NotImplementedError

    # Task operations (HIL)
    def create_task(
        self,
        event_id: str,
        task_type: str,
        title: str,
        payload: Dict[str, Any],
        **kwargs,
    ) -> str:
        """Create a HIL task."""
        raise NotImplementedError

    def create_message_approval(
        self,
        event_id: str,
        client_name: str,
        client_email: str,
        draft_message: str,
        subject: Optional[str] = None,
    ) -> str:
        """Create a message approval task."""
        raise NotImplementedError

    # Room operations
    def get_rooms(self, date_iso: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get available rooms."""
        raise NotImplementedError

    # Extended event operations for workflow steps
    def update_event_date(
        self,
        event_id: str,
        date_iso: str,
        *,
        confirmed: bool = False,
    ) -> Dict[str, Any]:
        """Update event date (Step 2 - Date Confirmation)."""
        raise NotImplementedError

    def update_event_room(
        self,
        event_id: str,
        room_id: str,
        *,
        status: str = "room_selected",
    ) -> Dict[str, Any]:
        """Update event room selection (Step 3 - Room Availability)."""
        raise NotImplementedError

    def update_event_billing(
        self,
        event_id: str,
        products: List[Dict[str, Any]],
        total: float,
    ) -> Dict[str, Any]:
        """Update event billing/products (Step 4 - Offer)."""
        raise NotImplementedError

    def append_audit(
        self,
        event_id: str,
        action: str,
        details: Dict[str, Any],
    ) -> None:
        """Append an audit trail entry."""
        raise NotImplementedError

    def get_context_snapshot(
        self,
        email: str,
    ) -> Dict[str, Any]:
        """Get conversation context for AI processing."""
        raise NotImplementedError


# =============================================================================
# JSON Adapter (wraps existing database.py)
# =============================================================================

class JSONDatabaseAdapter(DatabaseAdapter):
    """
    Adapter that wraps the existing JSON file-based database.

    This preserves current behavior when OE_INTEGRATION_MODE=json.
    """

    def __init__(self, db_path: Optional["Path"] = None):
        super().__init__()
        self._db_path = db_path
        self._db = None

    def initialize(self) -> None:
        if self._initialized:
            return

        from pathlib import Path
        from backend.workflows.io import database

        if self._db_path is None:
            self._db_path = Path(__file__).resolve().parents[3] / "events_database.json"

        self._db_module = database
        self._initialized = True
        logger.info("JSON database adapter initialized: %s", self._db_path)

    def _load(self) -> Dict[str, Any]:
        """Load database from disk."""
        self.initialize()
        return self._db_module.load_db(self._db_path)

    def _save(self, db: Dict[str, Any]) -> None:
        """Save database to disk."""
        self.initialize()
        self._db_module.save_db(db, self._db_path)

    def upsert_client(
        self,
        email: str,
        name: Optional[str] = None,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.initialize()
        db = self._load()
        client = self._db_module.upsert_client(db, email, name)
        if company:
            client["profile"]["org"] = company
        if phone:
            client["profile"]["phone"] = phone
        self._save(db)
        return client

    def create_event(self, event_data: Dict[str, Any]) -> str:
        self.initialize()
        db = self._load()
        event_id = self._db_module.create_event_entry(db, event_data)
        self._save(db)
        return event_id

    def find_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        self.initialize()
        db = self._load()
        idx = self._db_module.find_event_idx_by_id(db, event_id)
        if idx is not None:
            return db["events"][idx]
        return None

    def find_event_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        self.initialize()
        db = self._load()
        return self._db_module.last_event_for_email(db, email.lower())

    def update_event(self, event_id: str, **fields: Any) -> Dict[str, Any]:
        self.initialize()
        db = self._load()
        idx = self._db_module.find_event_idx_by_id(db, event_id)
        if idx is None:
            raise ValueError(f"Event {event_id} not found")

        event = db["events"][idx]
        self._db_module.update_event_metadata(event, **fields)
        self._save(db)
        return event

    def create_task(
        self,
        event_id: str,
        task_type: str,
        title: str,
        payload: Dict[str, Any],
        **kwargs,
    ) -> str:
        """Create a task in JSON format."""
        self.initialize()
        from backend.workflows.io.tasks import create_task

        db = self._load()
        task_id = create_task(
            db,
            event_id=event_id,
            task_type=task_type,
            title=title,
            payload=payload,
            **kwargs,
        )
        self._save(db)
        return task_id

    def create_message_approval(
        self,
        event_id: str,
        client_name: str,
        client_email: str,
        draft_message: str,
        subject: Optional[str] = None,
    ) -> str:
        """Create a message approval task."""
        return self.create_task(
            event_id=event_id,
            task_type="message_approval",
            title=f"Approve message to {client_name}",
            payload={
                "action": "approve_message",
                "draft_message": draft_message,
                "recipient_email": client_email,
                "subject": subject,
            },
            client_name=client_name,
        )

    def get_rooms(self, date_iso: Optional[str] = None) -> List[Dict[str, Any]]:
        self.initialize()
        room_names = self._db_module.load_rooms()
        return [{"name": name, "id": name} for name in room_names]

    def update_event_date(
        self,
        event_id: str,
        date_iso: str,
        *,
        confirmed: bool = False,
    ) -> Dict[str, Any]:
        self.initialize()
        db = self._load()
        idx = self._db_module.find_event_idx_by_id(db, event_id)
        if idx is None:
            raise ValueError(f"Event {event_id} not found")

        event = db["events"][idx]
        self._db_module.update_event_date(event, date_iso, confirmed=confirmed)
        self._save(db)
        return event

    def update_event_room(
        self,
        event_id: str,
        room_id: str,
        *,
        status: str = "room_selected",
    ) -> Dict[str, Any]:
        self.initialize()
        db = self._load()
        idx = self._db_module.find_event_idx_by_id(db, event_id)
        if idx is None:
            raise ValueError(f"Event {event_id} not found")

        event = db["events"][idx]
        self._db_module.update_event_room(
            event,
            selected_room=room_id,
            status=status,
        )
        self._save(db)
        return event

    def update_event_billing(
        self,
        event_id: str,
        products: List[Dict[str, Any]],
        total: float,
    ) -> Dict[str, Any]:
        self.initialize()
        db = self._load()
        idx = self._db_module.find_event_idx_by_id(db, event_id)
        if idx is None:
            raise ValueError(f"Event {event_id} not found")

        event = db["events"][idx]
        self._db_module.update_event_billing(event, products=products, total=total)
        self._save(db)
        return event

    def append_audit(
        self,
        event_id: str,
        action: str,
        details: Dict[str, Any],
    ) -> None:
        self.initialize()
        db = self._load()
        idx = self._db_module.find_event_idx_by_id(db, event_id)
        if idx is None:
            raise ValueError(f"Event {event_id} not found")

        event = db["events"][idx]
        self._db_module.append_audit_entry(event, action, details)
        self._save(db)

    def get_context_snapshot(
        self,
        email: str,
    ) -> Dict[str, Any]:
        self.initialize()
        db = self._load()
        client = db.get("clients", {}).get(email.lower())
        if not client:
            return {}
        return self._db_module.context_snapshot(db, client, email.lower())


# =============================================================================
# Supabase Adapter
# =============================================================================

class SupabaseDatabaseAdapter(DatabaseAdapter):
    """
    Adapter that uses Supabase for storage.

    Activated when OE_INTEGRATION_MODE=supabase.
    """

    def __init__(self):
        super().__init__()
        self._supabase_module = None

    def initialize(self) -> None:
        if self._initialized:
            return

        from . import supabase_adapter
        self._supabase_module = supabase_adapter

        # Initialize Supabase client
        self._supabase_module.get_supabase_client()
        self._initialized = True
        logger.info("Supabase database adapter initialized")

    def upsert_client(
        self,
        email: str,
        name: Optional[str] = None,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.initialize()
        return self._supabase_module.upsert_client(email, name, company, phone)

    def create_event(self, event_data: Dict[str, Any]) -> str:
        self.initialize()
        return self._supabase_module.create_event_entry(event_data)

    def find_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        self.initialize()
        return self._supabase_module.find_event_by_id(event_id)

    def find_event_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        self.initialize()
        return self._supabase_module.find_event_by_email(email)

    def update_event(self, event_id: str, **fields: Any) -> Dict[str, Any]:
        self.initialize()
        return self._supabase_module.update_event_metadata(event_id, **fields)

    def create_task(
        self,
        event_id: str,
        task_type: str,
        title: str,
        payload: Dict[str, Any],
        **kwargs,
    ) -> str:
        self.initialize()
        return self._supabase_module.create_hil_task(
            event_id=event_id,
            task_type=task_type,
            title=title,
            description=kwargs.get("description", ""),
            payload=payload,
            client_name=kwargs.get("client_name"),
            priority=kwargs.get("priority", "high"),
        )

    def create_message_approval(
        self,
        event_id: str,
        client_name: str,
        client_email: str,
        draft_message: str,
        subject: Optional[str] = None,
    ) -> str:
        self.initialize()
        return self._supabase_module.create_message_approval(
            event_id=event_id,
            client_name=client_name,
            client_email=client_email,
            draft_message=draft_message,
            subject=subject,
        )

    def get_rooms(self, date_iso: Optional[str] = None) -> List[Dict[str, Any]]:
        self.initialize()
        return self._supabase_module.get_rooms(date_iso)

    def update_event_date(
        self,
        event_id: str,
        date_iso: str,
        *,
        confirmed: bool = False,
    ) -> Dict[str, Any]:
        self.initialize()
        return self._supabase_module.update_event_date(event_id, date_iso)

    def update_event_room(
        self,
        event_id: str,
        room_id: str,
        *,
        status: str = "room_selected",
    ) -> Dict[str, Any]:
        self.initialize()
        return self._supabase_module.update_event_room(
            event_id,
            selected_room=room_id,
            status=status,
        )

    def update_event_billing(
        self,
        event_id: str,
        products: List[Dict[str, Any]],
        total: float,
    ) -> Dict[str, Any]:
        """Update billing in Supabase - creates/updates offer with line items."""
        self.initialize()
        # In Supabase, billing is stored as an offer with line items
        return self._supabase_module.create_offer(
            event_id=event_id,
            line_items=products,
            total_amount=total,
        )

    def append_audit(
        self,
        event_id: str,
        action: str,
        details: Dict[str, Any],
    ) -> None:
        """Append audit entry - in Supabase this could be a separate audit table."""
        self.initialize()
        # For now, audit entries are stored in event notes or a dedicated table
        # This is a placeholder - full implementation depends on Supabase schema
        logger.debug("Audit entry for %s: %s - %s", event_id, action, details)

    def get_context_snapshot(
        self,
        email: str,
    ) -> Dict[str, Any]:
        """Get context for AI - combines client and event data from Supabase."""
        self.initialize()
        event = self._supabase_module.find_event_by_email(email)
        if not event:
            return {}
        # Return in a format compatible with the workflow
        return {
            "event": event,
            "last_message": event.get("event_data", {}).get("last_message"),
        }


# =============================================================================
# Adapter Factory
# =============================================================================

_adapter_instance: Optional[DatabaseAdapter] = None


def get_database_adapter() -> DatabaseAdapter:
    """
    Get the appropriate database adapter based on configuration.

    Returns:
        DatabaseAdapter instance (JSON or Supabase)
    """
    global _adapter_instance

    if _adapter_instance is not None:
        return _adapter_instance

    if is_integration_mode():
        logger.info("Using Supabase database adapter")
        _adapter_instance = SupabaseDatabaseAdapter()
    else:
        logger.info("Using JSON database adapter")
        _adapter_instance = JSONDatabaseAdapter()

    return _adapter_instance


def reset_adapter() -> None:
    """Reset the adapter instance (for testing)."""
    global _adapter_instance
    _adapter_instance = None


def is_using_supabase() -> bool:
    """Check if currently using Supabase adapter."""
    return is_integration_mode()


def is_using_json() -> bool:
    """Check if currently using JSON adapter."""
    return not is_integration_mode()


# =============================================================================
# Convenience Export
# =============================================================================

class _DatabaseProxy:
    """
    Proxy that forwards calls to the current adapter.

    Allows usage like:
        from backend.workflows.io.integration.adapter import db
        db.upsert_client(email, name)
    """

    def __getattr__(self, name: str) -> Any:
        adapter = get_database_adapter()
        return getattr(adapter, name)


# Global proxy instance
db = _DatabaseProxy()
