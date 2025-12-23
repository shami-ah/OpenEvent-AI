from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional


def _root_dir() -> Path:
    custom = os.getenv("DEBUG_TRACE_DIR")
    if custom:
        return Path(custom).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "tmp-debug" / "sessions"


ROOT = _root_dir()
ARCH = ROOT / "archive"


def _ensure_dirs() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    ARCH.mkdir(parents=True, exist_ok=True)


def _sanitise(thread_id: str) -> str:
    cleaned = thread_id.replace(os.sep, "_").replace("..", "_")
    return cleaned or "unknown-thread"


def _live_path(thread_id: str) -> Path:
    return ROOT / f"{_sanitise(thread_id)}.jsonl"


def _archived_paths(thread_id: str) -> List[Path]:
    safe = _sanitise(thread_id)
    pattern = f"__{safe}.jsonl"
    candidates: List[Path] = []
    if ARCH.exists():
        for child in ARCH.iterdir():
            if child.name.endswith(pattern):
                candidates.append(child)
    candidates.sort()
    return candidates


def append(thread_id: str, event: Dict) -> None:
    _ensure_dirs()
    path = _live_path(thread_id)
    line = json.dumps(event, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()


def snapshot(thread_id: str) -> List[Dict]:
    live = _live_path(thread_id)
    source: Optional[Path]
    if live.exists():
        source = live
    else:
        archived = _archived_paths(thread_id)
        source = archived[-1] if archived else None
    if not source or not source.exists():
        return []
    records: List[Dict] = []
    try:
        with source.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    except FileNotFoundError:
        return []
    return records


def mark_closed(thread_id: str, reason: str = "closed") -> str:
    live = _live_path(thread_id)
    if not live.exists():
        return ""
    _ensure_dirs()
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
    destination = ARCH / f"{timestamp}__{_sanitise(thread_id)}.jsonl"

    # Also close the human-readable live log
    try:
        from . import live_log  # pylint: disable=import-outside-toplevel

        live_log.close_log(thread_id, reason)
    except Exception:
        pass

    try:
        shutil.move(str(live), str(destination))
        return str(destination)
    except Exception:
        # If move fails, leave live file untouched
        return ""


def resolve_path(thread_id: str) -> Optional[Path]:
    live = _live_path(thread_id)
    if live.exists():
        return live
    archived = _archived_paths(thread_id)
    if archived:
        return archived[-1]
    return None


__all__ = ["append", "snapshot", "mark_closed", "resolve_path"]
