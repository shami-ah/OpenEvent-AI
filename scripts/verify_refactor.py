import compileall
import io
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdin, "isatty"):
    sys.stdin.isatty = lambda: False  # type: ignore[misc]

print("== compileall backend ==")
ok = compileall.compile_dir("backend", maxlevels=10, quiet=1)
print("COMPILE_ALL_OK", bool(ok))

print("== orchestrator samples ==")
from backend.workflow_email import run_samples  # noqa: E402

capture = io.StringIO()
with redirect_stdout(capture):
    sample_rows = run_samples() or []
first_three = sample_rows[:3]


def _preview(entry: object) -> object:
    if isinstance(entry, dict):
        preview: dict[str, object] = {"action": entry.get("action")}
        if "suggested_dates" in entry:
            preview["suggested_dates"] = entry.get("suggested_dates")
        if "date_confirmation" in entry and isinstance(entry["date_confirmation"], dict):
            preview["date_confirmation"] = {
                "action": entry["date_confirmation"].get("action"),
            }
        return preview
    return entry


print("SAMPLES_FIRST_3", [_preview(item) for item in first_three])

expected_actions = [
    "ask_for_date_enqueued",
    "room_avail_result",
    "manual_review_enqueued",
]
issues: list[str] = []
if len(first_three) < 3:
    issues.append("expected at least 3 sample outputs")
else:
    actual_actions = []
    for entry in first_three:
        if isinstance(entry, dict):
            actual_actions.append(entry.get("action"))
        else:
            actual_actions.append(type(entry).__name__)
    for idx, (expected, actual) in enumerate(zip(expected_actions, actual_actions), start=1):
        if expected != actual:
            issues.append(f"sample {idx} action expected {expected!r} but saw {actual!r}")
    if isinstance(first_three[1], dict):
        nested = first_three[1].get("date_confirmation")
        nested_action = nested.get("action") if isinstance(nested, dict) else None
        if nested_action != "date_confirmed":
            issues.append(
                "sample 2 missing nested date_confirmation.action='date_confirmed'"
            )
    else:
        issues.append("sample 2 is not a dict payload")
if issues:
    print("SAMPLE_SEQUENCE_MISMATCH", issues)

print("== uniqueness of helpers ==")
targets = [
    "room_status_on_date",
    "suggest_dates",
    "compose_date_confirmation_reply",
    "is_valid_ddmmyyyy",
]
counts = {name: 0 for name in targets}
for root, _, files in os.walk("backend"):
    for filename in files:
        if not filename.endswith(".py"):
            continue
        path = Path(root, filename)
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for name in targets:
            pattern = r"^def\s+{}\s*\(".format(re.escape(name))
            counts[name] += len(re.findall(pattern, text, flags=re.M))
print("HELPER_DEF_COUNTS", counts)
unexpected = {name: count for name, count in counts.items() if count != 1}
if unexpected:
    print("HELPERS_UNEXPECTED_COUNTS", unexpected)

print("== direct DB writes in groups ==")
bad = []
for root, _, files in os.walk("backend/workflows/groups"):
    for filename in files:
        if not filename.endswith(".py"):
            continue
        path = Path(root, filename)
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if re.search(r"open\(.*events_database\\.json", text):
            bad.append(str(path))
print("DIRECT_DB_WRITES_IN_GROUPS", bad)

print("== availability toggle ==")
from backend.workflows.steps.step3_room_availability.trigger import evaluate_room_statuses  # noqa: E402

db = {
    "events": [
        {
            "event_id": "e1",
            "event_data": {
                "Event Date": "10.10.2025",
                "Preferred Room": "Room A",
                "Status": "Option",
            },
        }
    ]
}
print("Option:", evaluate_room_statuses(db, "10.10.2025"))
db["events"][0]["event_data"]["Status"] = "Confirmed"
print("Confirmed:", evaluate_room_statuses(db, "10.10.2025"))

print("== fastapi entrypoint ==")
try:
    import fastapi  # noqa: F401
except Exception:
    print("FASTAPI_SKIPPED")
else:
    try:
        import backend.main as appmod  # noqa: F401

        print("FASTAPI_IMPORT_OK", bool(appmod))
    except Exception as exc:  # pragma: no cover - diagnostic output only
        print("FASTAPI_IMPORT_FAIL", exc)
