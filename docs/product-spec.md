# LineUp — Full Project Spec

Nov 15, 2026 · @Guilherme Rio-Tinto

## 1. Summary

LineUp is a booking app for a campus surf club at Carcavelos beach, where a live ocean forecast labels every session. Students book with prepaid credits, instructors run and call off sessions, and admins approve payments and read the numbers. It is built in Python 3.12 with Streamlit, stores its data in Supabase, and runs at a public URL on Streamlit Community Cloud.

### The problem

A surf club sells lessons in packs, fills small groups and cancels when the sea is too big. Without a system, this runs on group chats and spreadsheets. Last places get double-booked, refunds are forgotten, and nobody knows how full last month's lessons were.

### What LineUp does

- Lists the next 14 days of sessions with places left and a Go, Marginal, No-go or Unknown label computed from wave height and wind.
- Lets students book in one confirmation, cancel with a 24-hour refund window, and join a waitlist that promotes automatically.
- Lets instructors create sessions, take attendance and call a session off, refunding everyone in one step.
- Lets admins approve credit-pack payments, manage roles, tune forecast thresholds and export reports.

### Scope at a glance

| Item | Size |
| --- | --- |
| Roles | 3: student, instructor, admin |
| Screens | 11 |
| Business rules | 12 groups, 78 numbered rules (section 5) |
| Acceptance scenarios | 18 (section 6) |
| External data | 2 Open-Meteo feeds (waves; wind and sunset), no key needed |
| Database tables | 12 (section 9) |
| Automated test cases | About 200, none needing secrets or network (section 13) |

In the interface a lesson is a "session". In code and in the database it is a `surf_session`, so it is never confused with Streamlit's `st.session_state`.

This is the team project for Introduction to Programming at Nova SBE, 2026/27. The repository link is due 23 Nov 2026 at 23:59, and the project is presented on 24 Nov or 4 Dec.

## 2. How the spec meets the grading criteria

Every criterion on the [team project page](https://2477-introduction-programming.gitlab.io/wiki/team-project/) is answered by named sections of this spec. The middle column paraphrases the top band (100%).

| Criterion (weight) | What the top band asks for | Where this spec delivers it |
| --- | --- | --- |
| It works (20%) | Every workflow runs on the deployed app with no errors, bad input included | Result pattern (8), validation in every rule (5), forecast fallback (10), seed data and manual checklist (13, 14) |
| Interface and experience (20%) | Screens suit the task, flows have no wasted steps, outcomes and errors are visible | Screens, states and the message catalogue (11) |
| Scope and ambition (20%) | Large features far past a solo project, built consistently | Three roles, shared data with a conflict rule, live data driving rules, an approval workflow over a ledger, waitlist automation, notifications, reports (4), one architecture throughout (8) |
| Verification (10%) | Tests for allowed actions, refused actions and edge cases, all green on main | Acceptance scenarios (6), test plan and CI (13) |
| Security (10%) | Permissions and input checks enforced; few dependencies, version-pinned, no known vulnerabilities | Permission matrix (3), security (12), dependencies (7) |
| Repository walkthrough (20%) | Any member explains the build, the reasons, the limits and possible changes | Architecture and conventions (8), limits and changes (18), walkthrough drill (17) |

The solo projects supported one user and made accounts, external APIs and AI optional. LineUp puts accounts, roles and external data at its core, which is the bar "far past a solo project" is measured against.

## 3. Roles and permissions

LineUp has three roles, and every action re-reads the actor's role from the database before it runs. Hiding a button is never the check; the service function is (section 8).

| Role | Who | How someone gets it |
| --- | --- | --- |
| Student | Club members who take lessons | Default for every new account |
| Instructor | Coaches who run lessons | An admin changes their role |
| Admin | The club board | The seed script creates the first one; admins can promote others |

Visitors who are not logged in see only the login and sign-up screen.

### Permission matrix

Each cell below is one case of a parametrised test in `tests/test_permissions.py`. "Own" means the record belongs to the acting user.

| Action | Student | Instructor | Admin |
| --- | --- | --- | --- |
| View upcoming sessions and conditions | Yes | Yes | Yes |
| Book, cancel, join or leave a waitlist | Own only | No | No |
| Request or withdraw a credit pack | Own only | No | No |
| View credit balance and statement | Own only | No | Any member |
| Read and mark notifications | Own only | Own only | Own only |
| Create, edit or delete a session | No | Own only | No |
| View roster, mark attendance, export roster | No | Own sessions | Any session |
| Call off a session | No | Own sessions | Any session |
| Approve or reject credit requests | No | No | Yes |
| Change a member's role or level | No | No | Yes, never leaving zero admins |
| Edit thresholds and forecast mode | No | No | Yes |
| View reports; export bookings, ledger and requests | No | No | Yes |

A denied action returns the code `forbidden`, writes nothing, and the page shows "You don't have permission to do that."

## 4. Capabilities

Fourteen capabilities make up the product: thirteen are must-haves (three with should-have parts) and LU14 is a should-have. Each one points to the rules that define it.

| ID | Capability | Who | What it does | Rules | Priority |
| --- | --- | --- | --- | --- | --- |
| LU01 | Sign up and log in | Visitor | Create an account with a @novasbe.pt email; log in and out | R1 | Must |
| LU02 | Members and roles | Admin | List members with role, level and balance; change role or level | R1 | Must |
| LU03 | Browse sessions | Everyone logged in | Next 14 days: time, level, instructor, places left, conditions label | R2, R6 | Must |
| LU04 | Book a session | Student | Book in one confirmation; uses 1 credit | R3 | Must |
| LU05 | Waitlist | Student | Join a full session; promotion happens automatically when a place frees | R4 | Must |
| LU06 | Cancel a booking | Student | Cancel before the start; refund at 24 h or more before | R5 | Must |
| LU07 | Manage sessions | Instructor | Create, edit and delete own sessions | R2 | Must (sunset rule R2.7: Should) |
| LU08 | Conditions | Everyone | Go, Marginal, No-go or Unknown per session, with waves, wind and forecast time | R6, R7 | Must |
| LU09 | Call off | Instructor, admin | Cancel a session for everyone, refund all, clear the waitlist, notify | R8 | Must |
| LU10 | Attendance | Instructor, admin | Mark attended or no-show once the session starts | R9 | Must |
| LU11 | Credits | Student, admin | Request a pack with a payment reference; admin approves or rejects; statement | R10 | Must (statement CSV: Should) |
| LU12 | Notifications | Everyone | Inbox with an unread count that refreshes every 10 s | R11 | Must |
| LU13 | Reports and exports | Admin; instructors for rosters; students for statements | KPIs, charts and CSV files for a chosen period | R12 | Must (one export); rest Should |
| LU14 | Settings | Admin | Edit forecast thresholds; switch the forecast to saved-only mode | R6.6, R7.6 | Should |

The level rule for Intermediate sessions (R3.6) is a should-have; until it is built, every student may book Intermediate sessions. Stretch features (AI briefing, PDF report, Postgres in CI) are in section 19 and start only after the must-haves pass.

## 5. Business rules

The product is defined by 78 numbered rules, and each "tested boundary" becomes test cases in section 13. Times are Europe/Lisbon on screen and UTC in the database. "Now" is the server clock, passed into every service so tests can fix it.

Refused actions return one of these codes: `forbidden`, `invalid`, `not_found`, `closed`, `not_yet`, `no_credits`, `clash`, `level`, `duplicate`, `full`, `not_full`, `already_done`.

### R1 Accounts

| ID | Rule | Tested boundary |
| --- | --- | --- |
| R1.1 | Email has one @, a non-empty part before it, and ends in `@novasbe.pt` after trimming spaces; case is ignored | Ana@NovaSBE.pt with spaces around accepted; ana@gmail.com, @novasbe.pt and ana@sub.novasbe.pt rejected |
| R1.2 | Full name: 2–60 characters of letters (accents allowed), spaces, hyphens, apostrophes and full stops | 2 accepted, 1 rejected; 60 accepted, 61 rejected; João D'Ávila accepted |
| R1.3 | Password: at least 8 characters; the confirmation must match | 7 rejected, 8 accepted; mismatch rejected |
| R1.4 | A new account becomes a Student at level Beginner on its first login | Profile created with those values |
| R1.5 | Only admins change roles and levels | Student or instructor attempt → `forbidden` |
| R1.6 | There is always at least one admin | Demoting the only admin → `invalid`, role unchanged |
| R1.7 | Local demo mode (pick a demo user, no password) exists only when no Supabase settings are configured and the database is a local SQLite file | Postgres URL or Supabase URL present → mode off |

### R2 Sessions

| ID | Rule | Tested boundary |
| --- | --- | --- |
| R2.1 | Start time is on a 15-minute step and at or after 08:00 | 07:45 and 08:10 rejected; 08:00 accepted |
| R2.2 | Start is at least 3 hours after now, on a date at most 14 days after today | now + 2:59 rejected, now + 3:00 accepted; today + 14 accepted, today + 15 rejected |
| R2.3 | Duration is 60, 90 or 120 minutes | 45 and 150 rejected |
| R2.4 | Capacity is a whole number from 1 to 8 | 0 and 9 rejected; 1 and 8 accepted |
| R2.5 | Level is Beginner or Intermediate | Any other value rejected |
| R2.6 | An instructor's scheduled sessions never overlap; back-to-back is fine; called-off sessions don't count | With 10:00–11:30 booked in: 11:00 start → `clash`, 11:30 accepted |
| R2.7 | A session ends at or before sunset on its date (Should). Without sunset data it must end by 17:00, and the form says which limit applied | End = sunset accepted, sunset + 1 min rejected; no data → 17:00 limit |
| R2.8 | Edits and deletes happen only before the start of a scheduled session | Edit after start → `closed` |
| R2.9 | With no confirmed bookings, any field can change under R2.1–R2.7. With bookings, only capacity changes, and only upwards to 8 | Time change with 1 booking → `invalid`; capacity 4 → 6 accepted, 4 → 3 rejected |
| R2.10 | Raising capacity runs waitlist promotion (R4.3) | 2 waiting, 2 places added → both booked |
| R2.11 | Delete only if nobody ever booked or joined the waitlist; otherwise call off | Delete with 1 booking → `invalid` |

### R3 Booking

| ID | Rule | Tested boundary |
| --- | --- | --- |
| R3.1 | Only students book | Instructor or admin → `forbidden` |
| R3.2 | The session must be scheduled, not called off | Called-off session → `closed` |
| R3.3 | Booking is open while now ≤ start − 2 h | At start − 2:00 accepted; at start − 1:59 → `closed` |
| R3.4 | The student needs at least 1 credit; a booking uses exactly 1 | Balance 1 → accepted, then 0; balance 0 → `no_credits` |
| R3.5 | No overlap with the student's other confirmed bookings; back-to-back is fine | With 10:00–11:30 booked: 11:00 → `clash`, 11:30 accepted |
| R3.6 | Intermediate sessions need level Intermediate or 3 attended Beginner sessions (Should) | 2 attended → `level`; 3 accepted; level set by admin accepted |
| R3.7 | One confirmed booking per student per session | Second attempt → `duplicate` |
| R3.8 | A place is taken by one atomic update, so the first booking saved wins | Capacity 2 with 1 booked: first accepted, second → `full` with a waitlist offer; count stays 2 |
| R3.9 | A waiting student who books an open place leaves the waitlist | Entry becomes `promoted` |
| R3.10 | A No-go or Unknown label never blocks booking; the confirmation shows the label and warns the instructor may call it off | No-go session bookable, with the warning |

### R4 Waitlist

| ID | Rule | Tested boundary |
| --- | --- | --- |
| R4.1 | Join only when the session is full, booking is open (R3.3), there is no clash (R3.5), the level allows (R3.6), and the student is neither booked nor waiting. No credit needed to join | Places left → `not_full`; second join → `duplicate` |
| R4.2 | Order is join time, earliest first | A joins before B → A offered first |
| R4.3 | When a place frees while booking is open, offer it in order. A student with no credit or a clash is removed and told why; the next is tried | Carla (0 credits) then Bruno (1): Carla removed, Bruno booked and charged |
| R4.4 | No promotion once booking has closed; the free place stays empty | Cancellation at start − 1:59 → nobody promoted |
| R4.5 | A student can leave the waitlist any time before the start | Entry becomes `left` |
| R4.6 | Each waiting student sees their position | Third in line sees "#3" |

### R5 Cancellation

| ID | Rule | Tested boundary |
| --- | --- | --- |
| R5.1 | Students cancel only their own confirmed booking, before the start | Another's booking → `forbidden`; at start → `closed` |
| R5.2 | Refund 1 credit if now ≤ start − 24 h; otherwise no refund. The dialog says which before the student confirms | At start − 24:00 refunded; at start − 23:59 not |
| R5.3 | Cancelling frees the place and runs promotion (R4.3, R4.4) | Full session with 1 waiting → that student booked |
| R5.4 | Cancelling twice changes nothing | Second attempt → `already_done` |

### R6 Conditions

| ID | Rule | Tested boundary |
| --- | --- | --- |
| R6.1 | A session uses every forecast hour it touches: from the hour holding its start to the hour holding its last minute | 10:00–11:30 uses 10:00 and 11:00; 10:00–11:00 uses 10:00 only |
| R6.2 | Take the highest wave height and the highest wind speed across those hours | Waves 1.2 and 1.6 → 1.6 |
| R6.3 | Go if waves ≤ Go-wave and wind ≤ Go-wind; else Marginal if waves ≤ Marginal-wave and wind ≤ Marginal-wind; else No-go | Beginner: 1.50 m and 25 km/h Go; 1.51 m Marginal; 25.1 km/h Marginal; 2.01 m No-go; 35.1 km/h No-go |
| R6.4 | Unknown if a needed hour is missing or empty, the session is beyond the forecast range, no forecast exists, or the forecast used was fetched more than 12 h ago | Fetched 11:59 ago → used; 12:01 ago → Unknown |
| R6.5 | Labels are advice: they never cancel, block or change a booking (R3.10) | No-go session still bookable |
| R6.6 | Admin-edited thresholds: each above 0; Go ≤ Marginal for waves and for wind; waves ≤ 10 m; wind ≤ 150 km/h | Go-wave 2.1 with Marginal-wave 2.0 → `invalid` |

Default thresholds are example club policy, not safety advice; admins change them in Settings.

| Level | Go: waves up to | Go: wind up to | Marginal: waves up to | Marginal: wind up to |
| --- | --- | --- | --- | --- |
| Beginner | 1.5 m | 25 km/h | 2.0 m | 35 km/h |
| Intermediate | 2.5 m | 30 km/h | 3.0 m | 40 km/h |

### R7 Forecast data

| ID | Rule | Tested boundary |
| --- | --- | --- |
| R7.1 | Call Open-Meteo only when the newest saved forecast is 60 minutes old or more | 59 min → no call; 60 min → call |
| R7.2 | Each request times out after 5 seconds | Fake timeout → fallback |
| R7.3 | Save every successful fetch (waves, wind, sunset) with its fetch time | Rows present after a fetch |
| R7.4 | If either request fails, use the saved forecast for everything and show its time | Label "Forecast from 09:12 (live update failed)" |
| R7.5 | After a failed attempt, wait 10 minutes before trying again | Failure at 09:00 → no call at 09:09, call at 09:10 |
| R7.6 | In Saved-only mode (admin setting) the app makes no live calls | Fake fetcher called 0 times |
| R7.7 | Any screen that shows conditions credits Open-Meteo | Footer present |

### R8 Call-off

| ID | Rule | Tested boundary |
| --- | --- | --- |
| R8.1 | Only the session's instructor or an admin, while now < session end | Another instructor → `forbidden`; after end → `closed` |
| R8.2 | A category is required (Conditions, Instructor unavailable, Other) plus a reason of 3–200 characters | 2 or 201 characters → `invalid` |
| R8.3 | Every confirmed booking becomes `called_off` and gets 1 credit back, whatever the time | Booking 1 h before start still refunded |
| R8.4 | The waitlist is cleared; every booked and waiting student is notified | 3 booked + 2 waiting → 5 notifications |
| R8.5 | Calling off twice changes nothing | Second attempt → `already_done`, no new refunds |

### R9 Attendance

| ID | Rule | Tested boundary |
| --- | --- | --- |
| R9.1 | Only the session's instructor or an admin, from the start onwards, never for called-off sessions | Before start → `not_yet`; called off → `closed` |
| R9.2 | Each confirmed booking is marked Attended or No-show, and can be corrected later | No-show → Attended accepted |
| R9.3 | No-shows get no refund | Ledger unchanged |

### R10 Credits

| ID | Rule | Tested boundary |
| --- | --- | --- |
| R10.1 | Packs: 1 credit for €15, 5 for €65, 10 for €120 | Seeded; money stored in cents |
| R10.2 | At most one pending request per student | Second → `duplicate` |
| R10.3 | Payment reference: 3–40 characters of letters, digits, spaces and `- / #` | MBWAY 912 accepted; `<b>x</b>` rejected |
| R10.4 | Students can withdraw their own pending request | Status becomes `withdrawn` |
| R10.5 | Only admins approve or reject; a rejection needs a note of 3–200 characters | Student approves → `forbidden`; empty note → `invalid` |
| R10.6 | Approval adds the pack's credits once; deciding a decided request changes nothing | Approve twice → one ledger row, `already_done` |
| R10.7 | Balance = sum of the member's ledger rows; no action may make it negative | Booking at 0 → `no_credits` |
| R10.8 | Ledger rows are never edited or deleted; each has a unique reference such as `booking:57` or `refund:57` | A second `refund:57` is blocked by the unique constraint |

### R11 Notifications

| ID | Rule | Tested boundary |
| --- | --- | --- |
| R11.1 | Notify on: booking confirmed, promoted, removed from waitlist, session called off, credit request approved or rejected | One notification per event |
| R11.2 | A notification is written in the same transaction as its action | Failed action → no notification |
| R11.3 | Members read and mark only their own | Another's → `forbidden` |

### R12 Reports and exports

| ID | Rule | Tested boundary |
| --- | --- | --- |
| R12.1 | Period: start ≤ end, at most 92 days | 93 days or end before start → `invalid` |
| R12.2 | Sessions run = not called off and ended before now | Future sessions excluded |
| R12.3 | Fill rate = confirmed bookings in sessions run ÷ their total capacity | 6 of 8 places → 75%; no sessions → "—" |
| R12.4 | No-show rate = no-shows ÷ (attended + no-shows) | Nothing marked → "—" |
| R12.5 | Credits sold and revenue = requests approved in the period | One 5-pack and one 1-pack → 6 credits, €80.00 |
| R12.6 | Call-offs are counted by category | 2 Conditions, 1 Other |
| R12.7 | CSV files hold only the listed columns; a text cell starting with `=`, `+`, `-` or `@` gets a leading apostrophe | `=HYPERLINK(...)` exported as `'=HYPERLINK(...)` |
| R12.8 | Instructors export rosters of their own sessions only; students export only their own statement | Another's → `forbidden` |

## 6. Acceptance scenarios

Eighteen scenarios define "done" for the product as a whole. Each is one test in `tests/test_scenarios.py` and one line of the manual checklist run on the deployed app (section 13).

| ID | Scenario | Given | When | Then |
| --- | --- | --- | --- | --- |
| A1 | Sign-up domain (R1.1) | No account | Sign up with ana@gmail.com, then with ana@novasbe.pt | First refused with the reason and nothing created; second creates a Student at Beginner |
| A2 | Booking cutoff (R3.3) | Session at 10:00 with places | Ana books at 08:00; Bruno tries at 08:01 | Ana booked; Bruno sees "Booking closed" |
| A3 | Last credit (R3.4, R10.7) | Ana has 1 credit | She books session X, then session Y | X booked, balance 0; Y refused with `no_credits`, balance still 0 |
| A4 | Clash (R3.5) | Ana booked 10:00–11:30 | She books 11:00–12:00, then 11:30–12:30 | First refused, naming the clashing time; second booked |
| A5 | Last place (R3.8, R4.1) | Capacity 2, 1 booked | Ana books, then Bruno books | Ana booked; Bruno told it is full and joins the waitlist as #1; booked count is 2 |
| A6 | Promotion with a skip (R4.3, R5.2) | Full session; Carla waiting #1 with 0 credits, Bruno #2 with 1 | Ana cancels 30 h before the start | Ana refunded; Carla removed and told why; Bruno booked, charged and notified |
| A7 | Refund window (R5.2, R5.1) | Three students booked | One cancels at start − 24:00, one at start − 23:59, one at the start | First refunded; second not refunded and warned before confirming; third refused |
| A8 | Thresholds (R6.3) | Beginner session | The forecast peaks at 1.50 m and 25 km/h; then 1.51 m; then 2.01 m; then 1.0 m and 35.1 km/h | Go, Marginal, No-go, No-go |
| A9 | Forecast failure (R7.4, R6.4) | Forecast saved at 09:00; a second case with nothing saved | The live call times out at 10:00 | With saved data: labels from it plus "Forecast from 09:00 (live update failed)". With nothing saved: Unknown. Booking works in both |
| A10 | Beyond range (R6.4) | Session 10 days ahead | Anyone views it | Unknown, "Forecast available closer to the date" |
| A11 | Call-off (R8.3–R8.5) | 3 booked (one of them 1 h before the start), 2 waiting | The instructor calls off with category Conditions, then tries again | 3 refunds, waitlist cleared, 5 notifications; the second attempt changes nothing |
| A12 | Wrong person (R8.1, R10.5) | Tiago's session; a pending credit request | Inês calls off Tiago's session; Ana approves the request | Both `forbidden`; nothing changes |
| A13 | Credit approval (R10.2, R10.6, R10.5) | Ana has no pending request | She requests a 5-pack, then another pack; the admin approves twice; the admin rejects a request without a note | One pending; the second request refused; +5 credits once; rejection refused until a note is given |
| A14 | Session validation (R2.1–R2.7) | Tiago has 10:00–11:30 tomorrow | He tries capacity 9; a 07:45 start; a session ending after sunset; an 11:00 start; an 11:30 start | First four refused, each with its reason; the 11:30 session created |
| A15 | Attendance unlocks Intermediate (R9.1, R3.6) | Ana attended 2 Beginner sessions; a third has ended | The instructor marks the third; Ana books an Intermediate session before and after | Marking a future session refused; booking refused at 2 attended, accepted at 3 |
| A16 | Survives a restart | Ana booked, Bruno waiting, Carla's request pending | Restart the app | Booking, balance, waitlist and request unchanged |
| A17 | Report numbers (R12.2–R12.6) | The fixed report dataset | The admin opens that period | Every KPI equals the value written in the test |
| A18 | Last admin (R1.6) | One admin | They change their own role to Student | Refused; still admin |

## 7. Stack and programming language

LineUp is written in Python 3.12 with Streamlit, the course stack, so no approval from the teaching staff is needed. Every other choice below is the course's standard option or has a stated reason.

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.12 | Course language; selectable on Streamlit Community Cloud |
| Interface | Streamlit, multipage with `st.navigation`; `st.dialog` for confirmations; `st.fragment(run_every=...)` for live refresh | Forms, cards, tables and charts are its strength |
| Live database | Supabase Postgres, reached through the session pooler | Shared by all users and survives restarts; the course's standard choice |
| Test and local database | SQLite, in memory for tests and a local file for development | Tests need no secrets or network |
| Database access | SQLAlchemy 2 Core (no ORM) | One set of queries for Postgres and SQLite |
| Login | Supabase Auth, email and password | We never store passwords; same service as the data |
| External data | Open-Meteo Marine API and Forecast API | Free for non-commercial use, no key; waves, wind and sunset |
| Hosting | Streamlit Community Cloud, deploying from `main` | Free, no card; reads `uv.lock` directly |
| Packages | uv with `pyproject.toml` and `uv.lock` | Course tool; the lock file pins every version with hashes |
| Tests | pytest | Course tool |
| CI | GitHub Actions | Runs the tests and a dependency audit on every pull request |
| Coding agent | Codex reading `AGENTS.md` | Course agent; any agent that reads `AGENTS.md` works |

### Dependencies

Seven runtime packages, each with one job. Nothing is added without a row here and an entry in `docs/decisions.md`.

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

`uv.lock` is the only dependency file in the repository. Streamlit Community Cloud reads it before any other file and the [Streamlit docs](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies) warn against keeping two, so there is no `requirements.txt`. The audit tool, pip-audit, runs through `uvx` and is never installed in the project.

## 8. Architecture

The code keeps the course's split of screens, rules and storage, and adds one layer, services, where every action is checked, applied and saved in one transaction. The diagram below shows what calls what.

&#91;embedded content: LineUp architecture · 11 parts, caller to callee\]

Screens never touch the database or an outside service directly: every action goes through a service, which is also where the tests plug in.

### Folder structure

```text
lineup-surf/
  app.py                     entry point: setup, login gate, navigation by role
  app_pages/                 SCREENS, one file per page (section 11)
    login.py  sessions.py  my_bookings.py  credits.py  inbox.py
    instructor_sessions.py  roster.py
    admin_requests.py  admin_members.py  admin_reports.py  admin_settings.py
  lineup/
    config.py                policy numbers, spot coordinates, time zone, secret lookup
    models.py                Result, error codes, dataclasses, enums
    timeutil.py              UTC and Lisbon conversion, hour rounding
    permissions.py           the permission matrix of section 3
    schema.py                STORAGE: table definitions (one owner)
    db.py                    STORAGE: engine, transactions, every query
    auth.py                  LOGIN: the only file that talks to Supabase Auth
    openmeteo.py             EXTERNAL API: the only file that talks to Open-Meteo
    logic/                   RULES: pure functions, no database, network or clock
      accounts.py  sessions.py  booking.py  conditions.py  credits.py  reports.py
    services/                ACTIONS: permission, rules, save, notify
      members.py  sessions.py  booking.py  forecast.py  credits.py
      notifications.py  reports.py
    ui.py                    shared Streamlit helpers: badges, messages, run_action
  scripts/seed.py            create tables, enable RLS on Postgres, load demo data
  tests/                     TESTS, plus fixtures/ with recorded Open-Meteo responses
  specs/                     one task spec per build task (Why, What, Out of scope, Done when)
  docs/                      this spec, architecture, decisions, limits, demo script, checklist
  .streamlit/config.toml     theme
  .streamlit/secrets.toml.example
  .github/workflows/ci.yml
  AGENTS.md  README.md  pyproject.toml  uv.lock  .python-version  .gitignore
```

The screens folder is `app_pages/`, not `pages/`, because Streamlit gives a folder named `pages/` a special meaning.

### What happens when someone clicks

1. The page collects the input and calls one service function, for example `booking.book(engine, actor_id, session_id)`.
2. The service opens one transaction, reloads the actor's role from the database and checks `permissions.py`.
3. It loads the data it needs and asks the pure rule in `logic/` whether the action is allowed.
4. If not, it returns `Result(ok=False, code, message)` and writes nothing.
5. If yes, it writes every change and its notifications in that same transaction and returns `Result(ok=True, message)`.
6. The page shows the result with `ui.show_result`.

### Conventions every file follows

- **Result.** Services never raise for expected problems; they return `Result(ok, code, message, data)`. Tests check `code`, never the wording.
- **Unexpected errors.** `ui.run_action` catches any exception, logs it with a six-character reference, and shows "Something went wrong (ref 7F2K9Q). Please try again."
- **Actor.** Services receive `actor_id`, never a role. The role is read inside the transaction, so a demoted user loses rights at once.
- **Time.** The database stores naive UTC datetimes; `timeutil` converts to Europe/Lisbon for display. Every service takes `now`, defaulting to the current UTC time, so tests can fix the clock.
- **Money and credits.** Money is integer cents; credits are integers.
- **One transaction per action.** `with engine.begin() as conn:` wraps every write.
- **Atomic place.** `UPDATE surf_sessions SET booked_count = booked_count + 1 WHERE id = :id AND status = 'scheduled' AND booked_count < capacity`. One changed row means the place was taken.
- **Credits under concurrency.** Before charging, services lock the member row with `SELECT ... FOR UPDATE` on Postgres; SQLite serialises writes on its own.
- **Imports.** `logic/` imports no Streamlit, SQLAlchemy or httpx. `services/` imports no Streamlit. Only `app.py`, `app_pages/` and `ui.py` import Streamlit.
- **Secrets.** Read only in `config.py`: environment variables first, then `st.secrets`.
- **Shared objects.** The database engine is created once per server process with `st.cache_resource`. The Supabase client is created fresh for each login and never cached, because it holds one user's session.

## 9. Data model

Twelve tables hold all data, defined only in `lineup/schema.py` and changed only by its owner. Datetimes are naive UTC, money is in cents, and ids are integers unless noted.

| Table | Columns | Constraints and notes |
| --- | --- | --- |
| members | id, auth\_user\_id, email, full\_name, role, level, created\_at | email unique, stored lower-case; auth\_user\_id (text) unique, empty until first login; role student, instructor or admin; level beginner or intermediate |
| surf\_sessions | id, instructor\_id, starts\_at, duration\_min, level, capacity, booked\_count, status, call\_off\_category, call\_off\_reason, called\_off\_at, created\_at | status scheduled or called\_off; 0 ≤ booked\_count ≤ capacity; capacity 1–8; duration 60, 90 or 120 |
| bookings | id, session\_id, member\_id, status, attendance, refunded, created\_at, cancelled\_at | status confirmed, cancelled or called\_off; attendance empty, attended or no\_show; partial unique index: one confirmed booking per session and member |
| waitlist\_entries | id, session\_id, member\_id, status, reason, created\_at, updated\_at | status waiting, promoted, left, removed or cleared; partial unique index: one waiting entry per session and member |
| credit\_packs | id, name, credits, price\_cents, active | Seeded: 1 credit for 1500, 5 for 6500, 10 for 12000 |
| credit\_requests | id, member\_id, pack\_id, payment\_ref, status, decided\_by, decided\_at, decision\_note, created\_at | status pending, approved, rejected or withdrawn; partial unique index: one pending request per member |
| credit\_ledger | id, member\_id, delta, kind, ref, note, created\_at | delta never 0; kind purchase, booking or refund; ref unique, such as purchase:12, booking:57, refund:57; never updated or deleted |
| notifications | id, member\_id, kind, message, created\_at, read\_at | message up to 300 characters |
| forecast\_hours | hour\_utc (key), wave\_height\_m, wind\_speed\_kmh, fetched\_at | Values may be empty |
| forecast\_days | day (key), sunset\_utc, fetched\_at | One row per date |
| condition\_thresholds | level (key), go\_wave\_m, go\_wind\_kmh, marginal\_wave\_m, marginal\_wind\_kmh, updated\_by, updated\_at | One row per level; rule R6.6 |
| app\_settings | key (key), value, updated\_at | forecast\_mode (live or saved\_only), last\_forecast\_attempt\_at, last\_forecast\_error |

Partial unique indexes use SQLAlchemy's `Index(..., unique=True, sqlite_where=..., postgresql_where=...)`, so the same definition works on both databases.

### How records change status

- **Session:** scheduled → called\_off (R8). "Running" and "finished" come from the clock and are never stored.
- **Booking:** confirmed → cancelled (student, R5) or called\_off (R8). It never returns to confirmed; booking again creates a new row.
- **Waitlist entry:** waiting → promoted (R4.3, R3.9), left (R4.5), removed (no credit or a clash, R4.3) or cleared (call-off, R8.4).
- **Credit request:** pending → approved, rejected or withdrawn (R10).

### Invariants

`db.check_invariants(conn)` lists every broken rule below. An automatic pytest fixture runs it after each service test, so a bug that corrupts data fails a test even when no assertion looks for it.

1. Each session's `booked_count` equals its number of confirmed bookings.
2. No member's ledger sums to less than zero.
3. A called-off session has no confirmed bookings and no waiting entries.
4. Each booking has exactly one `booking:<id>` ledger row and at most one `refund:<id>` row; `refunded` is true exactly when that refund row exists.
5. No student has two overlapping confirmed bookings.

## 10. Open-Meteo integration

Two keyless Open-Meteo requests, made at most once an hour, feed every conditions label. If they fail, the app uses the last saved forecast and says so; it never crashes and never blocks booking.

### Requests

| Feed | Request | Gives |
| --- | --- | --- |
| Waves | `GET https://marine-api.open-meteo.com/v1/marine?latitude=38.68&longitude=-9.34&hourly=wave_height&forecast_days=7&timezone=GMT` | Hourly significant wave height, metres |
| Wind and sunset | `GET https://api.open-meteo.com/v1/forecast?latitude=38.68&longitude=-9.34&hourly=wind_speed_10m&daily=sunset&wind_speed_unit=kmh&forecast_days=7&timezone=GMT` | Hourly wind speed at 10 m, km/h; sunset per day |

The coordinates are approximate for Carcavelos beach and live in `config.py`. The marine API picks the nearest sea grid cell by default, and its answer may describe a cell a few kilometres away. On Day 0, call both URLs once and confirm the arrays hold numbers, not nulls.

`timezone=GMT` makes every timestamp UTC, such as `2026-11-20T10:00`, which matches the database. The daily `sunset` value needs a `timezone` parameter anyway.

### Parsing and checks (`lineup/openmeteo.py`)

- Accept only HTTP 200 JSON whose `hourly.time` and value arrays have equal length. An HTTP 400 body (`{"error": true, "reason": ...}`), a timeout, or malformed JSON counts as a failure.
- Keep a value only if it is a finite number from 0 to 30 m (waves) or 0 to 300 km/h (wind); store anything else as empty.
- Parse each sunset string; an unparseable one is stored as empty.
- Return plain data classes (`HourValues`, `DaySunset`). This file holds no database code.

### Getting a forecast (`lineup/services/forecast.py`)

1. Forecast mode is Saved only: use saved data (R7.6).
2. The newest saved fetch is under 60 minutes old: use saved data (R7.1).
3. The last failed attempt was under 10 minutes ago: use saved data (R7.5).
4. Otherwise call both feeds with a 5-second timeout each (R7.2). Both succeed: save them in one transaction and use them (R7.3). Either fails: record the attempt and its error, and use saved data (R7.4).

The service receives the fetch function as a parameter. Tests pass a fake that returns recorded JSON, raises a timeout, or counts its calls.

### Labels shown with the data

| Situation | Text under the conditions |
| --- | --- |
| Fresh live data | Forecast updated 09:12 |
| Saved data after a failed update | Forecast from 09:12 (live update failed) |
| Saved-only mode | Forecast from 09:12 (saved data, live updates paused) |
| No usable data | Forecast unavailable, and every label is Unknown |
| Session beyond the data | Forecast available closer to the date |

### Test fixtures

On Day 0, save one real response of each feed as `tests/fixtures/marine_ok.json` and `tests/fixtures/weather_ok.json`. Add hand-edited copies with nulls, with a missing array, and an HTTP 400 body. Tests never touch the network.

### Terms and attribution

The Marine API is free for non-commercial use with no key, which covers a student project. Open-Meteo asks every user to credit Open-Meteo and the providers of the models used. The footer therefore reads "Weather data: Open-Meteo.com, wave models by Météo-France, ECMWF, NOAA and DWD", linked to the [Open-Meteo licence page](https://open-meteo.com/en/licence). Source: [Open-Meteo Marine API documentation](https://open-meteo.com/en/docs/marine-weather-api).

## 11. Screens and UX

Eleven screens, each showing only what its role needs. Every action ends in a visible success or error message that names the reason and, where there is one, the fix.

### On every screen

- **Navigation by role** with `st.navigation`. Students see Sessions, My bookings, Credits, Inbox. Instructors see Sessions, My sessions, Roster, Inbox. Admins see Sessions, Roster, Credit requests, Members, Reports, Settings, Inbox.
- **Sidebar:** name and role, credit balance for students, the unread count (refreshed every 10 s), Log out.
- **Conditions badge:** a coloured pill that always carries the word (Go, Marginal, No-go, Unknown), never colour alone, with the numbers beside it: "Waves 1.2 m · Wind 18 km/h".
- **Times** always in Lisbon time with the weekday: "Fri 20 Nov, 10:00–11:30".
- **Confirmations** use `st.dialog` and state the consequence above the button.
- **Footer** with the Open-Meteo credit wherever conditions appear.
- **Phone first:** one column of cards on a narrow screen; checked on a real phone before the demo.

### Screens

| Screen | Who | Shows | Actions | Empty and error states |
| --- | --- | --- | --- | --- |
| Login | Visitor | Log in and Sign up tabs | Log in; sign up with name, email and password twice | Errors under each field; a wrong password shows "Email or password is wrong." |
| Sessions | All | Cards for the next 14 days, filterable by level and "only ones I can book": time, level, instructor, places left or waitlist length, badge, the student's own status | Book (dialog: credit used, free-cancel deadline, current label); Join waitlist. A disabled button says why, such as "Booking closed" | "No sessions in the next 14 days yet." |
| My bookings | Student | Upcoming bookings, waitlist positions, past sessions with attendance and refund status | Cancel (dialog says refund or no refund); Leave waitlist | "You have no upcoming sessions." with a link to Sessions |
| Credits | Student | Balance, the three packs with price per credit, any pending request, statement | Request a pack with a payment reference; Withdraw; Download statement CSV | Payment instructions next to the form |
| Inbox | All | Notifications, newest first, unread in bold | Mark all as read | "No notifications yet." |
| My sessions | Instructor | "Needs your decision": own sessions in the next 72 h labelled No-go or Unknown. Then the create form and upcoming own sessions | Create; Edit (dialog); Delete if nobody booked; Call off | The sunset limit for the chosen date appears under the time field |
| Roster | Instructor, admin | One session: booked students with their attended Beginner count, the waitlist, attendance controls once it starts | Save attendance; Call off; Download roster CSV | "Attendance opens at 10:00." before the start |
| Credit requests | Admin | Pending requests, oldest first; decided history | Approve; Reject with a note | "No pending requests." |
| Members | Admin | Members with role, level and balance; search by name or email | Change role; change level | The last-admin message from R1.6 |
| Reports | Admin | Period picker, a row of KPIs, bookings per week, fill rate by level, call-offs by category | Download bookings, ledger and requests as CSV | "—" for a rate with no data |
| Settings | Admin | Threshold form per level; forecast mode with the last fetch time and last error | Save thresholds; switch mode | Errors from R6.6 under each field |

### Message catalogue

Each error code has one message template in `lineup/models.py`, so every screen words the same problem the same way.

| Code | Message |
| --- | --- |
| forbidden | You don't have permission to do that. |
| invalid | {field}: {problem}. Allowed: {allowed}. |
| not\_found | That item no longer exists. Refresh the page. |
| closed | Too late: {what} closed at {time}. |
| not\_yet | This opens when the session starts at {time}. |
| no\_credits | You have no credits left. Request a pack on the Credits page. |
| clash | You already have a session at that time ({time}). |
| level | Intermediate sessions need 3 attended Beginner sessions or an Intermediate level. You have {n}. |
| duplicate | You're already booked or waiting here. |
| full | This session just filled up. Join the waitlist to get the next free place. |
| not\_full | There are places left, so book directly. |
| already\_done | Nothing changed: this was already done. |

Success messages say what happened and what it means next, for example: "Booked: Fri 20 Nov, 10:00. 2 credits left. Free cancellation until Thu 19 Nov, 10:00."

### Usability check

On Friday 20 Nov, give two classmates who have never seen the app three tasks with no help: book a session, cancel one late, request credits. Note where they hesitate and fix the top three problems before the weekend.

## 12. Security

Security rests on four checks: who you are (Supabase Auth), what you may do (permissions in the services), what you may send (validation), and what the repository exposes (secrets and dependencies).

### Access control

- Every service function first loads the actor from the database and calls `permissions.require(actor, action, record)`. Nothing relies on a hidden button.
- The role is read on every action, so a demoted user loses rights on their next click.
- `tests/test_permissions.py` covers every cell of the matrix in section 3, including "own only" checked against a second user's record.

### Input validation

- Every field has a rule with a range in section 5. `logic/` checks it and returns `invalid` with the allowed range. Widget limits are a convenience, not the protection.
- Free text is trimmed and length-limited: name 60, reason 200, payment reference 40, notification 300 characters.
- SQL uses SQLAlchemy Core with bound parameters only. No SQL is ever built from strings.

### Login

- Supabase Auth checks passwords; LineUp never sees or stores a password hash.
- A new Supabase client is created for each login attempt and never cached or shared between users.
- After login the app keeps only the member id in `st.session_state`. Logging out or refreshing the page ends the session.
- "Confirm email" is off in Supabase so sign-up works during the demo without email. The @novasbe.pt rule therefore checks the address format, not ownership; this is listed in the limits.

### Database exposure

- Supabase automatically publishes tables in its `public` schema through a REST API. `scripts/seed.py` enables Row Level Security on all 12 tables with no policies, which closes that API.
- The app connects as the tables' owner through the session pooler, which Row Level Security does not block.
- After setup, Supabase's Security Advisor must show no "RLS disabled" warnings.

### Secrets

| Secret | Where it lives | Never in |
| --- | --- | --- |
| `DATABASE_URL` (contains the database password) | `.streamlit/secrets.toml` locally; Streamlit Cloud app settings | Code, tests, docs, chat, screenshots |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Same as above | Same as above |
| Demo account passwords | Team password manager; sent privately to the teaching staff | README, issues, chat |

- `.gitignore` lists `.streamlit/secrets.toml` and `.env` before either file exists. `.streamlit/secrets.toml.example` holds placeholders only.
- Before the repository goes public, search its whole history for `postgres`, `eyJ` and `sb_` (connection strings and Supabase keys). Anything found is rotated in the Supabase dashboard; deleting the file is not enough.
- Turn on GitHub secret scanning and push protection in the repository settings.
- LineUp never uses Supabase's secret (service-role) key.

### Output safety

- User-written text is shown with `st.text`, or escaped by a small `ui.plain()` helper before it enters Markdown. `unsafe_allow_html` is never used with user content.
- CSV exports put an apostrophe before any cell starting with `=`, `+`, `-` or `@` (R12.7), so a name cannot run as a spreadsheet formula.
- Logs never contain passwords, keys or connection strings, and users never see stack traces.

### Dependencies

- Seven runtime packages, each with a stated job (section 7).
- `uv.lock` pins exact versions with hashes. CI runs `uv sync --locked`, so a dependency change without a lock update fails.
- CI runs pip-audit on the locked versions; a known vulnerability fails the build.
- Dependabot alerts are on for the repository.
- `AGENTS.md` forbids adding packages without asking, and reviewers reject a pull request that changes `pyproject.toml` without an entry in `docs/decisions.md`.

### Coding agents

- A member who connects Supabase to their agent through MCP uses read-only mode, limited to this project, as the course's MCP guide advises.
- Agents never create, edit or print secrets files (`AGENTS.md`).

## 13. Testing and verification

About 200 test cases, many of them parametrised, run in under a minute with no secrets and no network. Every rule in section 5 gets an allowed case, a refused case and its boundary, and every test name states its rule, such as `test_booking_closes_two_hours_before_start`.

### Shared fixtures (`tests/conftest.py`)

- `engine`: an in-memory SQLite database (SQLAlchemy `StaticPool`) with all tables and foreign keys on.
- `now`: fixed at Fri 20 Nov 2026, 09:00 UTC. Lisbon equals UTC in November, so tests read naturally.
- Factories: `make_member(role, level)`, `make_session(...)`, `give_credits(member, n)`, `book(member, session)`.
- `fake_openmeteo`: returns a recorded response from `tests/fixtures/`, raises a timeout, or returns an HTTP 400 body, and counts its calls.
- An automatic fixture runs `db.check_invariants` after every test that used the database (section 9).

### Test files

| File | Covers | Example cases | Cases |
| --- | --- | --- | --- |
| test\_accounts.py | R1.1–R1.4, R1.7 | Email variants, name lengths and accents, password 7 and 8, first-login profile, seeded email linked at login, demo mode on and off | 16 |
| test\_permissions.py | Section 3 | 12 actions × 3 roles, parametrised, with "own only" checked against another user's record | 36 |
| test\_members.py | R1.5–R1.6 | Role change, level change, last admin, demoted user loses rights | 6 |
| test\_sessions.py | R2 | Every boundary in R2.1–R2.11 | 18 |
| test\_booking.py | R3 | Cutoff at 2:00 and 1:59, credits 1 and 0, clash and back-to-back, level 2 and 3, duplicate, called off, last place | 14 |
| test\_waitlist.py | R4 | Join rules, order, skip with reason, no promotion after cutoff, leave, position | 9 |
| test\_cancellation.py | R5 | 24:00 and 23:59, after start, another's booking, twice, promotion triggered | 7 |
| test\_conditions.py | R6 | Hour window, maximum, each threshold edge per level, every Unknown case, 12-hour staleness, threshold validation | 16 |
| test\_forecast.py | R7 | Recorded responses parsed, nulls, HTTP 400, timeout, 59 and 60 minutes, 10-minute back-off, saved-only mode, one feed failing | 12 |
| test\_call\_off.py | R8 | Refunds once, waitlist cleared, 5 notifications, twice, wrong instructor, admin allowed, reason length, after end | 9 |
| test\_attendance.py | R9 | Before start, after start, called off, correction, no refund | 5 |
| test\_credits.py | R10 | Packs seeded, one pending, reference rules, withdraw, approve once, rejection note, unique ledger reference | 12 |
| test\_notifications.py | R11 | One per event, none after a failed action, own only, mark read | 4 |
| test\_reports.py | R12 | Period rules, each KPI on fixed data, the "—" cases, CSV columns, formula escaping, export permissions | 12 |
| test\_scenarios.py | A1–A18 | One test per acceptance scenario | 18 |
| test\_persistence.py | A16 | A file database closed and reopened | 2 |
| test\_seed.py | Seed script | Runs twice cleanly; invariants hold | 2 |

### What the tests do not cover

The README repeats this table, because "what do the tests not cover?" is a walkthrough question.

| Not covered by automated tests | How it is checked instead |
| --- | --- |
| Screen layout and wording | `docs/manual-test-checklist.md`, run on the deployed app |
| Real Supabase Auth | Logging in with each demo role on the deployed app |
| The live Open-Meteo service | One manual call on Day 0; the fixtures are recorded from it |
| Truly simultaneous clicks | The atomic update is tested in sequence; Postgres row locking is reasoned about, not tested |
| Postgres-only behaviour | Stretch: run the whole suite on Postgres in CI (section 19) |

### Continuous integration

GitHub Actions runs on every pull request and every push to `main`: install from the lock, run the tests, audit the dependencies (file in section 15). Merging into `main` requires a green run. Once the repository is public, protect `main` so the check is enforced.

### Manual checklist

`docs/manual-test-checklist.md` walks A1–A18 by clicking, plus these invalid inputs: a gmail sign-up, a 7-character password, capacity 9, a 07:45 start, payment reference `<b>`, a 93-day report period, booking with 0 credits, a late cancellation, opening attendance before the start. Run it on the deployed URL on Saturday 21 Nov and again after the last fix.

## 14. Setup and deployment

The app is deployed on Day 0 as a bare login page, so every later merge is checked on the real host. Order matters below: the Auth users must exist before the seed links profiles to them.

### Settings the app reads

| Name | Example value | Used by |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://postgres.<ref>:<password>@<pooler-host>:5432/postgres` | `db.py`; leave it out locally to use `data/lineup.db` |
| `SUPABASE_URL` | `https://<ref>.supabase.co` | `auth.py` |
| `SUPABASE_ANON_KEY` | The project's publishable (anon) key | `auth.py` |

### Day 0 steps

1. **Supabase project.** Create a free project in an EU region. Store the database password in the team password manager.
2. **Auth settings.** In the Email provider settings, keep email sign-in on, turn "Confirm email" off, and set the minimum password length to 8.
3. **Connection string.** Click Connect, copy the session pooler URI, and change its scheme to `postgresql+psycopg://`. The direct connection may be unreachable from Streamlit Cloud; the pooler is not.
4. **Keys.** Copy the project URL and the publishable (anon) key. Never put the secret (service-role) key in the app.
5. **Local run.** `uv sync`, then `uv run python scripts/seed.py` (creates `data/lineup.db`), then `uv run streamlit run app.py`. Without Supabase settings, local demo mode lets you pick a demo user (R1.7).
6. **Demo users.** In Supabase, Authentication → Users → Add user, create each demo account below as an auto-confirmed user.
7. **Live tables and data.** With `DATABASE_URL` in your local secrets, run `uv run python scripts/seed.py --target live`. It asks you to type RESET, creates the tables, enables Row Level Security on each, and loads the demo data.
8. **Security Advisor.** In Supabase, confirm there are no "RLS disabled" warnings.
9. **Deploy.** On Streamlit Community Cloud, create an app from the team repository, branch `main`, file `app.py`, with a custom subdomain such as `lineup-surf`. Under Advanced settings, choose Python 3.12 and paste the three settings in TOML form.
10. **Check.** Open the URL, log in as each role, and confirm the labels show live data and the footer credit appears.

### Demo accounts

These addresses never receive mail, because they are created already confirmed. Passwords live in the team password manager, never in the repository.

| Role | Name | Email |
| --- | --- | --- |
| Admin | Marta Silva | lineup.admin@novasbe.pt |
| Instructor | Tiago Costa | lineup.tiago@novasbe.pt |
| Instructor | Inês Rocha | lineup.ines@novasbe.pt |
| Student | Ana Martins | lineup.ana@novasbe.pt |
| Student | Bruno Lopes | lineup.bruno@novasbe.pt |
| Student | Carla Dias | lineup.carla@novasbe.pt |
| Student | Diogo Alves | lineup.diogo@novasbe.pt |

### What the seed creates

Dates are relative to the day the seed runs, so the demo always has upcoming sessions. Purchases and bookings go through the ledger, so the invariants hold.

| Item | Seeded data |
| --- | --- |
| Catalogue | The three packs (R10.1) and the default thresholds (R6) |
| Past sessions | Two finished Beginner sessions with attendance marked: two weeks ago Ana and Bruno attended; one week ago Bruno attended and Diogo was a no-show |
| Tomorrow, 10:00 | Beginner with Tiago, capacity 4, Ana and Bruno booked; a second Beginner session with Inês at 10:30, empty, for the clash demo |
| In 2 days, 10:00 | Beginner, capacity 2, 1 booked: the last-place demo |
| In 3 days, 14:00 | Intermediate, capacity 2, full, with Bruno waiting |
| In 9 days, 10:00 | Beginner, beyond the forecast, so it shows Unknown |
| Credits after seeding | Approved last month: 5-packs for Ana, Bruno and Diogo, a 1-pack for Carla. After the seeded bookings: Ana 3, Bruno 2, Carla 0, Diogo 2. Diogo also has a pending 5-pack request |
| Notifications | A few read and unread ones per student |

Ana is seeded at level Beginner; Bruno, Carla and Diogo at Intermediate. Carla and Diogo fill the Intermediate session, which is why Carla ends with 0 credits.

### Before the presentation

- The day before: rehearse on the deployed app, then run `seed.py --target live` to reset the data.
- On the day: open the URL ten minutes early so the app is awake, and log in on the phone and the laptop.
- Presenting on 4 Dec: open the app or the Supabase dashboard at least every five days after 23 Nov, because free projects pause after a week without activity.

## 15. Files to create first

These seven files are written on Day 0, before any feature, because every agent session and every reviewer depends on them. Copy each block as it stands, then fill in the placeholders.

### `AGENTS.md`

```markdown
# AGENTS.md: LineUp

## Project
LineUp is a Streamlit app that books surf sessions for a campus surf club, with an Open-Meteo forecast labelling each session. The full product spec is docs/product-spec.md. Read the rules in section 5 that a task touches before changing behaviour.

## Commands
- Install: uv sync
- Run the app: uv run streamlit run app.py
- Run all tests: uv run pytest -q
- Reset local demo data: uv run python scripts/seed.py

## Where code goes
- Screens: app.py and app_pages/. Only these and lineup/ui.py import streamlit.
- Rules: lineup/logic/. Pure functions only: no streamlit, sqlalchemy, httpx or clock reads. "now" is a parameter.
- Actions: lineup/services/. Every public function loads the actor from the database, checks lineup/permissions.py, applies logic/, writes in ONE transaction (notifications included) and returns a Result.
- Tables: only lineup/schema.py. Queries: only lineup/db.py.
- Open-Meteo: only lineup/openmeteo.py. Supabase Auth: only lineup/auth.py.
- Secrets: only through lineup/config.py.

## Conventions
- Services never raise for expected problems. They return Result(ok, code, message, data) with a code from lineup/models.py.
- Database datetimes are naive UTC. Display converts to Europe/Lisbon through lineup/timeutil.py.
- Money is integer cents. Credits are integers.
- SQL uses SQLAlchemy Core with bound parameters. Never build SQL with f-strings or concatenation.
- Never use unsafe_allow_html with text a user typed.
- Never cache the Supabase client.

## Rules for every task
- Each task happens on its own branch named after it, never on main. Git is done by the member in GitHub Desktop; do not run git commands unless asked.
- Do only what the task's spec in specs/ asks for.
- Write the task's tests first and show them failing before implementing.
- After every change run uv run pytest -q and paste the final output. The output is the proof, not a sentence.
- Never edit, delete or skip anything in tests/ unless the task says so. If a test looks wrong, say so and stop.
- Tests never touch the network or Supabase. Use tests/conftest.py and tests/fixtures/.
- Do not change lineup/schema.py unless the task says so.
- Do not add or upgrade dependencies without asking. If approved, update pyproject.toml and uv.lock together and add a line to docs/decisions.md.
- Never create, edit or print .streamlit/secrets.toml or .env. Never write keys, passwords or connection strings anywhere.
- Never run scripts/seed.py --target live without asking first.
- When finished, list every file you changed.
```

### `README.md` (template)

```markdown
# LineUp: surf session booking for a campus surf club

Live app: https://lineup-surf.streamlit.app

Students book surf sessions with prepaid credits, instructors run and call off sessions, and admins approve payments and read reports. Live wave and wind forecasts from Open-Meteo label every session Go, Marginal, No-go or Unknown.

## Team
| Name | Student number |
| --- | --- |
| ... | ... |

## Try it
Sign up with any @novasbe.pt address to use the student screens. Instructor and admin demo logins were sent to the teaching staff privately.

## Run it locally
1. Install uv: https://docs.astral.sh/uv/
2. uv sync
3. uv run python scripts/seed.py   (creates data/lineup.db with demo data)
4. uv run streamlit run app.py

With no secrets file the app runs in local demo mode on the SQLite file: pick a demo user instead of logging in. To use Supabase, copy .streamlit/secrets.toml.example to .streamlit/secrets.toml and fill it in.

## Run the tests
uv run pytest -q   (no secrets or network needed)

## How it is built
- Screens: app.py, app_pages/
- Rules: lineup/logic/
- Actions and permission checks: lineup/services/
- Storage: lineup/schema.py and lineup/db.py (Supabase Postgres live; SQLite locally and in tests)
- Forecast: lineup/openmeteo.py and lineup/services/forecast.py
- Architecture, decisions and limits: docs/

## If Open-Meteo is down
The app shows the last saved forecast with its time, or Unknown if none is usable. Booking keeps working; labels never block or cancel anything.

## What the tests cover and do not cover
(copy the two tables from section 13 of the spec)

## Dependencies
(copy the table from section 7 of the spec)

## Credits
Weather data: Open-Meteo.com, wave models by Météo-France, ECMWF, NOAA and DWD (https://open-meteo.com/en/licence).
```

### `pyproject.toml`

```toml
[project]
name = "lineup"
version = "1.0.0"
description = "Surf session booking for a campus surf club, with the ocean forecast in the rules"
requires-python = ">=3.12"
dependencies = [
    "streamlit>=1.40",
    "sqlalchemy>=2.0",
    "psycopg[binary]>=3.2",
    "supabase>=2.0",
    "httpx>=0.27",
    "pandas>=2.0",
    "tzdata>=2024.1",
]

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

Also create `.python-version` containing `3.12`, then run `uv lock` and commit `uv.lock`.

### `.gitignore`

```text
.venv/
__pycache__/
*.pyc
.pytest_cache/
data/
*.db
.env
.streamlit/secrets.toml
.DS_Store
```

### `.streamlit/secrets.toml.example`

```toml
# Copy to .streamlit/secrets.toml. Never commit that file.
# Leave DATABASE_URL out to use the local SQLite file data/lineup.db.
DATABASE_URL = "postgresql+psycopg://postgres.<ref>:<password>@<pooler-host>:5432/postgres"
SUPABASE_URL = "https://<ref>.supabase.co"
SUPABASE_ANON_KEY = "<publishable or anon key>"
```

### `.streamlit/config.toml`

```toml
[theme]
primaryColor = "#0E7490"
```

### `.github/workflows/ci.yml`

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - name: Install from the lock file
        run: uv sync --locked
      - name: Run the tests
        run: uv run pytest -q
      - name: Audit dependencies
        run: |
          uv export --no-dev --no-hashes --format requirements-txt -o /tmp/requirements.txt
          uvx pip-audit -r /tmp/requirements.txt
```

Check the current major version of both actions on their GitHub pages before committing; use the newest one shown.

## 16. Build order

Fourteen tasks, each one branch, one pull request and one spec file in `specs/`. Tasks T0–T10 must be merged by the end of Thursday 19 Nov; if they are not, drop T11 and stretch work, never tests.

&#91;embedded content: Build timeline · 14 tasks, 15–23 Nov 2026\]

Member 1 lays the shared foundation on Sunday and Monday. From Monday the three feature owners work in parallel, and everyone joins for hardening and rehearsal.

| Task | Builds | Rules | Owner | Starts after | Done when |
| --- | --- | --- | --- | --- | --- |
| T0 Skeleton and deploy | Section 15 files, config, models, timeutil, schema, db engine, `app.py` with a login placeholder, CI | — | Member 1 | — | CI green; the live URL shows the login page; tables exist in Supabase with RLS on |
| T1 Accounts and roles | `auth.py`, login page, profiles, `permissions.py`, Members page, local demo mode | R1, section 3 | Member 1 | T0 | Account, member and permission tests green; every demo account logs in live |
| T2 Seed and invariants | `scripts/seed.py`, `check_invariants`, test fixtures and factories | Sections 9, 14 | Member 1 | T0 | Seed tests green; demo data visible locally and live |
| T3 Sessions | Session rules and service, My sessions page | R2 | Member 3 | T2 | Session tests green; an instructor creates and edits a session live |
| T4 Credits and ledger | Packs, requests, approval, ledger, Credits and Credit requests pages | R10 | Member 4 | T2 | Credit tests green; a request approved live raises the balance |
| T5 Booking and cancellation | Booking, cancellation, refund window, last-place update, Sessions and My bookings pages | R3, R5 | Member 2 | T3, T4 | Booking and cancellation tests green; A2–A5 and A7 pass by clicking |
| T6 Waitlist | Join, leave, promotion with skips, capacity increase | R4, R2.10 | Member 2 | T5 | Waitlist tests green; A6 passes by clicking |
| T7 Notifications | `notify` inside every action, Inbox, sidebar count with 10-second refresh | R11 | Member 4 | T2 | Notification tests green; the count updates on a second device |
| T8 Forecast and conditions | `openmeteo.py`, forecast service, condition rules, badges, footer | R6, R7 | Member 3 | T2 | Condition and forecast tests green; live labels on the deployed app |
| T9 Call-off and attendance | Call-off, roster, attendance, decision list, roster CSV | R8, R9 | Member 3 | T5, T7, T8 | Call-off and attendance tests green; A11 passes by clicking |
| T10 Reports and exports | KPIs, charts, CSV exports, statements | R12 | Member 4 | T5 | Report tests green; the KPIs match the seed when checked by hand |
| T11 Settings | Threshold form, forecast mode switch | R6.6, R7.6 | Member 3 | T8 | Tests green; switching mode changes the labels live |
| T12 Hardening | Invalid-input sweep, manual checklist, docs, README, security checks, repository made public | Sections 12–14, 17, 18 | Everyone, led by Member 1 | T11 | Checklist passes on the live URL; history scanned; repository public |
| T13 Rehearsal and freeze | Two full demo runs, walkthrough drill, data reset, submission | Section 17 | Everyone | T12 | Link submitted on Moodle before 23 Nov, 23:59 |

Member 1 is the technical lead: owner of the shared files (`schema.py`, `db.py` core, `AGENTS.md`) and second reviewer of every pull request. Every pull request needs a green CI run and one review by someone who did not write it.

Each spec file copies its rules from section 5 into the course's four headings: Why, What (one line per rule), Out of scope, Done when.

## 17. Demo and walkthrough

The demo tells one story in about seven minutes on two devices. The walkthrough drill makes sure every member can answer any question about any part.

### Demo script

| Step | Device and account | Action | Shows |
| --- | --- | --- | --- |
| 1 | Laptop, Ana | Open Sessions; point at places left and the labels with their numbers | LU03, R6, live external data |
| 2 | Laptop, Ana | Book the last place in the two-place session; read the confirmation | R3, R3.8 |
| 3 | Phone, Bruno | Try the same session: "just filled up"; join the waitlist as #1 | R3.8, R4 |
| 4 | Laptop, Ana | Try tomorrow's 10:30 session, which overlaps her 10:00 one: clash message | R3.5, refused input |
| 5 | Laptop, admin Marta | In Settings, lower the Beginner Go-wave threshold to 0.5 m; tomorrow's 10:00 session changes label | R6.6, LU14 |
| 6 | Laptop, instructor Tiago | "Needs your decision" lists it; call it off with category Conditions; the dialog states the refunds | R8 |
| 7 | Phone, Bruno | Within 10 seconds the inbox shows the call-off and the refund | R11, live refresh |
| 8 | Laptop, Ana | Cancel the two-place session more than 24 h ahead: refunded; Bruno is promoted on the phone | R5, R4.3 |
| 9 | Laptop, Marta | Approve Diogo's pending pack; open Reports; download a CSV | R10, R12 |
| 10 | Laptop, Marta | Switch the forecast to Saved only: labels read "Forecast from ..."; switch back and restore the threshold | R7, fallback |
| 11 | Laptop, visitor | Sign up with a gmail address: a clear refusal | R1.1 |

Before the demo: reset the live data with the seed the day before, log the phone in as Bruno and the laptop as Ana, and keep Marta and Tiago in other browser profiles. One member operates; the others narrate. If Open-Meteo is down that day, step 10 is happening for real: say so and continue.

### Walkthrough drill

Practise until every member answers each question in under a minute, pointing at the file.

| Question | Short answer | Point at |
| --- | --- | --- |
| Where is the data stored? | Supabase Postgres, 12 tables defined in one file; SQLite in tests and local runs | `lineup/schema.py`, `lineup/db.py` |
| What do the tests cover, and not cover? | Every rule with allowed, refused and boundary cases; not layout, real login, the live API or truly parallel clicks | `tests/`, README |
| What if Open-Meteo is unavailable? | The saved forecast with its time, or Unknown; a retry after 10 minutes; booking keeps working | `lineup/services/forecast.py` |
| What stops a student approving credits? | The service reloads the role and checks permissions before anything else, and a test proves it | `lineup/permissions.py`, `tests/test_permissions.py` |
| What if two students book the last place at once? | One conditional update; the database lets only one succeed, and the other is offered the waitlist | `lineup/db.py` |
| Why doesn't No-go cancel automatically? | The model forecasts offshore waves, not the beach; the instructor decides and the app advises | R6.5, `docs/decisions.md` |
| Why a ledger instead of a balance column? | Every change is traceable, unique references stop double refunds, and the balance is a sum | R10.8 |
| Why Streamlit, and what are its limits? | The course stack, strong for forms and tables; limits are polling instead of push, and a refresh logs you out | `docs/decisions.md`, section 18 |
| What happens if Supabase pauses? | The app shows an error message; we unpause it from the dashboard and check the day before | `docs/limits.md` |
| How would you add a second beach? | A spots table, coordinates per spot, forecast rows keyed by spot | Section 18 |
| How would you add real payments? | A payment provider confirms instead of the admin and writes the same ledger row | Section 18 |

### Teach-back

On Sunday 22 Nov, each member explains, with the code open, a part they did not build. Member 1 explains booking, Member 2 conditions, Member 3 credits and reports, Member 4 accounts and permissions; the others ask the drill questions.

### Docs written in T12

- `docs/architecture.md`: the diagram from section 8 and the click path.
- `docs/decisions.md`: each choice, the alternative rejected and why. Cover Streamlit against a JavaScript stack, Supabase against SQLite on the host, SQLAlchemy Core against plain sqlite3, ledger against a balance column, polling against push, and Open-Meteo against paid surf APIs.
- `docs/limits.md`: section 18.
- `docs/demo-script.md`: the table above.
- `docs/manual-test-checklist.md`: section 13.

## 18. Limits, risks and future changes

These limits are known and accepted for a three-week student project. Naming them, with their reasons, is part of the walkthrough grade.

### Known limits (`docs/limits.md`)

| Limit | Why it exists | Effect |
| --- | --- | --- |
| Changes by others appear within about 10 seconds, not instantly | Streamlit polls with fragments; there is no push | Another user's change shows on the next refresh |
| Refreshing the browser logs you out | The session lives in Streamlit's memory, not in a cookie | Log in again |
| The app sleeps when unused | Free Streamlit Community Cloud | The first visit can take up to a minute |
| The database pauses after a week without use | Free Supabase plan | Unpause it from the dashboard |
| The forecast reaches about a week ahead | The requested forecast range | Later sessions show Unknown |
| The forecast describes a sea grid cell, not the beach | Wave models run on an ocean grid | Labels are advice; the instructor decides |
| The sign-up domain rule checks format, not ownership | Email confirmation is off for the demo | Anyone can register an @novasbe.pt address as a student |
| No real payments | Out of scope | An admin confirms each payment by hand |
| One beach, one time zone | Scope | Coordinates and Lisbon time are fixed in `config.py` |
| Tests run on SQLite; production runs on Postgres | Tests must need no secrets | Postgres-only differences are untested (stretch in section 19) |

### Risks and fallbacks

| Risk | Fallback |
| --- | --- |
| The eight-day timeline slips | Cut line on Thu 19 Nov: drop T11 and stretch work, never tests |
| A free agent quota runs out mid-task | Each member has their own quota; hand the task to a teammate or pair on one laptop |
| Open-Meteo is down during the demo | The fallback is part of the demo (step 10) |
| Supabase pauses before 4 Dec | Open the app or the dashboard every five days; check the day before |
| A secret reaches GitHub | Rotate it in the dashboard at once, update local and host settings, check the usage page |
| A demo account fails on the day | Log in with every account on the deployed app the day before |

### How LineUp could change

- **Second beach:** a `spots` table with coordinates; sessions and forecast rows gain a spot id.
- **Real payments:** a payment provider's confirmation replaces the admin's approval and writes the same `purchase:` ledger row.
- **Email or Telegram notifications:** `notify()` is the one place notifications are created, so a sender plugs in there.
- **Instant updates:** a JavaScript front end with Supabase Realtime replaces the screens; services and rules stay as they are.
- **Smarter labels:** wave period and wind direction join the rules, and thresholds become a table per spot and level.

## 19. Stretch features

Start these only after T0–T10 are merged and green. Each is optional and independent, and none changes a rule in section 5.

| Feature | What it adds | How to build it safely | Done when |
| --- | --- | --- | --- |
| AI conditions briefing | A two-sentence, plain-language summary of tomorrow's conditions on the Sessions page | Requesty, the course standard, with a free model. Send only the forecast numbers. A reply over 280 characters or containing a link is replaced by a template sentence. One call per date per hour, stored. Labelled "AI-generated"; it never affects a rule. Key in `REQUESTY_API_KEY` | Tests with fake replies cover a good reply, a too-long reply, a failure and the stored copy. The free plan's 200 requests a day, shared by the account, are never at risk |
| PDF monthly report | A one-page PDF with the KPIs and the list of call-offs | One extra dependency (fpdf2), justified in `docs/decisions.md` | A test checks the file starts with `%PDF` and that only admins can download it |
| Postgres in CI | The whole test suite also runs on Postgres | A Postgres service container in the workflow; tests use `DATABASE_URL` when it is set | Both CI runs green; the "Postgres-only behaviour" row leaves section 13 |
| Screen smoke tests | Automated checks that key pages render | Streamlit's `AppTest`: the login page, a refused sign-up, the Sessions page in local demo mode | Tests green with no secrets |
