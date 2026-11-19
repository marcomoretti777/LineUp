"""Entry point: page setup, the login gate and navigation by role.

Business rules live in lineup/logic/ and lineup/services/; this file only
calls config, db and ui.

Rules: section 8, section 11, R1.7.
"""

from __future__ import annotations

import streamlit as st
from sqlalchemy import select
from sqlalchemy.engine import Engine

from lineup import config, schema, ui
from lineup.models import Actor, Role

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


def _demo_members(engine: Engine) -> list[tuple[int, str, str]]:
    """List every member as (id, full name, role) for the demo picker.

    Read straight from storage because demo mode is a shell concern with no
    service behind it; task F06 moves it into services/members.py with the
    rest of the sign-in rules.

    Rules: R1.7.
    """
    query = select(
        schema.members.c.id, schema.members.c.full_name, schema.members.c.role
    ).order_by(schema.members.c.full_name)
    with engine.begin() as conn:
        return [(row.id, row.full_name, row.role) for row in conn.execute(query)]


def _demo_login(engine: Engine) -> None:
    """Show the demo banner and let anyone sign in as any member, no password.

    Rules: R1.7.
    """
    st.title("LineUp")
    st.error(
        "Local demo mode: anyone can sign in as any member without a password. "
        "Never point this at real data."
    )
    members = _demo_members(engine)
    if not members:
        st.info("No members yet. Load the demo data with the seed script (task F07).")
        return

    labels = {
        member_id: f"{full_name} ({role})" for member_id, full_name, role in members
    }
    chosen = st.selectbox(
        "Sign in as", options=list(labels), format_func=labels.get, key="demo_pick"
    )
    if st.button("Continue", type="primary"):
        st.session_state["member_id"] = chosen
        st.rerun()


def _navigation_for(actor: Actor):
    """Build the navigation holding only the screens this role may open.

    Rules: section 3, section 11.
    """
    pages = [
        st.Page(_PAGES[key][1], title=_PAGES[key][0])
        for key in _NAVIGATION.get(actor.role, _NAVIGATION[Role.STUDENT])
    ]
    return st.navigation(pages)


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

    _navigation_for(actor).run()


main()
