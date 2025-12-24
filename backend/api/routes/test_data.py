"""
MODULE: backend/api/routes/test_data.py
PURPOSE: Test data and Q&A API endpoints for development pages.

ROUTES:
    GET  /api/test-data/rooms              - Room availability data
    GET  /api/test-data/catering           - Catering menus catalog
    GET  /api/test-data/catering/{slug}    - Specific menu details
    GET  /api/test-data/qna                - Legacy Q&A endpoint
    GET  /api/qna                          - Universal Q&A endpoint

DESCRIPTION:
    These endpoints serve test data for development pages and provide
    Q&A functionality using the existing workflow Q&A engine.

MIGRATION: Extracted from main.py in Phase C refactoring (2025-12-18).
"""

from fastapi import APIRouter, HTTPException, Request
from pathlib import Path
from typing import Optional

from backend.utils.test_data_providers import (
    get_all_catering_menus,
    get_catering_menu_details,
    get_qna_items,
    get_rooms_for_display,
)
from backend.workflow_email import (
    DB_PATH as WF_DB_PATH,
    load_db as wf_load_db,
)

router = APIRouter(tags=["test-data"])


@router.get("/api/test-data/rooms")
async def get_rooms_data(date: Optional[str] = None, capacity: Optional[str] = None):
    """Serve room availability data for test pages."""
    rooms = get_rooms_for_display(date, capacity)
    return rooms


@router.get("/api/test-data/catering")
async def get_catering_catalog(
    month: Optional[str] = None,
    vegetarian: Optional[str] = None,
    vegan: Optional[str] = None,
    courses: Optional[str] = None,
    wine_pairing: Optional[str] = None,
):
    """Serve catering menus for catalog page with dynamic filtering."""
    filters = {
        "month": month,
        "vegetarian": vegetarian == "true" if vegetarian else None,
        "vegan": vegan == "true" if vegan else None,
        "courses": int(courses) if courses and courses.isdigit() else None,
        "wine_pairing": wine_pairing == "true" if wine_pairing else None,
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}
    menus = get_all_catering_menus(filters=filters)
    return menus


@router.get("/api/test-data/catering/{menu_slug}")
async def get_catering_data(menu_slug: str, room: Optional[str] = None, date: Optional[str] = None):
    """Serve specific catering menu data for test pages."""
    menu = get_catering_menu_details(menu_slug)
    if not menu:
        raise HTTPException(status_code=404, detail="Menu not found")

    menu["context"] = {
        "room": room,
        "date": date,
    }
    return menu


@router.get("/api/qna")
async def universal_qna(request: Request):
    """Universal Q&A endpoint - accepts any parameters, uses existing Q&A engine."""
    from backend.workflows.qna.engine import build_structured_qna_result
    from backend.workflows.common.types import WorkflowState, IncomingMessage as Message

    # Get all query params
    params = dict(request.query_params)
    category = params.get("category", "general")

    # Build q_values from query params for Q&A engine
    q_values = {}

    # Date/month parameters
    if params.get("date"):
        q_values["date"] = params["date"]
    if params.get("month"):
        q_values["date_pattern"] = params["month"]

    # Capacity parameters
    if params.get("capacity"):
        try:
            q_values["n_exact"] = int(params["capacity"])
        except ValueError:
            pass

    # Room parameters
    if params.get("room"):
        q_values["room"] = params["room"]

    # Product attributes
    product_attributes = []
    if params.get("vegetarian") == "true":
        product_attributes.append("vegetarian")
    if params.get("vegan") == "true":
        product_attributes.append("vegan")
    if params.get("wine_pairing") == "true":
        product_attributes.append("wine pairing")
    if params.get("courses"):
        product_attributes.append(f"{params['courses']}-course")
    if product_attributes:
        q_values["product_attributes"] = product_attributes

    # Build extraction structure
    qna_extraction = {
        "qna_subtype": category,
        "q_values": q_values,
        "msg_type": "event",
        "qna_intent": "select_dependent"
    }

    # Create minimal state for Q&A engine
    try:
        db = wf_load_db()
    except Exception:
        db = {}

    state = WorkflowState(
        client_id="qna-page",
        message=Message(
            msg_id="qna",
            subject="",
            body="",
            from_name=None,
            from_email=None,
            ts=None
        ),
        db_path=Path(WF_DB_PATH),
        db=db,
        user_info={},
        event_entry={},
        intent=None,
        confidence=1.0
    )
    state.extras["qna_extraction"] = qna_extraction

    # Use existing Q&A engine
    try:
        result = build_structured_qna_result(state, qna_extraction)

        # Fetch legacy items to support FAQ page
        legacy_data = get_qna_items(category, filters=q_values)

        return {
            "query": params,
            "result_type": category,
            "filters_applied": q_values,
            "data": result.action_payload if result and result.handled else {},
            "items": legacy_data.get("items", []),
            "categories": legacy_data.get("categories", []),
            "menus": legacy_data.get("menus", []),
            "body_markdown": result.body_markdown if result and result.handled else "No results found",
            "handled": result.handled if result else False,
            "success": True
        }
    except Exception as e:
        import traceback
        return {
            "query": params,
            "result_type": category,
            "filters_applied": q_values,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "success": False
        }


@router.get("/api/test-data/qna")
async def get_qna_data(
    category: Optional[str] = None,
    month: Optional[str] = None,
    vegetarian: Optional[str] = None,
    vegan: Optional[str] = None,
    courses: Optional[str] = None,
    wine_pairing: Optional[str] = None,
    date: Optional[str] = None,
    capacity: Optional[str] = None,
):
    """Legacy endpoint - kept for backwards compatibility during migration."""
    filters = {
        "month": month,
        "vegetarian": vegetarian == "true" if vegetarian else None,
        "vegan": vegan == "true" if vegan else None,
        "courses": int(courses) if courses and courses.isdigit() else None,
        "wine_pairing": wine_pairing == "true" if wine_pairing else None,
        "date": date,
        "capacity": int(capacity) if capacity and capacity.isdigit() else None,
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}
    return get_qna_items(category, filters=filters)
