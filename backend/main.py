# CRITICAL: Clear bytecode caches on startup
# This prevents stale .pyc files from causing "unexpected keyword argument" errors on reload
import sys
import os
import shutil
import importlib
from pathlib import Path as _Path
sys.dont_write_bytecode = True  # Prevent new cache writes

# Clear pycache directories
_backend_dir = _Path(__file__).parent
for _cache_dir in _backend_dir.rglob("__pycache__"):
    try:
        shutil.rmtree(_cache_dir)
    except Exception:
        pass

# Invalidate import caches (but don't delete already-loaded modules as that breaks uvicorn)
importlib.invalidate_caches()

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
# NOTE: FileResponse, PlainTextResponse moved to routes/debug.py
from contextlib import asynccontextmanager
from pydantic import BaseModel
import uuid
import re
import atexit
import subprocess
import socket
import signal
import time
import webbrowser
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path
# NOTE: domain, conversation_manager imports moved to routes/messages.py
from backend.legacy.session_store import active_conversations  # Used in root endpoint
# NOTE: adapter imports moved to routes/messages.py
# NOTE: workflow imports moved to routes/messages.py
from backend.utils import json_io

os.environ.setdefault("AGENT_MODE", os.environ.get("AGENT_MODE_DEFAULT", "openai"))

from backend.workflow_email import DB_PATH as WF_DB_PATH
# NOTE: process_msg, load_db, save_db moved to routes/messages.py
# NOTE: Most debug imports moved to routes/debug.py
from backend.api.debug import debug_generate_report  # Still used in _persist_debug_reports
from backend.debug.settings import is_trace_enabled
from backend.debug.trace import BUS
from backend.api.routes import (
    tasks_router,
    events_router,
    config_router,
    clients_router,
    debug_router,
    snapshots_router,
    test_data_router,
    workflow_router,
    messages_router,
    emails_router,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager to handle startup and shutdown events."""
    # --- Startup: clear Python cache to prevent stale bytecode issues ---
    # This runs regardless of how the app is started (uvicorn direct, --reload, etc.)
    # and prevents errors like `__init__() got an unexpected keyword argument 'draft'`.
    backend_dir = Path(__file__).parent
    cleared = 0
    for cache_dir in backend_dir.rglob("__pycache__"):
        try:
            import shutil
            shutil.rmtree(cache_dir)
            cleared += 1
        except Exception:
            pass
    if cleared:
        print(f"[Backend] Startup: cleared {cleared} __pycache__ directories")
    
    yield
    # --- Shutdown logic (if any) can go here ---

app = FastAPI(title="AI Event Manager", lifespan=lifespan)

# Include route modules (Phase C refactoring - complete)
app.include_router(tasks_router)
app.include_router(events_router)
app.include_router(config_router)
app.include_router(clients_router)
app.include_router(debug_router)
app.include_router(snapshots_router)
app.include_router(test_data_router)
app.include_router(workflow_router)
app.include_router(messages_router)
app.include_router(emails_router)

DEBUG_TRACE_ENABLED = is_trace_enabled()

# NOTE: GUI_ADAPTER moved to routes/messages.py

# CORS for frontend - configurable origins for security
# Default allows localhost:3000 for local development
# Set ALLOWED_ORIGINS env var for production (comma-separated list)
_raw_allowed_origins = os.getenv("ALLOWED_ORIGINS")
if _raw_allowed_origins:
    allowed_origins = [origin.strip() for origin in _raw_allowed_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # Dev default: allow any localhost origin, regardless of port (3000/3001/etc).
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# CENTRALIZED EVENTS DATABASE - use canonical path from workflow_email
EVENTS_FILE = str(WF_DB_PATH)  # For backwards compat in any string contexts
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "atelier-ai-frontend"
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "3000"))
_frontend_process: Optional[subprocess.Popen] = None
DEV_DIR = Path(__file__).resolve().parents[1] / ".dev"
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")


def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def _pids_listening_on_tcp_port(port: int) -> List[int]:
    """Return PIDs listening on localhost TCP port (best effort; macOS/Linux)."""
    import shutil

    if not shutil.which("lsof"):
        return []
    try:
        output = subprocess.check_output(  # nosec B603,B607 (dev-only port cleanup)
            ["lsof", "-nP", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    pids: List[int] = []
    for line in output.decode().splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            pids.append(int(value))
        except ValueError:
            continue
    return sorted(set(pids))


def _terminate_pid(pid: int, timeout_s: float = 3.0) -> None:
    """Terminate a pid (TERM then KILL), best effort."""
    if pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _pid_exists(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def _ensure_backend_port_free(port: int) -> None:
    if not _is_port_in_use(port):
        return
    if os.getenv("AUTO_FREE_BACKEND_PORT", "1") != "1":
        raise RuntimeError(
            f"Port {port} is already in use. Stop the existing process or set AUTO_FREE_BACKEND_PORT=1."
        )
    pids = _pids_listening_on_tcp_port(port)
    if not pids:
        raise RuntimeError(
            f"Port {port} is already in use, but no PID could be discovered (missing lsof?)."
        )
    print(f"[Backend][WARN] Port {port} is in use; terminating listeners: {', '.join(map(str, pids))}")
    for pid in pids:
        _terminate_pid(pid)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not _is_port_in_use(port):
            return
        time.sleep(0.1)
    remaining = _pids_listening_on_tcp_port(port)
    raise RuntimeError(
        f"Port {port} is still in use after attempting cleanup (remaining PIDs: {remaining or 'unknown'})."
    )


def _write_pidfile(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    except Exception as exc:  # pragma: no cover - best effort
        print(f"[Backend][WARN] Failed to write pidfile {path}: {exc}")


def _cleanup_pidfile(path: Path) -> None:
    try:
        if not path.exists():
            return
        existing = path.read_text(encoding="utf-8").strip()
        if existing and existing != str(os.getpid()):
            return
        path.unlink(missing_ok=True)
    except Exception:  # pragma: no cover - best effort
        return


def _is_frontend_healthy(port: int, timeout: float = 2.0) -> bool:
    """Check if frontend returns a healthy response (not 500 error)."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(f"http://localhost:{port}/", method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500  # 404 is OK (might be a different route), 500 is not
    except Exception:
        return False


def _kill_unhealthy_frontend() -> None:
    """Kill any existing frontend processes and clear cache."""
    import shutil
    print("[Frontend] Killing unhealthy frontend and clearing cache...")
    # Kill next dev processes
    subprocess.run(["pkill", "-f", "next dev"], capture_output=True)
    time.sleep(0.5)
    # Clear the .next cache which often causes 500 errors
    next_cache = FRONTEND_DIR / ".next"
    if next_cache.exists():
        try:
            shutil.rmtree(next_cache)
            print("[Frontend] Cleared .next cache")
        except Exception as e:
            print(f"[Frontend][WARN] Could not clear .next cache: {e}")
    time.sleep(0.5)


def _launch_frontend() -> Optional[subprocess.Popen]:
    if os.getenv("AUTO_LAUNCH_FRONTEND", "1") != "1":
        return None
    frontend_pidfile = DEV_DIR / "frontend.pid"
    try:
        if frontend_pidfile.exists():
            existing = frontend_pidfile.read_text(encoding="utf-8").strip()
            existing_pid = int(existing) if existing else None
            if (
                existing_pid
                and _pid_exists(existing_pid)
                and _is_port_in_use(FRONTEND_PORT)
                and _is_frontend_healthy(FRONTEND_PORT)
            ):
                print(
                    f"[Frontend] Reusing existing frontend process (pid={existing_pid}) on http://localhost:{FRONTEND_PORT}"
                )
                return None
            frontend_pidfile.unlink(missing_ok=True)
    except Exception:
        pass
    if _is_port_in_use(FRONTEND_PORT):
        # Port is in use - check if it's actually healthy
        if _is_frontend_healthy(FRONTEND_PORT):
            print(f"[Frontend] Port {FRONTEND_PORT} already in use – frontend is healthy.")
            return None
        else:
            print(f"[Frontend][WARN] Port {FRONTEND_PORT} in use but returning errors!")
            if os.getenv("AUTO_FIX_FRONTEND", "1") == "1":
                _kill_unhealthy_frontend()
                # Now port should be free, continue to launch
            else:
                print(f"[Frontend][WARN] Set AUTO_FIX_FRONTEND=1 to auto-fix, or run:")
                print(f"[Frontend][WARN]   pkill -f 'next dev' && rm -rf atelier-ai-frontend/.next")
                return None
    if not FRONTEND_DIR.exists():
        print(f"[Frontend][WARN] Directory {FRONTEND_DIR} not found; skipping auto-launch.")
        return None
    if not (FRONTEND_DIR / "package.json").exists():
        print(f"[Frontend][WARN] No package.json in {FRONTEND_DIR}; skipping auto-launch.")
        return None
    cmd = ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", str(FRONTEND_PORT)]
    try:
        env = os.environ.copy()
        env.setdefault("NEXT_PUBLIC_BACKEND_BASE", f"http://localhost:{BACKEND_PORT}")
        proc = subprocess.Popen(cmd, cwd=str(FRONTEND_DIR), env=env, start_new_session=True)
        try:
            DEV_DIR.mkdir(parents=True, exist_ok=True)
            frontend_pidfile.write_text(f"{proc.pid}\n", encoding="utf-8")
        except Exception:
            pass
        print(f"[Frontend] npm dev server starting on http://localhost:{FRONTEND_PORT}")
        return proc
    except FileNotFoundError:
        print("[Frontend][WARN] npm not found on PATH; skipping auto-launch.")
    except Exception as exc:
        print(f"[Frontend][ERROR] Failed to launch npm dev server: {exc}")
    return None


def _open_browser_when_ready() -> None:
    if os.getenv("AUTO_OPEN_FRONTEND", "1") != "1":
        return
    target_url = f"http://localhost:{FRONTEND_PORT}"
    debug_url = f"{target_url}/debug"
    for attempt in range(120):
        if _is_port_in_use(FRONTEND_PORT):
            try:
                webbrowser.open_new(target_url)
                if os.getenv("AUTO_OPEN_DEBUG_PANEL", "1") == "1":
                    webbrowser.open_new_tab(debug_url)
            except Exception as exc:  # pragma: no cover - environment dependent
                print(f"[Frontend][WARN] Unable to open browser automatically: {exc}")
            else:
                print(f"[Frontend] Opened browser window at {target_url}")
                if os.getenv("AUTO_OPEN_DEBUG_PANEL", "1") == "1":
                    print(f"[Frontend] Opened debug panel at {debug_url}")
            return
        time.sleep(0.5)
    print(f"[Frontend][WARN] Frontend not reachable on {target_url} after waiting 60s; skipping auto-open.")


def load_events_database():
    """Load all events from the database file"""
    if WF_DB_PATH.exists():
        with open(WF_DB_PATH, 'r', encoding='utf-8') as f:
            return json_io.load(f)
    return {"events": []}

def save_events_database(database):
    """Save all events to the database file"""
    with open(WF_DB_PATH, 'w', encoding='utf-8') as f:
        json_io.dump(database, f, indent=2, ensure_ascii=False)


# NOTE: Message routes moved to backend/api/routes/messages.py
# NOTE: Task routes (/api/tasks/*) moved to backend/api/routes/tasks.py
# NOTE: Client routes (/api/client/*) moved to backend/api/routes/clients.py
# NOTE: Debug routes (/api/debug/*) moved to backend/api/routes/debug.py
# NOTE: Test data routes (/api/test-data/*) moved to backend/api/routes/test_data.py
# NOTE: Q&A routes (/api/qna) moved to backend/api/routes/test_data.py
# NOTE: Snapshot routes (/api/snapshots/*) moved to backend/api/routes/snapshots.py
# NOTE: Workflow routes (/api/workflow/*) moved to backend/api/routes/workflow.py
# NOTE: Config routes (/api/config/*) moved to backend/api/routes/config.py
# NOTE: Deposit payment endpoints moved to backend/api/routes/events.py
# NOTE: /api/events routes moved to backend/api/routes/events.py


@app.get("/")
async def root():
    database = load_events_database()
    return {
        "status": "AI Event Manager Running",
        "active_conversations": len(active_conversations),
        "total_saved_events": len(database["events"])
    }


def _stop_frontend_process() -> None:
    global _frontend_process
    proc = _frontend_process
    if not proc:
        return
    try:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                proc.terminate()
            proc.wait(timeout=5)
    except Exception:
        try:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()
        except Exception:
            pass
    finally:
        try:
            pidfile = DEV_DIR / "frontend.pid"
            if pidfile.exists() and pidfile.read_text(encoding="utf-8").strip() == str(proc.pid):
                pidfile.unlink(missing_ok=True)
        except Exception:
            pass
        _frontend_process = None


def _persist_debug_reports() -> None:
    if not DEBUG_TRACE_ENABLED:
        return
    try:
        thread_ids = BUS.list_threads()
    except Exception as exc:  # pragma: no cover - defensive guard
        print(f"[Debug][WARN] Unable to enumerate trace threads: {exc}")
        return
    for thread_id in thread_ids:
        try:
            debug_generate_report(thread_id, persist=True)
        except Exception as exc:
            print(f"[Debug][WARN] Failed to persist debug report for {thread_id}: {exc}")


if os.getenv("DEBUG_TRACE_PERSIST_ON_EXIT", "0") == "1":
    atexit.register(_persist_debug_reports)
atexit.register(_stop_frontend_process)

def _clear_python_cache() -> None:
    """Clear Python bytecode cache to prevent stale dataclass issues."""
    backend_dir = Path(__file__).parent
    cleared = 0
    for cache_dir in backend_dir.rglob("__pycache__"):
        try:
            import shutil
            shutil.rmtree(cache_dir)
            cleared += 1
        except Exception:
            pass
    if cleared:
        print(f"[Backend] Cleared {cleared} __pycache__ directories")


if __name__ == "__main__":
    import uvicorn
    # Clear Python cache to prevent stale bytecode issues (e.g., missing dataclass fields)
    _clear_python_cache()

    backend_pidfile = DEV_DIR / "backend.pid"
    _write_pidfile(backend_pidfile)
    atexit.register(_cleanup_pidfile, backend_pidfile)

    _ensure_backend_port_free(BACKEND_PORT)
    _frontend_process = _launch_frontend()
    threading.Thread(target=_open_browser_when_ready, name="frontend-browser", daemon=True).start()
    try:
        uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT)
    finally:
        _stop_frontend_process()
