"""
MODULE: backend/api/routes/debug.py
PURPOSE: Debug and tracing API endpoints.

ROUTES:
    GET  /api/debug/threads/{thread_id}              - Get full trace for thread
    GET  /api/debug/threads/{thread_id}/timeline     - Get timeline events only
    GET  /api/debug/threads/{thread_id}/timeline/download - Download timeline JSON
    GET  /api/debug/threads/{thread_id}/timeline/text    - Download timeline as text
    GET  /api/debug/threads/{thread_id}/report       - Generate debug report
    GET  /api/debug/threads/{thread_id}/llm-diagnosis - LLM-optimized diagnosis
    GET  /api/debug/live                             - List active threads with live logs
    GET  /api/debug/threads/{thread_id}/live         - Get live log content

NOTE: These routes are conditionally registered based on DEBUG_TRACE_ENABLED.
      When tracing is disabled, stub endpoints return 404.

MIGRATION: Extracted from main.py in Phase C refactoring (2025-12-18).
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from typing import List, Optional

from backend.api.debug import (
    debug_get_trace,
    debug_get_timeline,
    debug_generate_report,
    resolve_timeline_path,
    render_arrow_log,
    debug_llm_diagnosis,
)
from backend.debug.settings import is_trace_enabled

router = APIRouter(tags=["debug"])

DEBUG_TRACE_ENABLED = is_trace_enabled()


def _parse_kind_filter(raw: Optional[str]) -> Optional[List[str]]:
    """Parse comma-separated kind filter string into list."""
    if not raw:
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


if DEBUG_TRACE_ENABLED:

    @router.get("/api/debug/threads/{thread_id}")
    async def get_debug_thread_trace(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
        as_of_ts: Optional[float] = Query(None),
    ):
        """Get full debug trace for a thread."""
        return debug_get_trace(
            thread_id,
            granularity=granularity,
            kinds=_parse_kind_filter(kinds),
            as_of_ts=as_of_ts,
        )

    @router.get("/api/debug/threads/{thread_id}/timeline")
    async def get_debug_thread_timeline(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
        as_of_ts: Optional[float] = Query(None),
    ):
        """Get timeline events for a thread."""
        return debug_get_timeline(
            thread_id,
            granularity=granularity,
            kinds=_parse_kind_filter(kinds),
            as_of_ts=as_of_ts,
        )

    @router.get("/api/debug/threads/{thread_id}/timeline/download")
    async def download_debug_thread_timeline(thread_id: str):
        """Download timeline as JSONL file."""
        path = resolve_timeline_path(thread_id)
        if not path:
            raise HTTPException(status_code=404, detail="Timeline not available")
        safe_id = thread_id.replace("/", "_").replace("\\", "_")
        filename = f"openevent_timeline_{safe_id}.jsonl"
        return FileResponse(path, media_type="application/json", filename=filename)

    @router.get("/api/debug/threads/{thread_id}/timeline/text")
    async def download_debug_thread_timeline_text(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
    ):
        """Download timeline as human-readable text."""
        return render_arrow_log(thread_id, granularity=granularity, kinds=_parse_kind_filter(kinds))

    @router.get("/api/debug/threads/{thread_id}/report")
    async def download_debug_thread_report(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
        persist: bool = Query(False),
    ):
        """Generate and optionally persist a debug report."""
        body, saved_path = debug_generate_report(
            thread_id,
            granularity=granularity,
            kinds=_parse_kind_filter(kinds),
            persist=persist,
        )
        headers = {}
        if saved_path:
            headers["X-Debug-Report-Path"] = saved_path
        return PlainTextResponse(content=body, headers=headers)

    @router.get("/api/debug/threads/{thread_id}/llm-diagnosis")
    async def get_debug_llm_diagnosis(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
    ):
        """Get LLM-optimized diagnosis for debugging."""
        return debug_llm_diagnosis(
            thread_id,
            granularity=granularity,
            kinds=_parse_kind_filter(kinds),
        )

    @router.get("/api/debug/live")
    async def list_live_logs():
        """List all active thread IDs with live logs."""
        from backend.debug import live_log

        threads = live_log.list_active_logs()
        return {
            "active_threads": threads,
            "log_dir": str(live_log.ROOT),
            "watch_command": f"tail -f {live_log.ROOT}/<thread_id>.log",
        }

    @router.get("/api/debug/threads/{thread_id}/live")
    async def get_live_log(thread_id: str):
        """Get the live log content for a thread."""
        from backend.debug import live_log

        path = live_log.get_log_path(thread_id)
        if not path:
            raise HTTPException(status_code=404, detail="Live log not found for this thread")
        try:
            content = path.read_text(encoding="utf-8")
            return PlainTextResponse(content=content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

else:
    # Stub endpoints when tracing is disabled

    @router.get("/api/debug/threads/{thread_id}")
    async def get_debug_thread_trace_disabled(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
        as_of_ts: Optional[float] = Query(None),
    ):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")

    @router.get("/api/debug/threads/{thread_id}/timeline")
    async def get_debug_thread_timeline_disabled(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
        as_of_ts: Optional[float] = Query(None),
    ):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")

    @router.get("/api/debug/threads/{thread_id}/timeline/download")
    async def download_debug_thread_timeline_disabled(thread_id: str):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")

    @router.get("/api/debug/threads/{thread_id}/timeline/text")
    async def download_debug_thread_timeline_text_disabled(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
    ):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")

    @router.get("/api/debug/threads/{thread_id}/report")
    async def download_debug_thread_report_disabled(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
        persist: bool = Query(False),
    ):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")

    @router.get("/api/debug/threads/{thread_id}/llm-diagnosis")
    async def get_debug_llm_diagnosis_disabled(
        thread_id: str,
        granularity: str = Query("logic"),
        kinds: Optional[str] = Query(None),
    ):
        raise HTTPException(status_code=404, detail="Debug tracing disabled")
