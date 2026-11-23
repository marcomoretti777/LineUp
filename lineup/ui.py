"""Shared Streamlit helpers every screen uses: engine, actor, messages, badges.

Only app.py, app_pages/ and this module import Streamlit (AGENTS.md). Screens
call a service and hand the Result here, so one problem is always worded the
same way.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from secrets import choice

import streamlit as st
from sqlalchemy.engine import Engine

from lineup import config, db
from lineup.models import Actor, Condition, Label, Result, SessionView
from lineup.services import forecast

_LOG = logging.getLogger(__name__)

FORECAST_CACHE_SECONDS = 300

# No look-alike characters, because people read the reference out loud or
# type it into a message to the club.
_REF_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_REF_LENGTH = 6

# Streamlit's own colour names, so no raw HTML is needed for the pill.
_BADGE_COLOURS = {
    Label.GO: ("Go", "green"),
    Label.MARGINAL: ("Marginal", "orange"),
    Label.NO_GO: ("No-go", "red"),
    Label.UNKNOWN: ("Unknown", "gray"),
}

# Chip kinds, so a page names a state rather than picking a colour. Every
# one keeps its word visible; the colour only repeats what the text says.
CHIP_COLOURS = {
    "neutral": "gray",
    "info": "blue",
    "good": "green",
    "warn": "orange",
    "bad": "red",
}

# The stylesheet is read once from static/. It is a constant file: no value
# in it ever comes from a member (section 12).
STYLES = (Path(__file__).resolve().parent.parent / "static" / "lineup.css").read_text()

# Drawn in house rather than fetched, so the app pulls no remote asset.
WAVE_SVG = (
    '<svg class="lu-wave" viewBox="0 0 320 24" width="100%" height="24" '
    'role="presentation" aria-hidden="true" focusable="false">'
    '<path d="M0 14 C 40 2, 80 2, 120 14 S 200 26, 240 14 S 300 2, 320 10" '
    'fill="none" stroke="#0E7C86" stroke-width="3" stroke-linecap="round"/>'
    '</svg>'
)

# Every character Markdown would otherwise read as markup.
_MARKDOWN_SPECIALS = set("\\`*_{}[]()#+-.!|$~<>")


@st.cache_resource
def get_engine() -> Engine:
    """Return the one database engine of this server process, tables ready.

    Cached per process because a connection pool must be shared, never rebuilt
    on every rerun.

    Rules: section 8 (shared objects), section 14.
    """
    engine = db.make_engine(config.get_secret("DATABASE_URL"))
    db.init_db(engine)
    return engine


def _forecast_key(session: SessionView) -> tuple:
    # Only what the label depends on: a booking changing the places left
    # must not throw the cached labels away.
    return (session.id, session.starts_at, session.duration_min, session.level.value)


@st.cache_data(ttl=FORECAST_CACHE_SECONDS, show_spinner=False,
               hash_funcs={SessionView: _forecast_key})
def cached_conditions(_engine: Engine, sessions: list[SessionView]) -> dict[int, Condition]:
    """Return the conditions labels for these sessions, shared for five minutes.

    The forecast changes hourly, yet every open screen used to read it from
    the database on each 10-second refresh. One copy now serves every member
    for five minutes; a threshold an admin changes shows within that time.

    Rules: R6, R7, section 11 (Sessions).
    """
    return forecast.conditions_for_sessions(_engine, sessions)


def conditions_for(engine: Engine, sessions, now=None, fetch=None) -> dict[int, Condition]:
    """Conditions for these sessions, from the shared cache where possible.

    Carries the service's own signature, so it can be injected wherever
    conditions_for_sessions is expected. A caller supplying its own fetch
    wants a live read, so that path skips the cache entirely.

    Rules: R6, R7, section 11.
    """
    sessions = list(sessions)
    if fetch is not None:
        return forecast.conditions_for_sessions(engine, sessions, now=now, fetch=fetch)
    return cached_conditions(engine, sessions)


def current_actor(engine: Engine) -> Actor | None:
    """Return the signed-in member, re-read from the database on every rerun.

    The role is never kept in the session, so a demoted member loses the extra
    rights on their next click.

    Rules: section 3, section 8 (Actor convention).
    """
    member_id = st.session_state.get("member_id")
    if not member_id:
        return None
    with engine.begin() as conn:
        return db.get_actor(conn, member_id)


def show_result(result: Result | None) -> None:
    """Show a service Result: success plus toast when ok, error otherwise.

    Rules: section 8 (Result), section 11.
    """
    if result is None:
        return
    if result.ok:
        st.success(result.message)
        st.toast(result.message, icon=":material/check_circle:")
    else:
        st.error(result.message)


def run_action(fn, *args, **kwargs) -> Result | None:
    """Call one service function, turning an unexpected error into a message.

    Expected problems come back as a Result and never reach the except branch;
    anything else is logged with a reference the member can quote, so no
    traceback is ever shown on screen.

    Rules: section 8 (unexpected errors).
    """
    try:
        return fn(*args, **kwargs)
    except Exception:
        ref = "".join(choice(_REF_CHARS) for _ in range(_REF_LENGTH))
        _LOG.exception("Unhandled error in %s (ref %s)", getattr(fn, "__name__", fn), ref)
        st.error(f"Something went wrong (ref {ref}). Please try again.")
        return None


def _number(value: float | None, unit: str) -> str:
    """Format a forecast number, or an em dash when there is none.

    Rules: R6.4.
    """
    return "—" if value is None else f"{value:g} {unit}"


def badge(condition: Condition) -> None:
    """Show the conditions pill: the word, then the waves, wind and the note.

    The word is part of the text, so the colour never carries the meaning on
    its own.

    Rules: R6.2-R6.4, section 11 (conditions badge).
    """
    word, colour = _BADGE_COLOURS.get(condition.label, _BADGE_COLOURS[Label.UNKNOWN])
    numbers = (
        f"Waves {_number(condition.wave_m, 'm')}"
        f" · Wind {_number(condition.wind_kmh, 'km/h')}"
    )
    st.markdown(f":{colour}-background[**{word}**] {numbers}")
    if condition.note:
        st.caption(plain(condition.note))


def plain(text: str) -> str:
    """Escape Markdown so text a member typed renders exactly as they typed it.

    Rules: section 12 (never render member text as markup).
    """
    return "".join("\\" + ch if ch in _MARKDOWN_SPECIALS else ch for ch in str(text))


def footer_credit() -> None:
    """Show the Open-Meteo credit required wherever conditions appear.

    Rules: section 10 (terms and attribution).
    """
    st.caption(
        "Weather data: [Open-Meteo.com](https://open-meteo.com/en/licence), "
        "wave models by Météo-France, ECMWF, NOAA and DWD"
    )


def inject_styles() -> None:
    """Put the LineUp stylesheet on the page once per run.

    The argument is the module constant, never anything a member typed, so
    no markup can reach the page through it.

    Rules: section 11, section 12 (output safety).
    """
    st.html(f"<style>{STYLES}</style>")


def page_header(title: str, subtitle: str | None = None) -> None:
    """Draw a screen's title and optional one-line subtitle.

    Rules: section 11.
    """
    st.title(title)
    if subtitle:
        st.caption(plain(subtitle))


@contextmanager
def card():
    """A bordered surface for one session, booking or request.

    Rules: section 11.
    """
    with st.container(border=True) as container:
        yield container


def chip_markup(text: str, kind: str = "neutral") -> str:
    """Return the coloured pill markup for a state, with the text escaped.

    The word is always shown, so the colour never carries the meaning on
    its own, and an unknown kind falls back to neutral rather than
    silently losing the pill.

    Rules: section 11, section 12 (output safety).
    """
    colour = CHIP_COLOURS.get(kind, CHIP_COLOURS["neutral"])
    return f":{colour}-background[**{plain(text)}**]"


def chip(text: str, kind: str = "neutral") -> None:
    """Show one state pill.

    Rules: section 11.
    """
    st.markdown(chip_markup(text, kind))


def empty_state(message: str, icon: str = ":material/surfing:") -> None:
    """Show the catalogue's own wording for an empty list.

    The helper only frames the message; it never invents new wording.

    Rules: section 11 (empty states).
    """
    st.info(plain(message), icon=icon)


@contextmanager
def loading(text: str = "Paddling out\u2026"):
    """Wrap slow work in a spinner with a waving shaka.

    The hand holds still under prefers-reduced-motion, which the stylesheet
    enforces; the words are the same either way.

    Rules: section 11.
    """
    with st.spinner(text):
        yield
