# LineUp: surf session booking for a campus surf club

Live app: LIVE_URL_PENDING

Students book surf sessions with prepaid credits, instructors run and call off sessions, and admins approve payments and read reports. Live wave and wind forecasts from Open-Meteo label every session Go, Marginal, No-go or Unknown.

## Team

| Name | Student number |
| --- | --- |
| Marco Moretti | 78483 |
| Guilherme Natário Rio-Tinto | 73277 |
| Lisa Maria Stirbu | 80706 |
| Diogo Rito Mota Pinto | 75080 |

## Try it

Open LIVE_URL_PENDING and log in with one of the demo accounts below. Their passwords are shared privately with the teaching staff and are never written in this repository.

| Role | Name | Email |
| --- | --- | --- |
| Admin | Marta Silva | lineup.admin@novasbe.pt |
| Instructor | Tiago Costa | lineup.tiago@novasbe.pt |
| Instructor | Inês Rocha | lineup.ines@novasbe.pt |
| Student | Ana Martins | lineup.ana@novasbe.pt |
| Student | Bruno Lopes | lineup.bruno@novasbe.pt |
| Student | Carla Dias | lineup.carla@novasbe.pt |
| Student | Diogo Alves | lineup.diogo@novasbe.pt |

Ana has credits and bookings, Carla has none, and Diogo has a pending credit request, so every screen has something to show.

## Run it locally

1. Install uv: https://docs.astral.sh/uv/
2. `uv sync`
3. `uv run python scripts/seed.py` (creates `data/lineup.db` with the demo data)
4. `uv run streamlit run app.py`

With no secrets file the app runs in local demo mode on the SQLite file: pick a demo user instead of logging in. Running the seed twice is safe and gives the same result.

To use Supabase instead, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill it in. Never commit that file. With Supabase settings present, demo mode turns itself off and the login page is the only way in.

## Run the tests

`uv run pytest -q` (no secrets and no network needed)

## How it is built

- Screens: `app.py`, `app_pages/`
- Rules: `lineup/logic/` (pure functions: no database, network or clock)
- Actions and permission checks: `lineup/services/`
- Storage: `lineup/schema.py`, `lineup/db.py` and `lineup/queries/` (Supabase Postgres live; SQLite locally and in tests)
- Login: `lineup/auth.py`, the only file that talks to Supabase Auth
- Forecast: `lineup/openmeteo.py` and `lineup/services/forecast.py`
- Architecture, decisions and limits: `docs/architecture.md`, `docs/decisions.md`, `docs/limits.md`

Screens never reach the database directly. Every action goes through a service, which loads the actor, checks `lineup/permissions.py`, asks a pure rule, then writes everything in one transaction.

## If Open-Meteo is down

The app shows the last saved forecast with the time it was taken, or Unknown if there is none. Booking keeps working; labels advise and never block or cancel anything.

## What the tests cover and do not cover

**725 tests**, run in under ten seconds with no secrets and no network. Every business rule has an allowed case, a refused case and its boundary.

### Covered, file by file

| File | Tests | Covers |
| --- | --- | --- |
| `test_permissions.py` | 97 | Every cell of the permission matrix of spec section 3 |
| `test_session_rules.py` | 66 | Pure session create, edit and delete rules (R2.1–R2.9, R2.11) |
| `test_booking_rules.py` | 66 | Pure booking, waitlist and cancellation rules (R3, R4.1–R4.2, R5) |
| `test_core_types.py` | 43 | Shared types, configuration, time helpers and demo mode (R1.7) |
| `test_booking_views.py` | 42 | The per-session status helper behind the Sessions page (LU03–LU05) |
| `test_reports.py` | 34 | Report KPIs, period rules, chart data and admin CSV exports (R12.1–R12.8, A17) |
| `test_sessions.py` | 33 | Creating, editing, deleting and listing sessions as a service |
| `test_db_core.py` | 31 | Schema, shared queries and the invariant checks of spec section 9 |
| `test_attendance.py` | 31 | Attendance marking, the roster and formula-safe CSV (R9.1–R9.3, R12.7, R12.8) |
| `test_seed.py` | 30 | The demo seed of spec section 14, including running it twice |
| `test_credit_rules.py` | 29 | Pure credit request rules and money formatting (R10.2–R10.6) |
| `test_accounts.py` | 27 | Sign-up validation and the Supabase Auth wrapper (R1.1–R1.3) |
| `test_credits.py` | 26 | The credit approval workflow as a service (R10.2–R10.8, R11.1) |
| `test_waitlist.py` | 24 | Waitlist join, leave, position and promotion (R4.1–R4.6, R2.10, R11.1) |
| `test_openmeteo.py` | 23 | The Open-Meteo client: requests, parsing and checks (section 10, R7.2) |
| `test_conditions.py` | 23 | Pure condition label rules (R6.1–R6.4) |
| `test_call_off.py` | 20 | Call-off and the "Needs your decision" list (R8.1–R8.5, R10.8, R11.1) |
| `test_forecast.py` | 19 | Hourly refresh, saved fallback and per-session labels (R7, R6.4) |
| `test_members.py` | 17 | First-login profiles and admin role and level changes (R1.4–R1.6) |
| `test_cancellation.py` | 13 | Cancelling a booking as a service (R5.1–R5.4, R10.8) |
| `test_booking.py` | 13 | Booking a session as a service (R3.1–R3.9, R10.7, R10.8, R11.1) |
| `test_notifications.py` | 9 | The notifications service: inbox listing and read state (R11.2–R11.3) |
| `test_scenarios.py` | 6 | Acceptance scenarios A2–A7, end to end through services |
| `test_persistence.py` | 2 | Acceptance scenario A16: data survives a restart |
| `test_smoke.py` | 1 | A placeholder from the first task, kept so CI always has something to run |

### Where each acceptance scenario is tested

Every scenario in spec section 6 has at least one automated test. Several live with their lane's tests rather than in `test_scenarios.py`.

| Scenario | File | Test |
| --- | --- | --- |
| A1 Sign-up domain | `test_accounts.py` | `test_r1_1_padded_mixed_case_novasbe_email_is_accepted`, `test_r1_1_email_outside_the_club_domain_is_refused` |
| A2 Booking cutoff | `test_scenarios.py` | `test_a2_booking_cutoff` |
| A3 Last credit | `test_scenarios.py` | `test_a3_last_credit` |
| A4 Clash | `test_scenarios.py` | `test_a4_clash` |
| A5 Last place | `test_scenarios.py` | `test_a5_last_place` |
| A6 Promotion with a skip | `test_scenarios.py`, `test_waitlist.py` | `test_a6_promotion_with_a_skip`, `test_a6_cancel_30h_before_full_session_refunds_ana_removes_carla_books_bruno` |
| A7 Refund window | `test_scenarios.py` | `test_a7_refund_window` |
| A8 Thresholds | `test_conditions.py` | `test_r6_3_beginner_threshold_edges`, `test_r6_3_intermediate_threshold_edges` |
| A9 Forecast failure | `test_forecast.py` | `test_r7_2_r7_4_failure_uses_saved_data_and_records_attempt`, `test_r7_4_one_feed_failing_saves_nothing_and_uses_saved_data` |
| A10 Beyond range | `test_conditions.py` | `test_r6_4_missing_hour_is_unknown`, `test_r6_4_no_forecast_is_unknown` |
| A11 Call-off | `test_call_off.py` | `test_r8_3_every_confirmed_booking_refunded_once`, `test_r8_3_cancelled_booking_is_not_refunded_again` |
| A12 Wrong person | `test_call_off.py`, `test_credits.py` | `test_r8_1_other_instructor_is_forbidden`, `test_r10_5_r10_6_admin_approves_once` |
| A13 Credit approval | `test_credits.py` | `test_a13_credit_approval` |
| A14 Session validation | `test_sessions.py` | `test_r2_1_start_off_step_rejected`, `test_r2_2_start_under_three_hours_rejected` and the other `test_r2_*` cases |
| A15 Attendance unlocks Intermediate | `test_attendance.py` | `test_r9_1_mark_before_start_is_not_yet`, `test_r9_1_own_instructor_can_mark_from_start` |
| A16 Survives a restart | `test_persistence.py` | `test_a16_member_survives_an_engine_restart`, `test_a16_booking_and_balance_survive_an_engine_restart` |
| A17 Report numbers | `test_reports.py` | `test_a17_report_numbers_on_the_fixed_dataset` |
| A18 Last admin | `test_members.py` | `test_r1_6_demoting_the_only_admin_is_refused_and_changes_nothing` and the other `test_r1_6_*` cases |

The automated tests run against SQLite, so they cannot prove the deployed app behaves the same. `docs/manual-test-checklist.md` walks all eighteen scenarios on the live URL.

### Not covered by automated tests

| Not covered | How it is checked instead |
| --- | --- |
| Screen layout and wording | `docs/manual-test-checklist.md`, run on the deployed app |
| Real Supabase Auth | Logging in with each demo role on the deployed app |
| The live Open-Meteo service | One manual call on Day 0; the fixtures are recorded from it |
| Truly simultaneous clicks | The atomic update is tested in sequence; Postgres row locking is reasoned about, not tested |
| Postgres-only behaviour | The suite runs on SQLite; running it on Postgres in CI is a stretch goal |
| `lineup/ui.py` | The shared Streamlit helpers are exercised only through the screens |

## Not built

| Screen | Why |
| --- | --- |
| Admin Settings (stretch task S08) | The services behind it are built and tested — forecast mode and the per-level thresholds are covered by `test_forecast.py` and `test_conditions.py` (R6.6, R7.6) — but the screen itself was not finished, so it is left out of the admin navigation rather than shipped as a placeholder. Thresholds keep the defaults in `lineup/config.py`. |

## Dependencies

| Package | Minimum version | Job |
| --- | --- | --- |
| streamlit | 1.40 | Interface; `st.navigation`, `st.dialog` and `st.fragment` need a recent version |
| sqlalchemy | 2.0 | Database access (Core only) |
| psycopg\[binary\] | 3.2 | Postgres driver for the live database; loaded by SQLAlchemy, never imported directly |
| supabase | 2.0 | Login calls; only `lineup/auth.py` imports it, inside a function |
| httpx | 0.27 | Open-Meteo calls |
| pandas | 2.0 | Tables and charts on the reports page |
| tzdata | 2024.1 | Time-zone data so `zoneinfo` works on Windows laptops |
| pytest (dev only) | 8.0 | Tests |

`uv.lock` is the only dependency file; there is no `requirements.txt`. CI runs `uv sync --locked` and `pip-audit` on every push and pull request.

## Credits

Weather data: Open-Meteo.com, wave models by Météo-France, ECMWF, NOAA and DWD (https://open-meteo.com/en/licence).
