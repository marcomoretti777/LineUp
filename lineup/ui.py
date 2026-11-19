"""Shared Streamlit helpers every screen uses: engine, actor, messages, badges.

Only app.py, app_pages/ and this module import Streamlit (AGENTS.md). Screens
call a service and hand the Result here, so one problem is always worded the
same way.
"""

from __future__ import annotations

import logging
from secrets import choice

import streamlit as st
from sqlalchemy.engine import Engine

from lineup import config, db
from lineup.models import Actor, Condition, Label, Result

_LOG = logging.getLogger(__name__)

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
