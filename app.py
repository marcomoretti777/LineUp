"""Entry point: page setup, the login gate and navigation by role.

Business rules live in lineup/logic/ and lineup/services/; this file only
calls config, db, ui and the services.

Rules: section 8, section 11, R1.7.
"""

from __future__ import annotations

import streamlit as st
from sqlalchemy.engine import Engine

from lineup import config, db, ui
from lineup.models import Actor, Role
from lineup.services import members

# Title, then the page file, in the order spec section 11 lists them.
_PAGES = {
    "sessions": ("Sessions", "app_pages/sessions.py"),
    "my_bookings": ("My bookings", "app_pages/my_bookings.py"),
    "credits": ("Credits", "app_pages/credits.py"),
    "inbox": ("Inbox", "app_pages/inbox.py"),
    "instructor_sessions": ("My sessions", "app_pages/instructor_sessions.py"),
    "roster": ("Roster", "app_pages/roster.py"),
    "admin_requests": ("Credit requests", "app_pages/admin_requests.py"),
    "admin_members": ("Members", "app_pages/admin_members.py"),
    "admin_reports": ("Reports", "app_pages/admin_reports.py"),
    "admin_settings": ("Settings", "app_pages/admin_settings.py"),
}

_NAVIGATION = {
    Role.STUDENT: ("sessions", "my_bookings", "credits", "inbox"),
    Role.INSTRUCTOR: ("sessions", "instructor_sessions", "roster", "inbox"),
    Role.ADMIN: (
        "sessions", "roster", "admin_requests", "admin_members",
        "admin_reports", "admin_settings", "inbox",
    ),
}


def _demo_mode() -> bool:
    """Say whether the passwordless demo picker may replace the login page.

    Rules: R1.7.
    """
    return config.demo_mode_allowed(
        config.get_secret("DATABASE_URL"), config.get_secret("SUPABASE_URL")
    )


def _demo_login(engine: Engine) -> None:
    """Show the demo banner and let anyone sign in as any member, no password.

    Rules: R1.7.
    """
    st.title("LineUp")
    st.error(
        "Local demo mode: anyone can sign in as any member without a password. "
        "Never point this at real data."
    )
    people = members.list_demo_members(engine)
    if not people:
        st.info("No members yet. Load the demo data with the seed script (task F07).")
        return

    labels = {
        member_id: f"{full_name} ({role})" for member_id, full_name, role in people
    }
    chosen = st.selectbox(
        "Sign in as", options=list(labels), format_func=labels.get, key="demo_pick"
    )
    if st.button("Continue", type="primary"):
        st.session_state["member_id"] = chosen
        st.rerun()


@st.fragment(run_every="10s")
def _unread_count(engine: Engine, member_id: int) -> None:
    """Redraw only the unread notification count, every ten seconds.

    The fragment holds the text alone: a fragment rerun does not re-register
    the navigation, so anything page-shaped has to be drawn outside it.

    Rules: section 11 (sidebar).
    """
    with engine.begin() as conn:
        unread = db.unread_count(conn, member_id)
    st.caption(f"{unread} unread" if unread else "No unread notifications")


def _sidebar(engine: Engine, actor: Actor, inbox_page: st.Page | None) -> None:
    """Show who is signed in, their balance, unread count and Log out.

    Takes the Inbox Page that st.navigation already registered, because
    st.page_link only accepts a page the navigation knows about.

    Rules: section 11 (sidebar), R1.7.
    """
    with st.sidebar:
        st.markdown(f"**{ui.plain(actor.full_name)}**")
        st.caption(actor.role.value.replace("_", " ").capitalize())

        if actor.role == Role.STUDENT:
            with engine.begin() as conn:
                st.metric("Credits", db.ledger_balance(conn, actor.id))

        if inbox_page is not None:
            st.page_link(inbox_page, icon=":material/mail:")
        _unread_count(engine, actor.id)

        if st.button("Log out", use_container_width=True):
            st.session_state.clear()
            st.rerun()


def _pages_for(actor: Actor) -> dict[str, st.Page]:
    """Build this role's Page objects once, keyed by screen.

    One object per screen, so the navigation and the sidebar link point at
    the same page rather than at a path.

    Rules: section 3, section 11.
    """
    return {
        key: st.Page(_PAGES[key][1], title=_PAGES[key][0])
        for key in _NAVIGATION.get(actor.role, _NAVIGATION[Role.STUDENT])
    }


def main() -> None:
    """Set the page up, gate on sign-in, then run the chosen screen.

    Rules: section 8, section 11, R1.7.
    """
    st.set_page_config(page_title="LineUp", page_icon="🌊", layout="centered")
    engine = ui.get_engine()

    actor = ui.current_actor(engine)
    if actor is None:
        # A stale id (the member was deleted) must not strand the session.
        st.session_state.pop("member_id", None)
        if _demo_mode():
            _demo_login(engine)
        else:
            st.navigation([st.Page("app_pages/login.py", title="Log in")]).run()
        return

    pages = _pages_for(actor)
    # st.navigation must register the pages before the sidebar links to one.
    navigation = st.navigation(list(pages.values()))
    _sidebar(engine, actor, pages.get("inbox"))
    navigation.run()


main()
