import argparse
import json
import tempfile
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.workflow_email import approve_task_and_send, process_msg
from backend.workflows.common.menu_options import build_menu_payload, extract_menu_request, format_menu_line
from backend.workflows.io import database as db_io
from backend.workflow_verbalizer_test_hooks import render_rooms
from tests.stubs.dates_and_rooms import room_status_on_date as stub_room_status
from tests.stubs.dates_and_rooms import suggest_dates as stub_suggest_dates
from tests.stubs.dates_and_rooms import load_rooms_config as stub_load_rooms_config
from tests.stubs.dates_and_rooms import week_window as stub_week_window

ACTION_TASK_MAP = {
    "ask_for_date_enqueued": 2,
    "room_options_enqueued": 3,
    "offer_enqueued": 4,
    "negotiation_enqueued": 5,
}


def assert_headers_subset(actual: Sequence[str], expected_subset: Sequence[str]) -> None:
    if not expected_subset:
        return
    iterator = iter(actual)
    for needle in expected_subset:
        for candidate in iterator:
            if candidate == needle:
                break
        else:
            raise AssertionError(f"Expected headers to contain subset {expected_subset}, got {list(actual)}")


def assert_body_order(body: str, markers: Sequence[str]) -> None:
    if not markers:
        return
    cursor = -1
    for marker in markers:
        idx = body.find(marker)
        if idx == -1:
            raise AssertionError(f"Missing marker '{marker}' in body: {body}")
        if idx < cursor:
            raise AssertionError(f"Marker '{marker}' appears out of order in body: {body}")
        cursor = idx


def assert_contains_all(body: str, phrases: Iterable[str]) -> None:
    for phrase in phrases:
        if phrase not in body:
            raise AssertionError(f"Missing phrase '{phrase}' in body: {body}")


class FlowHarness:
    def __init__(self, suite_path: Path, suite_data: Dict[str, Any]) -> None:
        self.suite_path = suite_path
        self.suite = suite_data
        self.thread_id = f"{suite_data.get('suite', 'flow')}-thread"
        self.default_email = "client@example.com"
        
        # Create a temporary directory for the flow run
        tmp_root = Path("tmp-flows")
        tmp_root.mkdir(exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix="flow_run_", dir=tmp_root))
        
        self.db_path = tmp_dir / "events.json"
        self.msg_counter = 0
        self.last_result: Optional[Dict[str, Any]] = None
        self.last_actions: List[Dict[str, Any]] = []
        self._original_patches: List[Tuple[Any, str, Any]] = []
        self._last_msg_payload: Optional[Dict[str, Any]] = None
        self._install_stubs()

    def close(self) -> None:
        while self._original_patches:
            module, attr, original = self._original_patches.pop()
            setattr(module, attr, original)

    def run(self) -> None:
        try:
            for step in self.suite["steps"]:
                if "msg_in" in step:
                    result = self._handle_msg(step["msg_in"], step.get("simulate_intent"))
                elif "gui_action" in step:
                    result = self._handle_gui(step["gui_action"])
                elif "system_call" in step:
                    result = self._handle_system_call(
                        step["system_call"],
                        step.get("args", {}),
                        step.get("stub_returns", {}),
                    )
                else:
                    continue
                self.last_result = result
                self.last_actions = result.get("actions", [])
                self._assert_expectations(step.get("expect"), result)
        finally:
            self.close()

    def _install_stubs(self) -> None:
        modules = [
            "backend.workflows.groups.intake.condition.checks",
            "backend.workflows.groups.intake.condition",
            "backend.workflows.groups.intake",
            "backend.workflows.groups.date_confirmation.trigger.process",
        ]
        for name in modules:
            module = import_module(name)
            if hasattr(module, "suggest_dates"):
                original = getattr(module, "suggest_dates")
                self._original_patches.append((module, "suggest_dates", original))
                setattr(module, "suggest_dates", stub_suggest_dates)
        dates_module = import_module("backend.utils.dates")
        original_week_window = getattr(dates_module, "week_window")
        self._original_patches.append((dates_module, "week_window", original_week_window))
        setattr(dates_module, "week_window", stub_week_window)
        room_config_module = import_module("backend.workflows.groups.room_availability.db_pers")
        original_load_rooms = getattr(room_config_module, "load_rooms_config")
        self._original_patches.append((room_config_module, "load_rooms_config", original_load_rooms))
        setattr(room_config_module, "load_rooms_config", stub_load_rooms_config)
        ranking_module = import_module("backend.rooms.ranking")
        original_ranking_load = getattr(ranking_module, "load_rooms_config")
        self._original_patches.append((ranking_module, "load_rooms_config", original_ranking_load))
        setattr(ranking_module, "load_rooms_config", stub_load_rooms_config)

    def _handle_msg(
        self,
        msg_in: Dict[str, Any],
        simulate_intent: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.msg_counter += 1
        payload = dict(msg_in)
        payload.setdefault("msg_id", f"msg-{self.msg_counter}")
        payload.setdefault("from_name", "Test Client")
        payload.setdefault("from_email", self.default_email)
        payload.setdefault("ts", self.suite.get("initial_clock"))
        payload.setdefault("thread_id", self.thread_id)
        self._last_msg_payload = payload
        result = process_msg(payload, db_path=self.db_path)
        if simulate_intent:
            result["intent_detail"] = simulate_intent
        return result

    def _handle_gui(self, action: Dict[str, Any]) -> Dict[str, Any]:
        task_type = action.get("approve_task")
        if not task_type:
            raise AssertionError("Unsupported gui_action")
        task_id = self._resolve_task_id(task_type)
        if not task_id:
            raise AssertionError(f"Task for action {task_type} not found")
        return approve_task_and_send(task_id, db_path=self.db_path)

    def _resolve_task_id(self, action_type: str) -> Optional[str]:
        target_step = ACTION_TASK_MAP.get(action_type)
        db = db_io.load_db(self.db_path)
        for event in db.get("events", []):
            for entry in event.get("pending_hil_requests", []) or []:
                if entry.get("step") == target_step:
                    return entry.get("task_id")
        return None

    def _handle_system_call(
        self,
        name: str,
        args: Dict[str, Any],
        stub_returns: Dict[str, Any],
    ) -> Dict[str, Any]:
        event = self._current_event()
        if not event:
            raise AssertionError("system_call requires an event")
        if name == "room_status_on_date":
            pax = _extract_pax(event) or 0
            iso_date = args.get("date") or event.get("chosen_date_iso")
            requirements = (event.get("requirements") or {}).get("requirements") or []
            rooms = stub_returns.get("rooms") or stub_room_status(iso_date, pax, requirements)
            payload = render_rooms(event.get("event_id"), iso_date, pax, rooms)
            assistant = payload.get("assistant_draft", {})
            body_text = assistant.get("body", "")
            if self._message_has_menu_question():
                menu_payload = build_menu_payload(
                    (self._last_msg_payload or {}).get("body"),
                    context_month=(self._current_event() or {}).get("vague_month"),
                )
                qa_lines = []
                if menu_payload:
                    month_hint = menu_payload.get("month")
                    title = menu_payload.get("title") or "Menu options we can offer:"
                    qa_lines.append(title)
                    for row in menu_payload.get("rows", []):
                        rendered = format_menu_line(row, month_hint=month_hint)
                        if rendered:
                            qa_lines.append(rendered)
                if qa_lines:
                    combined_body = "\n".join(qa_lines + ["", body_text]) if body_text else "\n".join(qa_lines)
                    assistant["body"] = combined_body
                    headers = assistant.get("headers") or []
                    assistant["headers"] = ["Availability overview"] + [header for header in headers if header]
                    payload["assistant_draft_text"] = combined_body
            if "assistant_draft" not in payload:
                payload["assistant_draft"] = assistant
            payload.setdefault("actions", []).append({"type": "send_reply"})
            payload["rooms"] = rooms
            return payload
        if name == "build_offer":
            result = self._build_offer(event, args)
            result.setdefault("actions", []).append({"type": "send_reply"})
            return result
        raise AssertionError(f"Unknown system_call {name}")

    def _build_offer(self, event: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
        from backend.workflows.steps.step4_offer.trigger.process import build_offer

        result = build_offer(
            event.get("event_id"),
            args.get("room_id"),
            args.get("date"),
            args.get("pax", 0),
        )
        self._mark_event_option(event.get("event_id"))
        return result

    def _mark_event_option(self, event_id: Optional[str]) -> None:
        if not event_id:
            return
        db = db_io.load_db(self.db_path)
        for event in db.get("events", []):
            if event.get("event_id") == event_id:
                event.setdefault("event_data", {})["Status"] = "Option"
                break
        db_io.save_db(db, self.db_path)

    def _current_event(self) -> Optional[Dict[str, Any]]:
        db = db_io.load_db(self.db_path)
        events = db.get("events", [])
        return events[-1] if events else None

    def _assert_expectations(self, expect: Optional[Dict[str, Any]], actual: Dict[str, Any]) -> None:
        if not expect:
            return
        if "intent" in expect:
            assert actual.get("intent_detail") == expect["intent"], actual
        if "user_info" in expect:
            user_info = actual.get("user_info", {})
            for key, value in expect["user_info"].items():
                actual_value = user_info.get(key)
                if isinstance(value, str) and isinstance(actual_value, str):
                    assert actual_value.lower() == value.lower(), f"user_info mismatch for {key}: {user_info}"
                else:
                    assert actual_value == value, f"user_info mismatch for {key}: {user_info}"
        if "actions" in expect:
            actual_list = actual.get("actions", [])
            actual_types = [action.get("type") for action in actual_list]
            expected_list = expect["actions"]
            expected_types = [item.get("type") for item in expected_list]
            assert actual_types == expected_types, f"actions mismatch: {actual_types} vs {expected_types}"
            for idx, exp in enumerate(expected_list):
                if idx >= len(actual_list):
                    break
                exp_payload = exp.get("payload") or {}
                if not exp_payload:
                    continue
                act_payload = actual_list[idx].get("payload", {})
                for key, value in exp_payload.items():
                    if value == "ANY":
                        continue
                    actual_val = act_payload.get(key)
                    if isinstance(value, list) and isinstance(actual_val, list):
                        expect_slice = value
                        actual_slice = actual_val[: len(value)]
                        if value and isinstance(value[0], str):
                            expect_slice = [_normalize_date_string(item) for item in value]
                            actual_slice = [_normalize_date_string(item) for item in actual_slice]
                        assert actual_slice == expect_slice, f"Mismatch for action payload {key}: {act_payload}"
                    else:
                        assert actual_val == value, f"Mismatch for action payload {key}: {act_payload}"
        if "trace" in expect:
            trace_expect = expect["trace"]
            trace_actual = actual.get("trace", {})
            actual_subloops = trace_actual.get("subloops") or []
            if "subloops" in trace_expect:
                assert actual_subloops == trace_expect["subloops"], f"subloops mismatch: {actual_subloops}"
            if "subloops_contains" in trace_expect:
                for item in trace_expect["subloops_contains"]:
                    if item not in actual_subloops:
                        raise AssertionError(f"Expected subloop '{item}' in {actual_subloops}")
        if "res" in expect:
            res_actual = actual.get("res")
            if not res_actual and (
                "assistant_draft" in actual or "assistant_draft_text" in actual
            ):
                res_actual = {
                    "assistant_draft": actual.get("assistant_draft", {}),
                    "assistant_draft_text": actual.get("assistant_draft_text", ""),
                }
            res_actual = res_actual or {}
            res_expect = expect["res"]
            draft_expect = res_expect.get("assistant_draft")
            if draft_expect:
                draft_actual = res_actual.get("assistant_draft", {})
                headers_actual = draft_actual.get("headers") or []
                body_actual = draft_actual.get("body", "") or res_actual.get("assistant_draft_text", "")
                if "headers" in draft_expect:
                    assert headers_actual == draft_expect["headers"], headers_actual
                if "headers_subset" in draft_expect:
                    assert_headers_subset(headers_actual, draft_expect["headers_subset"])
                if "contains" in draft_expect:
                    assert_contains_all(body_actual, draft_expect["contains"])
                if "contains_all" in draft_expect:
                    assert_contains_all(body_actual, draft_expect["contains_all"])
                if "not_contains_all" in draft_expect:
                    for phrase in draft_expect["not_contains_all"]:
                        if phrase in body_actual:
                            raise AssertionError(f"Unexpected phrase '{phrase}' present in body: {body_actual}")
                if "body_order" in draft_expect:
                    assert_body_order(body_actual, draft_expect["body_order"])
            if "general_qa" in res_expect:
                qa_actual = res_actual.get("general_qa") or {}
                for key, value in res_expect["general_qa"].items():
                    if key.endswith("_min"):
                        field = key[:-4]
                        assert len(qa_actual.get(field, [])) >= value
                    else:
                        assert qa_actual.get(key) == value
        if "rooms_min" in expect:
            rooms = actual.get("rooms", [])
            assert len(rooms) >= expect["rooms_min"], rooms
        if "status" in expect:
            status = self._current_event_status()
            assert status == expect["status"], status
        if "db_assert" in expect:
            gate = expect["db_assert"].get("gatekeeping")
            if gate:
                snapshot = self._gatekeeping_snapshot()
                for key, value in gate.items():
                    assert snapshot.get(key) == value, snapshot

    def _gatekeeping_snapshot(self) -> Dict[str, Any]:
        event = self._current_event()
        if not event:
            return {}
        requirements = event.get("requirements") or {}
        chosen_iso = (
            event.get("requested_window", {}).get("date_iso")
            or event.get("pending_date_confirmation", {}).get("iso_date")
            or event.get("chosen_date_iso")
        )
        return {
            "attendees": requirements.get("number_of_participants") or requirements.get("participants"),
            "date": chosen_iso or event.get("chosen_date_iso") or event.get("chosen_date"),
        }

    def _current_event_status(self) -> Optional[str]:
        event = self._current_event()
        if not event:
            return None
        return (event.get("event_data") or {}).get("Status")

    def _message_has_menu_question(self) -> bool:
        payload = self._last_msg_payload or {}
        text = str(payload.get("body") or "")
        return extract_menu_request(text) is not None


def _extract_pax(event: Dict[str, Any]) -> Optional[int]:
    requirements = event.get("requirements") or {}
    pax = requirements.get("number_of_participants") or requirements.get("participants")
    return int(pax) if pax else None


def _normalize_date_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    token = value.strip()
    if token.count(".") == 2:
        day, month, year = token.split(".")
        return f"{year.zfill(4)}-{month.zfill(2)}-{day.zfill(2)}"
    return token


def load_suite(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def run_suite_file(path: Path) -> None:
    data = load_suite(path)
    harness = FlowHarness(path, data)
    harness.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run YAML-defined workflow flows")
    parser.add_argument("files", nargs="+", help="YAML suite files")
    args = parser.parse_args()
    for file_path in args.files:
        run_suite_file(Path(file_path))


if __name__ == "__main__":
    main()
