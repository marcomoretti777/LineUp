# Known limits, risks and how LineUp could change

These limits are known and accepted for a three-week student project.
Each one follows from a design choice; `docs/decisions.md` gives the
reasons for those choices. Spec: `docs/product-spec.md`, section 18.

## Known limits

| Limit | Why it exists | Effect | Rests on |
| --- | --- | --- | --- |
| Changes by others appear within about 10 seconds, not instantly | Streamlit polls with fragments; there is no push | Another user's change shows on the next refresh | `st.fragment(run_every="10s")` in `app.py` |
| Refreshing the browser logs you out | The session lives in Streamlit's memory, not in a cookie | Log in again | `st.session_state["member_id"]`, read by `ui.current_actor` in `lineup/ui.py` |
| The app sleeps when unused | Free Streamlit Community Cloud | The first visit can take up to a minute | Hosting, not code |
| The database pauses after a week without use | Free Supabase plan | Unpause it from the dashboard | `DATABASE_URL`, read through `config.get_secret` and opened by `db.make_engine` |
| The forecast reaches about a week ahead | The requested forecast range (`forecast_days=7`) | Later sessions show Unknown | `lineup/openmeteo.py`; R6.4 in `lineup/logic/conditions.py` |
| The forecast describes a sea grid cell, not the beach | Wave models run on an ocean grid | Labels are advice; the instructor decides | `config.LATITUDE`, `config.LONGITUDE`; R6.5 |
| The sign-up domain rule checks format, not ownership | Email confirmation is off for the demo | Anyone can register an @novasbe.pt address as a student | `config.ALLOWED_EMAIL_DOMAIN`, `lineup/logic/accounts.py`, `lineup/auth.py` |
| No real payments | Out of scope | An admin confirms each payment by hand | `lineup/services/credits.py` (approval writes the `purchase:` ledger row) |
| One beach, one time zone | Scope | Coordinates and Lisbon time are fixed in `config.py` | `config.TIMEZONE`, `config.LATITUDE`, `config.LONGITUDE`; `lineup/timeutil.py` |
| Tests run on SQLite; production runs on Postgres | Tests must need no secrets | Postgres-only differences are untested | `tests/conftest.py` (in-memory SQLite), `db.make_engine` |

Notes on two rows, where the code adds detail to the spec:

- **Postgres-only behaviour.** The known differences are covered in code,
  not tests: `db.lock_member` uses `SELECT ... FOR UPDATE`, which only
  Postgres honours, and `db.init_db` enables Row Level Security only on
  Postgres. Both are reasoned about, not tested.
- **Live refresh.** The fragment reruns only its own part of the page. A
  change to anything outside a fragment, such as a session card, shows on
  the member's next click or rerun.

## Risks and fallbacks

| Risk | Fallback |
| --- | --- |
| The eight-day timeline slips | Cut line on Thu 19 Nov: drop T11 and stretch work, never tests |
| A free agent quota runs out mid-task | Each member has their own quota; hand the task to a teammate or pair on one laptop |
| Open-Meteo is down during the demo | The saved forecast with its time, or Unknown; a retry after 10 minutes; booking keeps working. The fallback is part of the demo (step 10) |
| Supabase pauses before 4 Dec | Open the app or the dashboard every five days; check the day before |
| A secret reaches GitHub | Rotate it in the dashboard at once, update local and host settings, check the usage page |
| A demo account fails on the day | Log in with every account on the deployed app the day before |

## How LineUp could change

These are deliberate future changes, planned but out of scope now. Each
names where it would plug in.

- **Second beach (planned):** a `spots` table with coordinates; sessions
  and forecast rows gain a spot id. Today the coordinates are constants in
  `lineup/config.py` and the forecast tables are keyed by hour and day only.
- **Real payments (planned):** a payment provider's confirmation replaces
  the admin's approval and writes the same `purchase:` ledger row through
  `db.ledger_add`. The ledger, the balance and the reports stay as they are.
- **Email or Telegram notifications (planned):** `db.notify` is the one
  place notifications are created, so a sender plugs in there.
- **Instant updates (planned):** a JavaScript front end with Supabase
  Realtime replaces the screens; services and rules stay as they are,
  because neither imports Streamlit.
- **Smarter labels (planned):** wave period and wind direction join the
  rules in `lineup/logic/conditions.py`, and thresholds become a table per
  spot and level instead of one row per level in `condition_thresholds`.
- **Postgres in CI (planned, spec section 19):** run the whole suite on a
  Postgres service container as well, which removes the last row of the
  limits table.
