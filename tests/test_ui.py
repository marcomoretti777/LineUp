"""Tests for the shared Streamlit helpers in lineup/ui.py.

plain() is the escape that stops member-typed text rendering as Markdown,
and run_action() is what keeps a traceback off the screen, so both are
checked for what they refuse as well as what they allow. The Streamlit
calls are replaced with recorders, so no browser is needed.

Rules: section 8 (run_action), section 11, section 12 (output safety).
"""

import logging
import re

import pytest

from lineup import ui
from lineup.models import Code, Condition, Label, Result

RECORDED = ("success", "error", "toast", "markdown", "caption")


@pytest.fixture
def shown(monkeypatch):
    """Replace the Streamlit calls ui.py makes and record their arguments."""
    calls: dict[str, list] = {name: [] for name in RECORDED}

    def recorder(name):
        def record(*args, **kwargs):
            calls[name].append((args, kwargs))
        return record

    for name in RECORDED:
        monkeypatch.setattr(ui.st, name, recorder(name))
    return calls


def only_message(calls, name):
    """The single message passed to one Streamlit call."""
    assert len(calls[name]) == 1, f"expected one {name}, got {len(calls[name])}"
    return calls[name][0][0][0]


# --- plain(): the Markdown escape ------------------------------------------

@pytest.mark.parametrize("character", ["*", "_", "#", "`", "[", "]", "<", ">"])
def test_plain_escapes_each_markdown_character(character):
    assert ui.plain(f"a{character}b") == f"a\\{character}b"


@pytest.mark.parametrize("typed,shown_as", [
    ("**bold**", "\\*\\*bold\\*\\*"),
    ("# heading", "\\# heading"),
    ("<b>tag</b>", "\\<b\\>tag\\</b\\>"),   # the slash is not special, so it stays
])
def test_plain_renders_markup_literally(typed, shown_as):
    assert ui.plain(typed) == shown_as


def test_plain_escapes_a_link_so_it_is_not_clickable():
    escaped = ui.plain("[click](http://example.com)")
    assert escaped.startswith("\\[click\\]")
    assert "\\(" in escaped and "\\)" in escaped


def test_plain_escapes_every_character_it_claims_to():
    # Sweeps the set itself, so the test keeps up if the set ever changes.
    for character in ui._MARKDOWN_SPECIALS:
        assert ui.plain(character) == "\\" + character


@pytest.mark.parametrize("text", [
    "Ana Martins",
    "João D'Ávila",          # accents and an apostrophe must survive
    "Inês Rocha",
    "surf 🏄 time",
    "two  spaces",
])
def test_plain_leaves_ordinary_text_alone(text):
    assert ui.plain(text) == text


def test_plain_handles_the_empty_string():
    assert ui.plain("") == ""


def test_plain_accepts_a_value_that_is_not_a_string():
    assert ui.plain(12) == "12"


# --- run_action(): no traceback ever reaches the user ----------------------

def test_run_action_returns_a_result_unchanged(shown):
    expected = Result.success("Booked.")
    assert ui.run_action(lambda: expected) is expected
    assert shown["error"] == []


def test_run_action_returns_a_refusal_unchanged_without_showing_an_error(shown):
    # A refusal is an expected answer: the page shows it, run_action does not.
    refused = Result.fail(Code.NO_CREDITS, "You have no credits left.")
    assert ui.run_action(lambda: refused) is refused
    assert shown["error"] == []


def test_run_action_passes_arguments_through(shown):
    def service(a, b, *, c):
        return Result.success(f"{a}-{b}-{c}")

    assert ui.run_action(service, 1, 2, c=3).message == "1-2-3"


def test_run_action_turns_an_exception_into_none_and_one_message(shown):
    def boom():
        raise RuntimeError("the database fell over")

    assert ui.run_action(boom) is None
    assert len(shown["error"]) == 1


def test_run_action_message_carries_a_six_character_reference(shown):
    def boom():
        raise RuntimeError("the database fell over")

    ui.run_action(boom)
    message = only_message(shown, "error")
    match = re.fullmatch(r"Something went wrong \(ref ([A-Z0-9]{6})\)\. Please try again.", message)
    assert match, message
    assert set(match.group(1)) <= set(ui._REF_CHARS)


def test_run_action_never_shows_the_traceback_or_the_exception_text(shown):
    secret = "connection to postgres failed for user admin"

    def boom():
        raise RuntimeError(secret)

    ui.run_action(boom)
    message = only_message(shown, "error")
    assert "Traceback" not in message
    assert secret not in message
    assert "RuntimeError" not in message


def test_run_action_gives_each_failure_its_own_reference(shown):
    def boom():
        raise RuntimeError("no")

    for _ in range(6):
        ui.run_action(boom)
    references = {call[0][0] for call in shown["error"]}
    assert len(references) > 1


def test_run_action_logs_the_failure_with_its_traceback(shown, caplog):
    def boom():
        raise RuntimeError("the database fell over")

    with caplog.at_level(logging.ERROR, logger=ui._LOG.name):
        ui.run_action(boom)

    # The traceback belongs in the log, never on screen.
    assert "the database fell over" in caplog.text
    assert "RuntimeError" in caplog.text


# --- show_result() ---------------------------------------------------------

def test_show_result_shows_a_success_and_a_toast(shown):
    ui.show_result(Result.success("Booked: Fri 20 Nov, 10:00."))
    assert only_message(shown, "success") == "Booked: Fri 20 Nov, 10:00."
    assert len(shown["toast"]) == 1
    assert shown["error"] == []


def test_show_result_shows_a_failure_as_an_error(shown):
    ui.show_result(Result.fail(Code.FULL, "This session just filled up."))
    assert only_message(shown, "error") == "This session just filled up."
    assert shown["success"] == []
    assert shown["toast"] == []


def test_show_result_renders_nothing_for_none(shown):
    ui.show_result(None)
    assert all(shown[name] == [] for name in RECORDED)


# --- badge(): the word always carries the meaning --------------------------

@pytest.mark.parametrize("label,word", [
    (Label.GO, "Go"),
    (Label.MARGINAL, "Marginal"),
    (Label.NO_GO, "No-go"),
    (Label.UNKNOWN, "Unknown"),
])
def test_badge_always_names_the_label_in_words(shown, label, word):
    ui.badge(Condition(label, 1.2, 18.0, ""))
    markdown = only_message(shown, "markdown")
    # Colour must never carry the meaning on its own (section 11).
    assert word in markdown


@pytest.mark.parametrize("label,colour", [
    (Label.GO, "green"),
    (Label.MARGINAL, "orange"),
    (Label.NO_GO, "red"),
    (Label.UNKNOWN, "gray"),
])
def test_badge_uses_its_own_colour(shown, label, colour):
    ui.badge(Condition(label, 1.2, 18.0, ""))
    assert f":{colour}-background[" in only_message(shown, "markdown")


def test_badge_shows_the_wave_and_wind_numbers(shown):
    ui.badge(Condition(Label.GO, 1.2, 18.0, ""))
    markdown = only_message(shown, "markdown")
    assert "Waves 1.2 m" in markdown
    assert "Wind 18 km/h" in markdown


def test_badge_shows_a_dash_rather_than_none_when_a_number_is_missing(shown):
    ui.badge(Condition(Label.UNKNOWN, None, None, ""))
    markdown = only_message(shown, "markdown")
    assert "Waves —" in markdown
    assert "Wind —" in markdown
    assert "None" not in markdown


def test_badge_escapes_a_note_before_showing_it(shown):
    ui.badge(Condition(Label.NO_GO, 3.0, 40.0, "too big *today*"))
    assert only_message(shown, "caption") == "too big \\*today\\*"


def test_badge_shows_no_caption_without_a_note(shown):
    ui.badge(Condition(Label.GO, 1.2, 18.0, ""))
    assert shown["caption"] == []


def test_badge_falls_back_to_unknown_for_a_label_it_does_not_know(shown):
    ui.badge(Condition("something-else", 1.2, 18.0, ""))
    assert "Unknown" in only_message(shown, "markdown")


# --- footer_credit() -------------------------------------------------------

def test_footer_credit_names_open_meteo_and_links_the_licence(shown):
    ui.footer_credit()
    caption = only_message(shown, "caption")
    assert "Open-Meteo.com" in caption
    assert "https://open-meteo.com/en/licence" in caption
