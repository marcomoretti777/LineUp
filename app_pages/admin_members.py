"""Members: the admin screen for roles, levels and balances.

The screen never checks the role itself; permissions.require inside
services/members.py is the check, so reaching this page without being an
admin shows the forbidden message rather than any data.

Rules: R1.5, R1.6, section 11 (Members screen).
"""

import streamlit as st

from lineup import ui
from lineup.models import Level, Role
from lineup.services import members

engine = ui.get_engine()
actor = ui.current_actor(engine)

st.title("Members")

search = st.text_input("Search by name or email", key="members_search",
                       placeholder="Ana, or lineup.ana@novasbe.pt")

listed = ui.run_action(members.list_members, engine, actor.id if actor else 0, search)

if listed is None:
    st.stop()
if not listed.ok:
    ui.show_result(listed)
    st.stop()

people = listed.data
if not people:
    st.info("No members match that search.")
    st.stop()

st.dataframe(
    [
        {
            "Name": person["full_name"],
            "Email": person["email"],
            "Role": person["role"],
            "Level": person["level"],
            "Credits": person["balance"],
        }
        for person in people
    ],
    hide_index=True,
    width="stretch",
)

st.subheader("Change a member")

by_id = {person["id"]: person for person in people}
chosen_id = st.selectbox(
    "Member",
    options=list(by_id),
    format_func=lambda member_id: f"{by_id[member_id]['full_name']}"
                                  f" ({by_id[member_id]['role']})",
    key="members_chosen",
)
chosen = by_id[chosen_id]

# plain() because the name is text a member typed at sign-up.
st.caption(f"{ui.plain(chosen['full_name'])} — {chosen['balance']} credits")

roles = [role.value for role in Role]
levels = [level.value for level in Level]
left, right = st.columns(2)
with left:
    new_role = st.selectbox("Role", options=roles,
                            index=roles.index(chosen["role"]), key="members_role")
with right:
    new_level = st.selectbox("Level", options=levels,
                             index=levels.index(chosen["level"]), key="members_level")

if st.button("Save", type="primary"):
    changed = False
    if new_role != chosen["role"]:
        changed = True
        ui.show_result(ui.run_action(
            members.change_role, engine, actor.id, chosen_id, new_role))
    if new_level != chosen["level"]:
        changed = True
        ui.show_result(ui.run_action(
            members.change_level, engine, actor.id, chosen_id, new_level))
    if not changed:
        st.info("Nothing to save: the role and level are unchanged.")
