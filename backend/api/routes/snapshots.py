"""
MODULE: backend/api/routes/snapshots.py
PURPOSE: Snapshot API endpoints for persistent info page links.

ROUTES:
    GET  /api/snapshots/{snapshot_id}       - Get full snapshot by ID
    GET  /api/snapshots/{snapshot_id}/data  - Get just the data payload
    GET  /api/snapshots                     - List available snapshots

DESCRIPTION:
    Snapshots contain page data (rooms, products, etc.) that was captured
    at a specific point in time, allowing clients to revisit older links
    in the conversation without data changing.

MIGRATION: Extracted from main.py in Phase C refactoring (2025-12-18).
"""

from fastapi import APIRouter
from typing import Optional

from backend.utils.page_snapshots import (
    get_snapshot,
    get_snapshot_data,
    list_snapshots,
)

router = APIRouter(tags=["snapshots"])


@router.get("/api/snapshots/{snapshot_id}")
async def get_snapshot_endpoint(snapshot_id: str):
    """
    Retrieve a stored snapshot by ID.

    Snapshots contain page data (rooms, products, etc.) that was captured
    at a specific point in time, allowing clients to revisit older links.
    """
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        return {"error": "Snapshot not found or expired", "snapshot_id": snapshot_id}
    return snapshot


@router.get("/api/snapshots/{snapshot_id}/data")
async def get_snapshot_data_endpoint(snapshot_id: str):
    """
    Retrieve just the data payload from a snapshot.

    Use this endpoint when you only need the data, not the metadata.
    """
    data = get_snapshot_data(snapshot_id)
    if data is None:
        return {"error": "Snapshot not found or expired", "snapshot_id": snapshot_id}
    return {"snapshot_id": snapshot_id, "data": data}


@router.get("/api/snapshots")
async def list_snapshots_endpoint(
    type: Optional[str] = None,
    event_id: Optional[str] = None,
    limit: int = 50,
):
    """
    List available snapshots, optionally filtered by type or event_id.

    Returns metadata only (not full data) for efficiency.
    """
    return {
        "snapshots": list_snapshots(snapshot_type=type, event_id=event_id, limit=limit)
    }
