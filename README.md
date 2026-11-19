# LineUp: surf session booking for a campus surf club

Live app: (added after the first deploy)

Students book surf sessions with prepaid credits, instructors run and call off sessions, and admins approve payments and read reports. Live wave and wind forecasts from Open-Meteo label every session Go, Marginal, No-go or Unknown.

## Team

| Name | Student number |
| --- | --- |
| Guilherme [surname] | [student number] |
| Diogo [surname] | [student number] |
| Lisa [surname] | [student number] |
| Marco [surname] | [student number] |

## Try it

To be completed in task F09.

## Run it locally

1. Install uv: https://docs.astral.sh/uv/
2. `uv sync`
3. `uv run python scripts/seed.py` (creates `data/lineup.db` with demo data)
4. `uv run streamlit run app.py`

With no secrets file the app runs in local demo mode on the SQLite file: pick a demo user instead of logging in. To use Supabase, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill it in. Never commit that file.

## Run the tests

`uv run pytest -q` (no secrets or network needed)

## How it is built

- Screens: `app.py`, `app_pages/`
- Rules: `lineup/logic/`
- Actions and permission checks: `lineup/services/`
- Storage: `lineup/schema.py` and `lineup/db.py` (Supabase Postgres live; SQLite locally and in tests)
- Forecast: `lineup/openmeteo.py` and `lineup/services/forecast.py`
- Architecture, decisions and limits: `docs/`

## If Open-Meteo is down

The app shows the last saved forecast with its time, or Unknown if none is usable. Booking keeps working; labels never block or cancel anything.

## What the tests cover and do not cover

About 200 test cases, run in under a minute with no secrets and no network. Every business rule gets an allowed case, a refused case and its boundary.

Covered, file by file: to be completed in task F09.

| Not covered by automated tests | How it is checked instead |
| --- | --- |
| Screen layout and wording | `docs/manual-test-checklist.md`, run on the deployed app |
| Real Supabase Auth | Logging in with each demo role on the deployed app |
| The live Open-Meteo service | One manual call on Day 0; the fixtures are recorded from it |
| Truly simultaneous clicks | The atomic update is tested in sequence; Postgres row locking is reasoned about, not tested |
| Postgres-only behaviour | Stretch: run the whole suite on Postgres in CI |

## Dependencies

| Package | Minimum version | Job |
| --- | --- | --- |
| streamlit | 1.40 | Interface; `st.navigation`, `st.dialog` and `st.fragment` need a recent version |
| sqlalchemy | 2.0 | Database access (Core only) |
| psycopg\[binary\] | 3.2 | Postgres driver for the live database |
| supabase | 2.0 | Login calls; only `lineup/auth.py` imports it |
| httpx | 0.27 | Open-Meteo calls; already installed with supabase, declared because we import it |
| pandas | 2.0 | Tables and charts on the reports page; already installed with Streamlit |
| tzdata | 2024.1 | Time-zone data so `zoneinfo` works on Windows laptops |
| pytest (dev only) | 8.0 | Tests |

`uv.lock` is the only dependency file; there is no `requirements.txt`.

## Credits

Weather data: Open-Meteo.com, wave models by Météo-France, ECMWF, NOAA and DWD (https://open-meteo.com/en/licence).
