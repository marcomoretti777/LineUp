# Architecture

LineUp is a Streamlit app in five layers. Screens collect input and show
results; services check, apply and save each action in one transaction;
rules decide what is allowed as pure functions; storage holds the tables
and queries; one module each talks to Open-Meteo and to Supabase Auth.

Spec: `docs/product-spec.md`, sections 8 (architecture), 9 (data model)
and 11 (screens). Shared names: `docs/contract.md`.

## The layers

| Layer | Files | Job | May import |
| --- | --- | --- | --- |
| Screens | `app.py`, `app_pages/*.py`, `lineup/ui.py` | Collect input, call one service, show its `Result` | Streamlit, services, `ui`, `timeutil`, `models` |
| Services (actions) | `lineup/services/*.py` | Load the actor, check permissions, ask the rule, write everything and its notifications in one transaction, return a `Result` | `db`, `queries`, `logic`, `permissions`, `models`, `config`, `timeutil`; never Streamlit |
| Rules | `lineup/logic/*.py` | Pure functions: given plain values, return a refusal `Result` or `None` | `models`, `config`; never Streamlit, SQLAlchemy, httpx or the clock ("now" is a parameter) |
| Storage | `lineup/schema.py`, `lineup/db.py`, `lineup/queries/<lane>.py` | Table definitions (12 tables, one file), the engine and shared queries, and each lane's own queries | SQLAlchemy Core |
| External services | `lineup/openmeteo.py`, `lineup/auth.py` | The only file that calls Open-Meteo; the only file that calls Supabase Auth | httpx; supabase |

Cross-cutting modules every layer may use:

- `lineup/models.py`: `Result`, the error `Code`s and their message templates, enums and the `Actor`, `SessionView` and `Condition` dataclasses.
- `lineup/config.py`: policy numbers, beach coordinates, time zone, and `get_secret`, the only place secrets are read.
- `lineup/timeutil.py`: naive UTC in the database, Europe/Lisbon on screen.
- `lineup/permissions.py`: the permission matrix of spec section 3 as data, and `require(actor, action, owner_id)`.
- `scripts/seed.py`: creates the tables and loads the demo members, sessions, bookings and credit history (spec section 14).

### What calls what

```text
 browser
    │
    ▼
 app.py ── login gate, navigation by role, sidebar ──► lineup/auth.py ──► Supabase Auth
    │
    ▼
 app_pages/<screen>.py ── ui.run_action(service, ...) ──► ui.show_result(result)
    │
    ▼
 lineup/services/<lane>.py   one `with engine.begin() as conn:` per action
    │        │                 │                      │
    │        ▼                 ▼                      ▼
    │   permissions.require  logic/<lane>.py      db.py + queries/<lane>.py
    │   (fail closed)        (pure rules)              │
    │                                                  ▼
    │                                          schema.py tables
    │                                   Supabase Postgres (live) / SQLite (local, tests)
    ▼
 services/forecast.py ──► lineup/openmeteo.py ──► Open-Meteo Marine and Forecast APIs
```

Screens never touch the database or an outside service directly, with one
exception noted below. Every action goes through a service, which is also
where the tests plug in: a test calls the service with an in-memory SQLite
engine and a fixed `now`.

> **Note (code and spec):** the sidebar in `app.py` reads the credit
> balance and the unread count straight from `lineup/db.py`
> (`db.ledger_balance`, `db.unread_count`), and the local demo picker reads
> the members table, because these are read-only shell concerns with no
> service behind them. No screen writes without a service.

## The click path: booking a session

Spec section 8 lists six steps. Here they are with the real code of
`book()` in `lineup/services/booking.py`.

**1. The page collects the input and calls one service.**
The Sessions screen (spec section 11) shows a card for each session in the
next 14 days: time in Lisbon, level, instructor, places left or waitlist
length, the conditions badge and the student's own status. Pressing
**Book** opens an `st.dialog` that states the credit used, the
free-cancellation deadline and the current label. Confirming calls
`ui.run_action(booking.book, engine, actor.id, session_id)`. The screen
passes the actor's id, never a role.

**2. The service opens one transaction, reloads the actor and checks permissions.**

```python
# lineup/services/booking.py:201-207
with engine.begin() as conn:
    actor = db.get_actor(conn, actor_id)
    if actor is None:
        return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
    denied = require(actor, Action.BOOK, owner_id=actor.id)
    if denied:
        return denied
```

The role comes from the database inside the transaction
(`lineup/db.py:125`), so a member demoted a second ago is already refused.
Booking creates a record for the actor, so the service passes
`owner_id=actor.id`, as the ownership rule in `docs/contract.md` requires.

**3. It loads the data and asks the pure rule.**

```python
# lineup/services/booking.py:208-226
session = db.get_session(conn, session_id)
...
db.lock_member(conn, actor.id)
balance = db.ledger_balance(conn, actor.id)
clash_at = _clash_at(conn, actor.id, session)
refused = rules.check_can_book(role=actor.role, session_status=session.status,
                               now=now, starts_at=session.starts_at,
                               already_booked=..., has_clash=..., balance=balance, ...)
```

- `db.lock_member` (`lineup/db.py:142`) runs `SELECT ... FOR UPDATE` on the
  member row before the balance is read, so two tabs cannot both spend the
  last credit on Postgres. SQLite serialises writes on its own.
- `db.ledger_balance` (`lineup/db.py:174`) is the sum of the member's
  ledger rows: there is no balance column.
- `check_can_book` (`lineup/logic/booking.py:65`) takes plain values,
  including `now`, and checks R3.1 (students only), R3.2 and R3.3 (scheduled,
  and before the two-hour cutoff), R3.7 (no duplicate), R3.5 (no clash) and
  R3.4 (at least one credit), in that order.

> **Note (code and spec):** R3.6, the level rule for Intermediate sessions
> (a "Should" in the spec), is not among the checks in `check_can_book`
> today; `Code.LEVEL` and its message exist in `lineup/models.py`.

**4. If refused, it returns a failed Result and writes nothing.**
`return refused` leaves the `with` block normally, but nothing has been
written yet, so the transaction commits no change. The `Result` carries a
`Code` (for tests) and the catalogue message from `lineup/models.py` (for
people).

**5. If allowed, it writes every change and its notification in the same transaction.**

```python
# lineup/services/booking.py:229-246
if not q.reserve_place(conn, session.id):
    return Result.fail(Code.FULL, fill(Code.FULL), data={"can_join_waitlist": True})
booking_id = q.insert_booking(conn, session.id, actor.id, now)
db.ledger_add(conn, actor.id, -1, LedgerKind.BOOKING, f"booking:{booking_id}")
... # a waiting entry for this session becomes "promoted" (R3.9)
db.notify(conn, actor.id, "booking", message)
return Result.success(message, {"booking_id": booking_id, "free_cancel_until": ...})
```

- `q.reserve_place` (`lineup/queries/booking.py:63`) is the atomic place:
  one `UPDATE surf_sessions SET booked_count = booked_count + 1 WHERE id = :id
  AND status = 'scheduled' AND booked_count < capacity`. One changed row
  means the place was taken; zero means someone else got it first, and the
  student is offered the waitlist (R3.8).
- `db.ledger_add` (`lineup/db.py:155`) writes the `booking:<id>` row; the
  unique `ref` makes a double charge impossible (R10.8).
- `db.notify` (`lineup/db.py:185`) adds the notification in the same
  transaction, so a failed booking never leaves a "Booked" message behind.

**6. The page shows the result.**
`ui.show_result` (`lineup/ui.py`) shows a success box and a toast, for
example "Booked: Fri 20 Nov, 10:00. 2 credits left. Free cancellation until
Thu 19 Nov, 10:00.", or the error message. If the service raised instead,
`ui.run_action` logs the traceback with a six-character reference and shows
"Something went wrong (ref 7F2K9Q). Please try again."; no stack trace ever
reaches the screen.

The test for this path is `tests/test_booking.py`; the conftest fixture
runs `db.check_invariants` after each test, so a booking that left
`booked_count` and the confirmed bookings out of step would fail even
without an assertion for it.

## Where each lane's files live

Ownership comes from `docs/contract.md`. Each lane changes only its own
files; shared files change through the lead.

### Lead (Member 1): foundation, accounts, integration

- Shell and screens: `app.py`, `app_pages/login.py`, `app_pages/admin_members.py`, `lineup/ui.py`
- Core: `lineup/config.py`, `lineup/models.py`, `lineup/timeutil.py`, `lineup/permissions.py`
- Storage: `lineup/schema.py`, `lineup/db.py`
- Accounts: `lineup/auth.py`, `lineup/logic/accounts.py`, `lineup/services/members.py`
- Data: `scripts/seed.py`
- Tests: `tests/conftest.py`, `test_smoke.py`, `test_core_types.py`, `test_permissions.py`, `test_db_core.py`, `test_persistence.py`, `test_accounts.py`, `test_members.py`, `test_seed.py`, `test_scenarios.py`
- Docs: `README.md`, `docs/*` (except `docs/lanes/`)

### Member 2: Booking

- Screens: `app_pages/sessions.py`, `app_pages/my_bookings.py`
- Rules, actions, queries: `lineup/logic/booking.py`, `lineup/services/booking.py`, `lineup/queries/booking.py`
- Tests: `test_booking_rules.py`, `test_booking.py`, `test_cancellation.py`, `test_waitlist.py`, `test_booking_views.py`
- Lane doc: To be linked (`docs/lanes/booking.md`)

### Member 3: Sessions and forecast

- Screens: `app_pages/instructor_sessions.py`, `app_pages/admin_settings.py`
- Rules: `lineup/logic/sessions.py`, `lineup/logic/conditions.py`
- Actions: `lineup/services/sessions.py`, `lineup/services/forecast.py`
- External API: `lineup/openmeteo.py`
- Queries: `lineup/queries/sessions.py`, `lineup/queries/forecast.py`
- Tests: `test_session_rules.py`, `test_sessions.py`, `test_openmeteo.py`, `test_conditions.py`, `test_forecast.py`, `test_call_off.py`, `tests/fixtures/*`
- Lane doc: To be linked (`docs/lanes/sessions-forecast.md`)

### Member 4: Credits and reports

- Screens: `app_pages/credits.py`, `app_pages/inbox.py`, `app_pages/roster.py`, `app_pages/admin_requests.py`, `app_pages/admin_reports.py`
- Rules: `lineup/logic/credits.py`, `lineup/logic/reports.py`
- Actions: `lineup/services/credits.py`, `lineup/services/notifications.py`, `lineup/services/attendance.py`, `lineup/services/reports.py`
- Queries: `lineup/queries/credits.py`, `lineup/queries/reports.py`
- Tests: `test_credit_rules.py`, `test_credits.py`, `test_notifications.py`, `test_attendance.py`, `test_reports.py`
- Lane doc: To be linked (`docs/lanes/credits-reports.md`)

### Functions one lane calls in another

Defined in `docs/contract.md`; the lead created stubs so callers could code
against them before the owner filled them in.

| Function | Owner | Called by |
| --- | --- | --- |
| `services.booking.promote_waitlist(conn, session_id, now)` | Booking | Cancellation, and any action that frees a place |
| `services.forecast.conditions_for_sessions(engine, sessions, now)` | Sessions and forecast | The Sessions screen and "Needs your decision" |
| `services.forecast.sunset_for(engine, day)` | Sessions and forecast | The latest-end rule for new sessions (R2.7) |
| `services.sessions.call_off(engine, actor_id, session_id, category, reason, now)` | Sessions and forecast | My sessions and Roster |

## Where the code differs from the spec

- **Lane query files.** Spec section 8 says `lineup/db.py` holds "every
  query". The code keeps only shared queries in `db.py` (actor, ledger,
  notifications, sessions, invariants) and puts each lane's queries in
  `lineup/queries/<lane>.py`, as `AGENTS.md` says. See `docs/decisions.md`.
- **Row Level Security.** Spec section 12 has `scripts/seed.py` enable it.
  The code does it in `db.init_db` (`lineup/db.py:91`, through
  `rls_statements`), which runs on every app start, so any Postgres
  database the app opens is covered, seeded or not.
- **`Result` field order.** Spec section 8 writes `Result(ok, code,
  message, data)`; the dataclass in `lineup/models.py` is `Result(ok,
  message, code=None, data=None)`, built through `Result.success` and
  `Result.fail`. The fields are the same.
