"""Tests for cancellation detection."""
from __future__ import annotations

import pytest

from detection.special.cancellation import (
    detect_cancellation_intent,
    format_cancellation_subject,
)


class TestCancellationDetection:
    """Tests for detect_cancellation_intent."""

    @pytest.mark.parametrize("text,expected_cancel,min_confidence", [
        # English - strong signals (explicit event/booking cancellation)
        ("I need to cancel the event", True, 0.9),
        ("Please cancel the booking", True, 0.9),
        ("We have to cancel our reservation", True, 0.9),
        ("Cancel it please", True, 0.9),
        ("We won't be needing the room anymore", True, 0.9),
        ("We no longer need the room for our event", True, 0.9),

        # German - detection varies by pattern match
        ("Wir möchten die Veranstaltung stornieren", True, 0.9),
        ("Bitte stornieren Sie die Buchung", True, 0.65),  # is_decline + event word
        ("Wir müssen leider absagen", True, 0.9),  # Matches strong pattern
        ("Wir brauchen den Raum nicht mehr", True, 0.9),

        # French - strong signals
        ("Nous souhaitons annuler la réservation", True, 0.9),
        ("Merci d'annuler l'événement", True, 0.9),
        ("Nous n'avons plus besoin de la salle", True, 0.9),

        # Italian - strong signals
        ("Vogliamo annullare la prenotazione", True, 0.9),
        ("Dobbiamo annullare l'evento", True, 0.9),

        # Spanish - strong signals
        ("Queremos cancelar la reserva", True, 0.9),
        ("Tenemos que cancelar el evento", True, 0.9),

        # NOT cancellation - offer decline (different flow)
        ("I decline your offer", False, 0.0),
        ("That price is too high", False, 0.0),
        ("We'd like a different room", False, 0.0),

        # NOT cancellation - simple no
        ("No, that date doesn't work", False, 0.0),
        ("We prefer the other option", False, 0.0),

        # NOT cancellation - questions
        ("What is the cancellation policy?", False, 0.0),
        ("Can I cancel if needed?", False, 0.0),

        # Empty/short
        ("", False, 0.0),
        ("Hi", False, 0.0),
    ])
    def test_cancellation_detection(self, text, expected_cancel, min_confidence):
        is_cancel, confidence, _ = detect_cancellation_intent(text)
        assert is_cancel == expected_cancel, f"Expected is_cancel={expected_cancel} for '{text}'"
        if expected_cancel:
            assert confidence >= min_confidence, f"Expected confidence >= {min_confidence}, got {confidence}"


class TestFormatCancellationSubject:
    """Tests for format_cancellation_subject."""

    def test_basic_formatting(self):
        result = format_cancellation_subject("Room booking inquiry", "client@example.com")
        assert "CANCELLATION REQUEST" in result
        assert "client@example.com" in result
        assert "Room booking" in result

    def test_strips_re_prefix(self):
        result = format_cancellation_subject("Re: Room booking", "client@example.com")
        assert "Re:" not in result
        assert "Room booking" in result

    def test_truncates_long_subject(self):
        long_subject = "This is a very long subject line that should be truncated for readability"
        result = format_cancellation_subject(long_subject, "client@example.com")
        # Should have ellipsis for truncated subject
        assert "..." in result or len(result.split("|")[1].strip()) <= 43

    def test_emoji_prefix(self):
        result = format_cancellation_subject("Event inquiry", "test@test.com")
        assert result.startswith("⚠️")
