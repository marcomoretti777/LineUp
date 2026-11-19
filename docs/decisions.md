# Design decisions

Each entry gives the choice, the alternative we rejected and why, and where
the choice shows in the code. Spec: `docs/product-spec.md`, sections 7, 8
and 12. A pull request that changes `pyproject.toml` needs an entry here
(spec section 12, Dependencies).

## 1. Streamlit, not a JavaScript stack

- **Chosen:** Python 3.12 and Streamlit, multipage with `st.navigation`,
  `st.dialog` for confirmations and `st.fragment(run_every=...)` for live
  refresh.
- **Rejected:** a JavaScript front end (for example React or Next.js) over
  an API.
- **Why:** Streamlit is the course stack, so it needs no approval, and the
  whole team already writes Python. LineUp is forms, cards and tables, which
  is what Streamlit does well. A JavaScript stack would add a second
  language, a build step and an API layer for a three-week project.
- **Cost we accept:** no push updates (decision 5), and a browser refresh
  ends the session, because sign-in lives in `st.session_state`
  (`docs/limits.md`).
- **In the code:** `app.py` builds the navigation by role; only `app.py`,
  `app_pages/` and `lineup/ui.py` import Streamlit. Services and rules have
  no Streamlit in them, so a different front end could reuse them unchanged.

## 2. Supabase Postgres, not SQLite on the host

- **Chosen:** Supabase Postgres for the live app, reached through the
  session pooler; SQLite only for tests (in memory) and local runs (a file).
- **Rejected:** a SQLite file on the hosting machine.
- **Why:** Streamlit Community Cloud gives no lasting disk: a file database
  would be wiped on every restart or redeploy, and every user must see the
  same data. Supabase is the course's standard database and also provides
  the login service (`lineup/auth.py`), so one account covers both.
- **In the code:** `db.make_engine` (`lineup/db.py`) takes `DATABASE_URL`
  from `config.get_secret`; with none it uses `data/lineup.db`. Postgres
  engines use `pool_pre_ping`, because the pooler drops idle connections.

## 3. SQLAlchemy Core, not plain sqlite3

- **Chosen:** SQLAlchemy 2 Core (no ORM) with bound parameters.
- **Rejected:** the standard library's `sqlite3` with hand-written SQL;
  also the SQLAlchemy ORM.
- **Why:** `sqlite3` only reaches SQLite, so production on Postgres would
  need a second set of queries. Core runs one set of queries on both, and
  tests on SQLite exercise the same code that runs live. Core keeps the SQL
  visible (for example the one-statement place reservation), where an ORM
  would hide it behind objects. Bound parameters remove SQL injection by
  construction.
- **In the code:** tables in `lineup/schema.py`; partial unique indexes use
  `sqlite_where` and `postgresql_where` so one definition works on both.
  `db.lock_member` uses `with_for_update()`, which Postgres honours and
  SQLite ignores.

## 4. A credit ledger, not a balance column

- **Chosen:** every credit change is a row in `credit_ledger` with a unique
  `ref` such as `purchase:12`, `booking:57` or `refund:57`; the balance is
  the sum of a member's rows (R10.7, R10.8).
- **Rejected:** a `balance` column on `members`, incremented and
  decremented.
- **Why:** a column says how many credits someone has but not why. The
  ledger makes every change traceable for the statement and the reports,
  and the unique reference makes a double refund or double charge
  impossible: the second `refund:57` is refused. Rows are never edited or
  deleted.
- **In the code:** `db.ledger_add` checks the `ref` before inserting and
  returns `False` if it exists (a failed insert would abort the whole
  transaction on Postgres); the unique constraint stays as the last line of
  defence. `db.ledger_balance` sums the rows. `db.check_invariants` checks
  that no ledger goes below zero and that each booking has exactly one
  `booking:` row and at most one `refund:` row.

## 5. Polling every 10 seconds, not push

- **Chosen:** `st.fragment(run_every="10s")` redraws the parts that change
  because of other people, such as the unread count in the sidebar.
- **Rejected:** push updates (WebSockets or Supabase Realtime).
- **Why:** Streamlit has no way to receive a push from the database into a
  running page. Realtime would need a JavaScript client, which is decision 1
  in reverse. Ten seconds is fast enough for a booking app, and the fragment
  reruns only its own small part, not the page.
- **In the code:** `_unread_count` in `app.py` is the fragment. It holds
  only the text, because a fragment rerun does not re-register the
  navigation.

## 6. Open-Meteo, not a paid surf API

- **Chosen:** the Open-Meteo Marine API (wave height) and Forecast API
  (wind speed, sunset), keyless, at most once an hour (spec section 10).
- **Rejected:** paid surf-forecast APIs (Stormglass, Surfline and similar).
- **Why:** Open-Meteo is free for non-commercial use and needs no key, so
  there is no secret to leak and no card to give. It provides exactly the
  numbers the rules use. Paid APIs need a key, often a card, and have small
  free quotas a demo could exhaust. The cost is a model grid cell rather
  than the beach itself (`docs/limits.md`), and the credit line Open-Meteo
  asks for.
- **In the code:** `lineup/openmeteo.py` is the only file that calls it;
  `lineup/services/forecast.py` decides when to call and falls back to the
  saved forecast; `ui.footer_credit` shows the attribution.

## 7. Labels advise; they never cancel

- **Chosen:** No-go and Unknown never block or cancel a booking (R6.5,
  R3.10). Instructors see their No-go and Unknown sessions under "Needs
  your decision" and call them off themselves (R8).
- **Rejected:** cancelling No-go sessions automatically.
- **Why:** the model forecasts a sea grid cell offshore, not the beach, and
  can be wrong in either direction. The instructor decides; the app advises
  and, on call-off, refunds everyone.
- **In the code:** `logic/booking.check_can_book` has no condition among
  its inputs, so no label can refuse a booking.

## 8. Permissions fail closed

- **Chosen:** every service reloads the actor from the database and calls
  `permissions.require(actor, action, owner_id)` before anything else.
  Anything not explicitly allowed is refused.
- **Rejected:** hiding buttons by role, or a role kept in the session.
- **Why:** a hidden button is not a check, and a role stored at login would
  survive a demotion. Refusing by default means a forgotten case is a
  harmless "no", not a hole.
- **In the code:** `lineup/permissions.py` holds the matrix of spec section
  3 as data. `require` returns `forbidden` when the actor is missing, when
  the action or role is not in the matrix, and for an "own" action when
  `owner_id` is missing or is someone else's. A service that creates a
  record for the actor passes `owner_id=actor.id` (the ownership rule in
  `docs/contract.md`). `ui.current_actor` rereads the member on every
  rerun. `tests/test_permissions.py` covers every cell.

## 9. The Supabase Data API is off; RLS is a second layer

- **Chosen:** the Supabase project was created with the Data API switched
  off and "Enable RLS on new tables automatically" on. The app reaches the
  database only through SQLAlchemy over the session pooler, as the tables'
  owner.
- **Rejected:** leaving the Data API on (Supabase's default), which
  publishes every table in the `public` schema as auto-generated REST
  endpoints reachable with the public anon key.
- **Why:** LineUp never uses those endpoints, and every rule lives in the
  services. With the Data API on, anyone holding the anon key could read or
  write tables while skipping every check.
- **Second layer:** `db.init_db` also runs `ALTER TABLE ... ENABLE ROW
  LEVEL SECURITY` on all 12 tables on Postgres (`db.rls_statements`), with
  no policies. If the API were ever switched on, or the app pointed at a
  fresh database, the API would still see no rows. RLS does not block the
  app, because the app connects as the owner.
- **In the code:** the Data API setting is a deployment setting in the
  Supabase dashboard, not code. The RLS statements are in `lineup/db.py`.
- **Note (code and spec):** spec section 12 puts the RLS step in
  `scripts/seed.py`; the code runs it from `db.init_db` on every start, so
  it no longer depends on the seed having run.

## 10. Lane query files, not one db.py

- **Chosen:** `lineup/db.py` keeps the engine, setup and the queries every
  lane shares (actor, ledger, notifications, sessions, invariants); each
  lane keeps its own queries in `lineup/queries/<lane>.py`.
- **Rejected:** one `lineup/db.py` with every query, as spec section 8
  first described.
- **Why:** four people build in parallel, each owning their own files
  (`docs/contract.md`). One shared query file would make every task touch
  the same file, causing merge conflicts and reviews across lanes. Splitting
  by lane keeps ownership clear, while the shared functions stay in one
  place behind a fixed contract.
- **In the code:** `lineup/queries/booking.py` holds the booking lane's
  queries, including `reserve_place`. Every query function takes an open
  connection, so the calling service still does all its reads and writes in
  one transaction.
- **Note (code and spec):** this differs from spec section 8's folder
  structure, which lists `db.py` as "every query"; `AGENTS.md` records the
  rule the code follows.
