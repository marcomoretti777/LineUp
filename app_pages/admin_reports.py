"""Reports screen: period picker, KPI row, three charts and three CSV downloads.

Every number comes from lineup.services.reports and lineup.logic.reports; this
page only picks the dates, formats the numbers and draws them.

Rules: section 11 (Reports), LU13, R12.1-R12.8.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lineup import ui
from lineup.logic.credits import fmt_eur
from lineup.logic.reports import calloffs_total
from lineup.services import reports
from lineup.timeutil import local_date, utcnow

_PERIODS = ("This month", "Last month", "Custom")
_CATEGORIES = {"conditions": "Conditions", "instructor_unavailable": "Instructor unavailable",
               "other": "Other"}
_NO_DATA = "No data for this period."


def _rate(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def _period() -> tuple[date, date]:
    """Turn the picker into a start and end Lisbon date; the service checks them.

    Rules: R12.1.
    """
    today = local_date(utcnow())
    first = today.replace(day=1)
    choice = st.segmented_control("Period", _PERIODS, default="This month",
                                  key="reports_period") or "This month"
    if choice == "This month":
        return first, today
    if choice == "Last month":
        last_end = first - timedelta(days=1)
        return last_end.replace(day=1), last_end
    start_col, end_col = st.columns(2)
    start = start_col.date_input("Start", value=first, key="reports_start")
    end = end_col.date_input("End", value=today, key="reports_end")
    return start, end


def _metrics(data: dict) -> None:
    """Show the KPI row; a rate with nothing to divide shows "—".

    Rules: R12.2-R12.6.
    """
    top = st.columns(3)
    top[0].metric("Sessions run", data["sessions_run"])
    top[1].metric("Called off", calloffs_total(data["calloffs"]))
    top[2].metric("Fill rate", _rate(data["fill_rate"]))
    bottom = st.columns(3)
    bottom[0].metric("No-show rate", _rate(data["no_show_rate"]))
    bottom[1].metric("Credits sold", data["credits_sold"])
    bottom[2].metric("Revenue", fmt_eur(data["revenue_cents"]))


def _bar(title: str, counts: dict, x: str, y: str, y_label: str | None = None) -> None:
    st.markdown(f"**{title}**")
    if not counts:
        st.caption(_NO_DATA)
        return
    frame = pd.DataFrame({x: list(counts), y: list(counts.values())})
    st.bar_chart(frame, x=x, y=y, y_label=y_label or y)


def _charts(data: dict) -> None:
    """Draw bookings per week, fill rate by level and call-offs by category.

    Rules: R12.3, R12.6.
    """
    _bar("Bookings per week", data["bookings_per_week"], "Week", "Bookings")
    _bar("Fill rate by level",
         {level.capitalize(): rate for level, rate in data["fill_rate_by_level"].items()},
         "Level", "Fill rate", y_label="Fill rate (1.0 = every place taken)")
    _bar("Call-offs by category",
         {_CATEGORIES.get(c, c): n for c, n in data["calloffs_by_category"].items()},
         "Category", "Call-offs")


def _downloads(engine, actor_id: int, start: date, end: date) -> None:
    """Offer the bookings, ledger and requests CSV files for the period.

    Rules: R12.7, R12.8.
    """
    columns = st.columns(3)
    for column, (label, name, export) in zip(columns, [
        ("Bookings CSV", "bookings", reports.bookings_csv),
        ("Ledger CSV", "ledger", reports.ledger_csv),
        ("Requests CSV", "requests", reports.requests_csv),
    ], strict=True):
        result = ui.run_action(export, engine, actor_id, start, end)
        if result is None:
            continue
        if not result.ok:
            ui.show_result(result)
            continue
        column.download_button(label, result.data, mime="text/csv",
                               file_name=f"lineup-{name}-{start}_{end}.csv")


def main() -> None:
    """Draw the Reports screen for an admin.

    Rules: section 11 (Reports), LU13.
    """
    engine = ui.get_engine()
    ui.inject_styles()
    actor = ui.current_actor(engine)
    if actor is None:
        st.stop()

    ui.page_header("Reports", "How the club is doing over a period.")
    start, end = _period()

    numbers = ui.run_action(reports.kpis, engine, actor.id, start, end)
    if numbers is None:
        return
    if not numbers.ok:
        # An invalid period or a missing permission: say why and draw nothing else.
        ui.show_result(numbers)
        return
    st.caption(numbers.message)
    _metrics(numbers.data)

    charts = ui.run_action(reports.chart_data, engine, actor.id, start, end)
    if charts is not None and charts.ok:
        _charts(charts.data)
    elif charts is not None:
        ui.show_result(charts)

    # Secondary: exports sit behind a click so the numbers lead.
    with st.expander("Downloads"):
        _downloads(engine, actor.id, start, end)


main()
