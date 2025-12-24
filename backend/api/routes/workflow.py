"""
MODULE: backend/api/routes/workflow.py
PURPOSE: Workflow status and configuration API endpoints.

ROUTES:
    GET  /api/workflow/health      - Health check for workflow integration
    GET  /api/workflow/hil-status  - Get HIL toggle status

MIGRATION: Extracted from main.py in Phase C refactoring (2025-12-18).
"""

from fastapi import APIRouter

from backend.workflow_email import DB_PATH as WF_DB_PATH
from backend.workflows.io.integration.config import is_hil_all_replies_enabled

router = APIRouter(tags=["workflow"])


@router.get("/api/workflow/health")
async def workflow_health():
    """Minimal health check for workflow integration."""
    return {"db_path": str(WF_DB_PATH), "ok": True}


@router.get("/api/workflow/hil-status")
async def get_hil_status():
    """Get the HIL toggle status for AI reply approval.

    Returns whether HIL mode is enabled (all AI replies require manager approval).

    To toggle this setting, use:
        POST /api/config/hil-mode {"enabled": true/false}

    To get detailed status including source (database/environment/default):
        GET /api/config/hil-mode
    """
    return {
        "hil_all_replies_enabled": is_hil_all_replies_enabled(),
    }
