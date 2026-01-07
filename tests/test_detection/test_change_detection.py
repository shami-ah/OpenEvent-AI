from workflows.change_propagation import ChangeType, detect_change_type


def _base_event_state():
    return {
        "date_confirmed": True,
        "chosen_date": "01.01.2025",
        "locked_room_id": "room a",
        "current_step": 5,
    }


def test_hypothetical_question_not_change():
    event_state = _base_event_state()
    user_info = {"event_date": "05.03.2025"}
    change_type = detect_change_type(
        event_state,
        user_info,
        message_text="What if we changed the date?",
    )
    assert change_type is None


def test_actual_change_request_detected():
    event_state = _base_event_state()
    user_info = {"event_date": "05.03.2025"}
    change_type = detect_change_type(
        event_state,
        user_info,
        message_text="Can we change the date to 05.03.2025?",
    )
    assert change_type == ChangeType.DATE


def test_change_request_with_product_proximity():
    event_state = _base_event_state()
    user_info = {"products": "coffee"}
    change_type = detect_change_type(
        event_state,
        user_info,
        message_text="Could you change the coffee package?",
    )
    assert change_type == ChangeType.PRODUCTS


def test_distant_change_verb_not_matched():
    event_state = _base_event_state()
    user_info = {"products": "coffee"}
    text = "Change the date and by the way the coffee was great last time."
    change_type = detect_change_type(event_state, user_info, message_text=text)
    assert change_type is None
