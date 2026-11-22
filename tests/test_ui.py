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

RECORDED = ("success", "error", "toast", "markdown", "caption", "title", "info")


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


# =========================================================================
# F11: the shared visual components.
# Behaviour is presentation only; these pin down the parts that carry a
# rule — escaping member text, naming every state in words, and holding
# animation still for anyone who asked for less motion.
# =========================================================================

CHIP_KINDS = ("neutral", "info", "good", "warn", "bad")


# --- chip() ----------------------------------------------------------------

@pytest.mark.parametrize("kind", CHIP_KINDS)
def test_chip_markup_renders_for_every_kind(kind):
    markup = ui.chip_markup("Booked", kind)
    assert "Booked" in markup
    assert "-background[" in markup


@pytest.mark.parametrize("kind", CHIP_KINDS)
def test_chip_markup_uses_a_distinct_colour_per_kind(kind):
    colour = ui.CHIP_COLOURS[kind]
    assert f":{colour}-background[" in ui.chip_markup("Booked", kind)


def test_chip_colours_cover_exactly_the_documented_kinds():
    assert set(ui.CHIP_COLOURS) == set(CHIP_KINDS)


def test_chip_markup_escapes_member_text():
    # A chip may carry a name or a note, so it goes through plain().
    assert "\\*" in ui.chip_markup("*Ana*", "info")


def test_chip_markup_keeps_a_waitlist_number_readable():
    # plain() escapes "#", which Markdown then renders as a plain hash.
    assert "Waitlist \\#2" in ui.chip_markup("Waitlist #2", "info")


def test_chip_markup_falls_back_to_neutral_for_an_unknown_kind():
    assert f":{ui.CHIP_COLOURS['neutral']}-background[" in ui.chip_markup("Odd", "nonsense")


def test_chip_renders_through_streamlit(shown):
    ui.chip("Attended", "good")
    assert "Attended" in only_message(shown, "markdown")


# --- page_header() ---------------------------------------------------------

def test_page_header_shows_the_title(shown):
    ui.page_header("Sessions")
    assert only_message(shown, "title") == "Sessions"
    assert shown["caption"] == []


def test_page_header_shows_an_optional_subtitle(shown):
    ui.page_header("Sessions", "The next 14 days")
    assert only_message(shown, "caption") == "The next 14 days"


def test_page_header_escapes_a_subtitle(shown):
    ui.page_header("Members", "*Ana*")
    assert only_message(shown, "caption") == "\\*Ana\\*"


# --- empty_state() ---------------------------------------------------------

def test_empty_state_shows_the_message_it_is_given(shown):
    # The wording stays the catalogue's; the helper only frames it.
    ui.empty_state("No sessions in the next 14 days yet.")
    assert only_message(shown, "info") == "No sessions in the next 14 days yet."


def test_empty_state_escapes_member_text(shown):
    ui.empty_state("*nothing*")
    assert only_message(shown, "info") == "\\*nothing\\*"


# --- the stylesheet --------------------------------------------------------

def test_styles_are_a_constant_with_no_placeholder():
    # No user text ever enters the stylesheet, so it must not be a template.
    assert isinstance(ui.STYLES, str) and ui.STYLES
    assert "{}" not in ui.STYLES
    assert "%s" not in ui.STYLES


def test_styles_hold_the_shaka_animation_still_under_reduced_motion():
    assert "prefers-reduced-motion" in ui.STYLES
    # The rule must actually switch the animation off, not merely mention it.
    after = ui.STYLES.split("prefers-reduced-motion", 1)[1]
    assert "animation" in after


def test_styles_define_the_shaka_animation():
    assert "@keyframes" in ui.STYLES


def test_wave_svg_is_an_inline_svg_with_no_remote_reference():
    assert ui.WAVE_SVG.lstrip().startswith("<svg")
    assert "http://" not in ui.WAVE_SVG
    assert "https://" not in ui.WAVE_SVG


# --- loading() -------------------------------------------------------------

def test_loading_wraps_a_spinner_and_yields(monkeypatch):
    seen = []

    class FakeSpinner:
        def __init__(self, text):
            seen.append(text)
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(ui.st, "spinner", FakeSpinner)
    with ui.loading():
        pass
    assert seen and "addling" in seen[0]


def test_loading_accepts_its_own_text(monkeypatch):
    seen = []
    monkeypatch.setattr(ui.st, "spinner", lambda text: _NullContext(seen, text))
    with ui.loading("Reading the forecast"):
        pass
    assert seen == ["Reading the forecast"]


class _NullContext:
    def __init__(self, seen, text):
        seen.append(text)
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
