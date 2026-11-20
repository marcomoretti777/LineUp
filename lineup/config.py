"""Policy numbers, spot coordinates, time zone and secret lookup.

This is the only module that reads secrets (AGENTS.md). Values come from
spec section 5 and the rules that name them.
"""

from __future__ import annotations

import os
from datetime import time, timedelta

TIMEZONE = "Europe/Lisbon"
LATITUDE = 38.68
LONGITUDE = -9.34

EARLIEST_START = time(8, 0)
FALLBACK_LATEST_END = time(17, 0)
START_STEP_MIN = 15
MIN_LEAD = timedelta(hours=3)
MAX_DAYS_AHEAD = 14
DURATIONS = (60, 90, 120)
CAPACITY_MIN = 1
CAPACITY_MAX = 8

BOOKING_CUTOFF = timedelta(hours=2)
REFUND_WINDOW = timedelta(hours=24)

ALLOWED_EMAIL_DOMAIN = "novasbe.pt"

# (go_wave_m, go_wind_kmh, marginal_wave_m, marginal_wind_kmh); example club
# policy, not safety advice, and admins can change it in Settings.
DEFAULT_THRESHOLDS = {
    "beginner": (1.5, 25, 2.0, 35),
    "intermediate": (2.5, 30, 3.0, 40),
}

FORECAST_REFRESH = timedelta(minutes=60)
FORECAST_RETRY = timedelta(minutes=10)
FORECAST_STALE = timedelta(hours=12)
HTTP_TIMEOUT_S = 5

# (name, credits, price in cents)
CREDIT_PACKS = [
    ("1 session", 1, 1500),
    ("5 sessions", 5, 6500),
    ("10 sessions", 10, 12000),
]


def get_secret(name: str) -> str | None:
    """Return a setting from the environment, then from st.secrets, else None.

    Streamlit is imported inside the function so logic, services and tests
    can import config without Streamlit or a secrets file.

    Rules: section 12 (secrets).
    """
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:
        # No secrets file, or Streamlit not running: treat as not configured.
        return None
    return str(value) if value else None


def demo_mode_allowed(database_url: str | None, supabase_url: str | None) -> bool:
    """Say whether passwordless demo mode may run.

    Allowed only with no Supabase URL and a local SQLite database (or no
    database URL, which means the default SQLite file).

    Rules: R1.7.
    """
    if supabase_url:
        return False
    if not database_url:
        return True
    return database_url.startswith("sqlite")
