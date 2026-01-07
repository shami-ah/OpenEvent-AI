# MIGRATED: from workflows.nlu.semantic_matchers -> backend.detection.response.matchers
from detection.response.matchers import (
    is_room_selection,
    matches_acceptance_pattern,
    matches_change_pattern,
    matches_decline_pattern,
    matches_counter_pattern,
    _room_patterns_from_catalog,
)


def test_acceptance_explicit_confirm():
    is_match, confidence, _ = matches_acceptance_pattern("I confirm the offer")
    assert is_match and confidence > 0.7


def test_acceptance_explicit_accept():
    is_match, confidence, _ = matches_acceptance_pattern("We accept")
    assert is_match and confidence > 0.7


def test_acceptance_looks_good():
    is_match, confidence, _ = matches_acceptance_pattern("That looks good to us")
    assert is_match and confidence > 0.7


def test_acceptance_sounds_great():
    is_match, confidence, _ = matches_acceptance_pattern("Sounds great, thanks")
    assert is_match and confidence > 0.7


def test_acceptance_yes_please():
    is_match, confidence, _ = matches_acceptance_pattern("Yes please")
    assert is_match and confidence > 0.7


def test_acceptance_ok_send():
    is_match, confidence, _ = matches_acceptance_pattern("ok, send it over")
    assert is_match and confidence > 0.7


def test_acceptance_go_ahead():
    is_match, confidence, _ = matches_acceptance_pattern("Go ahead and proceed")
    assert is_match and confidence > 0.7


def test_not_acceptance_credit_card_question():
    is_match, _, _ = matches_acceptance_pattern("Do you accept credit cards?")
    assert not is_match


def test_not_acceptance_room_looks_good():
    message = "Room A looks good"
    assert is_room_selection(message)
    is_match, _, _ = matches_acceptance_pattern(message)
    assert not is_match


def test_decline_cancel():
    is_match, confidence, _ = matches_decline_pattern("Please cancel")
    assert is_match and confidence > 0.7


def test_decline_not_interested():
    is_match, confidence, _ = matches_decline_pattern("We are not interested")
    assert is_match and confidence > 0.7


def test_decline_pass():
    is_match, confidence, _ = matches_decline_pattern("We will pass on this")
    assert is_match and confidence > 0.7


def test_change_can_we_change():
    is_match, _, _ = matches_change_pattern("Can we change the date?")
    assert is_match


def test_change_modify_the_date():
    is_match, _, _ = matches_change_pattern("Please modify the date to March 5th")
    assert is_match


def test_change_switch_rooms():
    is_match, _, _ = matches_change_pattern("Could we switch rooms to Room B?")
    assert is_match


def test_not_change_hypothetical():
    is_match, _, _ = matches_change_pattern("What if we changed the date?")
    assert not is_match


def test_acceptance_multilanguage():
    is_match, confidence, _ = matches_acceptance_pattern("d'accord, proceed")
    assert is_match and confidence >= 0.8

    is_match2, confidence2, _ = matches_acceptance_pattern("Sehr gut, danke")
    assert is_match2 and confidence2 >= 0.75


def test_counter_budget_phrases():
    is_match, confidence, _ = matches_counter_pattern("Our budget is 3500, can you meet us at that?")
    assert is_match and confidence >= 0.7

    is_match2, confidence2, _ = matches_counter_pattern("Could you do 3000?")
    assert is_match2 and confidence2 >= 0.7


def test_confidence_higher_for_short_prominent_match():
    text = "Yes, that's fine with us."
    is_match, confidence, _ = matches_acceptance_pattern(text)
    assert is_match
    assert confidence >= 0.8


def test_room_selection_uses_catalog(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "backend.detection.response.matchers.load_room_catalog",
        lambda: [SimpleNamespace(name="Panorama Hall", room_id="PAN1")],
    )
    _room_patterns_from_catalog.cache_clear()
    assert is_room_selection("Panorama Hall looks good")
