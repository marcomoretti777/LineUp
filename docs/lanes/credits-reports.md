# Credits and reports lane: walkthrough notes

Member 4 owns credits, notifications, attendance and reports. This page explains how
that part of LineUp works, why it is built this way, and where to look in the code.
The rule numbers (R9–R12) and scenarios (A13, A17) refer to `docs/product-spec.md`.

## 1. How a credit request is approved

1. **The student asks.** On the Credits page the student picks a pack and types the
   MB WAY payment reference. `request_pack` in `lineup/services/credits.py` checks
   that the person is a student, that the pack exists, that they have no other pending
   request (R10.2), and that the reference is 3–40 letters, digits, spaces or `- / #`
   (R10.3). It then saves a **pending** request. No credits change yet.
2. **The student may change their mind.** `withdraw_request` turns their own pending
   request into **withdrawn** (R10.4).
3. **An admin decides.** On the Credit requests page an admin checks the payment and
   clicks Approve or Reject.
   - `approve_request` writes one ledger row of `+credits` with the reference
     `purchase:<request id>` (for example `purchase:12`), marks the request
     **approved**, and sends the student a notification. All of this happens in one
     database transaction.
   - `reject_request` needs a note of 3–200 characters (R10.5), marks the request
     **rejected**, and notifies the student with the note.
4. Deciding a request that is no longer pending changes nothing and answers
   "Nothing changed: this was already done." (R10.6).

### Why the ledger makes approvals and refunds safe to repeat

LineUp never stores a balance. Every change to a student's credits is one row in the
`credit_ledger` table: `+5` for a purchase, `-1` for a booking, `+1` for a refund.

- **The balance is the sum of the student's rows** (`ledger_balance` in
  `lineup/db.py`, R10.7). There is no separate number that could drift away from the
  history.
- **Every row has a unique reference** such as `purchase:12`, `booking:57` or
  `refund:57` (R10.8). The database itself refuses a second row with the same
  reference (`unique=True` on `credit_ledger.ref` in `lineup/schema.py`).
- **`ledger_add` checks the reference before writing** and returns `False` when it
  already exists. `approve_request` stops there, so a double click, a stale browser
  tab or two admins approving at once can never add the credits twice. The booking
  lane uses the same mechanism for refunds (`refund:<booking id>`), so a refund can
  never be paid twice either.
- **Rows are never edited or deleted.** A mistake is corrected by a new row, so the
  statement is a complete history.

## 2. How each report number is defined

The admin picks a period of Lisbon dates, both days included, of at most 92 days
(R12.1). `kpis` in `lineup/services/reports.py` loads the data, and the pure functions
in `lineup/logic/reports.py` do the arithmetic.

| Number | Definition | Shown as "—" when |
| --- | --- | --- |
| Sessions run | Sessions starting in the period that were **not called off** and have **already ended** (R12.2) | never: it is a count |
| Called off | Called-off sessions starting in the period, all categories together (R12.6) | never |
| Fill rate | Confirmed bookings in the sessions run ÷ the total capacity of those sessions (R12.3). Example: 6 of 8 places = 75% | there were no sessions run |
| No-show rate | No-shows ÷ (attended + no-shows) in the sessions run (R12.4). Unmarked bookings are left out | nobody has been marked yet |
| Credits sold | Credits in the requests **approved** in the period (R12.5) | never |
| Revenue | Price of those approved requests, kept in integer cents and shown as euros (R12.5). Example: one 5-pack and one 1-pack = 6 credits, €80.00 | never |
| Call-offs by category | Called-off sessions starting in the period, counted per category (Conditions, Instructor unavailable, Other) (R12.6) | the chart says "No data for this period." |

A session that ends exactly at the current time counts as run. One that ends a minute
later does not. Period edges follow Lisbon time, so an approval at 23:30 on 31 July
Lisbon time belongs to July, even though it is 22:30 UTC.

## 3. Why some CSV cells start with an apostrophe

Spreadsheet programs treat a cell that starts with `=`, `+`, `-` or `@` as a formula.
A student could sign up with the name `=HYPERLINK("http://evil.example","Click")`, and
an admin who opened the export would see a live link or formula instead of a name
("CSV injection"). `csv_safe` in `lineup/logic/reports.py` puts an apostrophe in front
of any text cell that starts with one of those characters, so the spreadsheet shows it
as plain text (R12.7). Numbers are left alone, so a ledger change of `-1` stays a
number. Every export (roster, statement, bookings, ledger, requests) goes through
`to_csv`, which applies `csv_safe` to every cell, and each file holds only the listed
columns.

## 4. Who can see what, and where it is enforced

Every action re-reads the member's role from the database and calls
`permissions.require(actor, action, owner_id)` inside the service function
(`lineup/permissions.py`). Hiding a button on a page is never the check. A refused
action returns `forbidden`, writes nothing, and the page shows "You don't have
permission to do that."

| What | Student | Instructor | Admin | Where |
| --- | --- | --- | --- | --- |
| Credit statement and its CSV | own only | no | any member | `statement` in `services/credits.py` (VIEW_STATEMENT) |
| Request or withdraw a pack | own only | no | no | `request_pack`, `withdraw_request` |
| Approve or reject requests | no | no | yes | `approve_request`, `reject_request`, `pending_requests`, `decided_requests` (DECIDE_CREDITS) |
| Inbox | own only | own only | own only | `services/notifications.py` (READ_NOTIFICATIONS); the query is always filtered by the actor's own id |
| Roster, attendance, roster CSV | no | own sessions | any session | `roster`, `mark_attendance`, `roster_csv`, `roster_sessions` in `services/attendance.py` (VIEW_ROSTER, MARK_ATTENDANCE, EXPORT_ROSTER), with `owner_id` = the session's instructor |
| Reports and their CSVs | no | no | yes | `kpis`, `chart_data`, `bookings_csv`, `ledger_csv`, `requests_csv` in `services/reports.py` (VIEW_REPORTS) |

## 5. What the tests do not cover

The lane has 129 automated test cases (`tests/test_credit_rules.py`,
`test_credits.py`, `test_notifications.py`, `test_attendance.py`, `test_reports.py`).
They do not cover:

| Not covered | How it is checked instead |
| --- | --- |
| How the five pages look and read | The manual checklists below, on the deployed app |
| Two admins clicking Approve at the same moment | Tested one after the other. On Postgres the request row is locked (`SELECT … FOR UPDATE` in `get_request`) and the unique ledger reference is the last line of defence; that locking is reasoned about, not tested |
| Postgres itself | Tests run on in-memory SQLite, so Postgres-only differences are untested |
| Opening the CSV files in Excel or Google Sheets | Done by hand: the apostrophe rule is tested on the text, not in a spreadsheet |
| The sidebar's unread count refreshing within 10 seconds | Checked by hand in the browser |

## 6. Three limits and how each could change

1. **Payments are confirmed by hand.** An admin compares the MB WAY reference with
   the club's bank app. *Change:* a payment provider's confirmation would call the
   same approval step and write the same `purchase:` ledger row, so balances and
   reports would not change.
2. **Reports are recalculated on every page load**, which is why a period is capped
   at 92 days. *Change:* cache each period's numbers for a few minutes, or store daily
   totals in a summary table, then allow a longer period.
3. **The roster picker reaches back only 7 days** (`ROSTER_LOOKBACK` in
   `services/attendance.py`), so attendance older than a week can't be corrected from
   the screen. *Change:* add a date picker, or make the look-back an admin setting.

## 7. Walkthrough questions

**1) Why is the balance a sum of ledger rows instead of a stored number?**
A stored number can disagree with the history after a bug or a half-finished action.
A sum can't: the balance *is* the history. Point at `ledger_balance` in
`lineup/db.py` and the `credit_ledger` table in `lineup/schema.py`. The statement page
shows the same rows with a running balance (`statement` in
`lineup/services/credits.py`).

**2) What stops an approval from adding credits twice?**
The ledger row's unique reference `purchase:<request id>`. `approve_request` in
`lineup/services/credits.py` calls `db.ledger_add`, which returns `False` if that
reference already exists, and the service then answers "Nothing changed" without
touching anything else. The `unique=True` constraint on `credit_ledger.ref` backs it
up in the database. Test: `test_r10_6_approve_twice_already_done_one_ledger_row`.

**3) How is the fill rate calculated, and what does the page show with no data?**
Confirmed bookings in the sessions run ÷ their total capacity: `fill_rate` in
`lineup/logic/reports.py`, fed by `sessions_run` in `lineup/queries/reports.py`. With
no sessions run it returns `None`, and the Reports page shows "—". Tests:
`test_r12_3_fill_rate_six_of_eight_places` and
`test_r12_3_fill_rate_without_sessions_is_none`.

**4) Why do CSV exports put an apostrophe before some cells?**
So a name or note starting with `=`, `+`, `-` or `@` can't run as a spreadsheet
formula when an admin opens the file. Point at `csv_safe` and `to_csv` in
`lineup/logic/reports.py`. Tests: `test_r12_7_csv_safe_prefixes_formula_starts` and
`test_r12_7_roster_csv_escapes_formula_name`.

**5) Who can see a student's credit statement, and where is that enforced?**
The student themselves and any admin, never an instructor or another student. It is
enforced by `permissions.require(actor, Action.VIEW_STATEMENT, owner_id=…)` inside
`statement` in `lineup/services/credits.py`, using the matrix in
`lineup/permissions.py`. Tests: `test_r10_7_student_other_statement_forbidden`,
`test_r10_7_admin_sees_any_statement` and `test_r10_7_instructor_statement_forbidden`.

**6) What do your tests not cover?**
The look of the pages, truly simultaneous clicks, Postgres-only behaviour, opening the
files in a real spreadsheet, and the 10-second sidebar refresh (section 5 above). Each
is checked by hand or reasoned about instead.

## 8. Manual checklist on the live URL

These steps need the demo accounts: an admin, a student with no pending request, and
some sessions, bookings and call-offs in the current month. The seed script creates
these once it exists.

### A13: credit approval

1. Log in as the student and open **Credits**. Note the balance.
2. Choose **5 sessions**, type `MBWAY 912` and click **Request pack**. A "Pending: 5
   sessions" box appears.
3. Choose **1 session**, type `MBWAY 913` and click **Request pack** again. Expect a
   red refusal; there is still only one pending request.
4. Log out and log in as the admin. Open **Credit requests**.
5. Copy the page address into a second browser tab.
6. In the first tab, click **Approve** on the student's request. Expect "Approved: 5
   credits added."
7. In the second tab, click **Approve** on the same request without reloading. Expect
   "Nothing changed: this was already done."
8. Log back in as the student. The balance has risen by exactly 5, the statement shows
   one `purchase:` row, and the Inbox has an "approved" notification.
9. Request another pack as the student, then log in as the admin. Click **Reject**,
   leave the note empty and click **Reject** in the dialog. Expect a red "Note: … 3 to
   200 characters" message, with the request still pending.
10. Type `Payment not found` and click **Reject**. The request moves to the
    **History** tab as Rejected, and the student's Inbox shows the note.

### A17: report numbers

1. Log in as the admin and open **Reports**, with **This month** selected.
2. Click **Bookings CSV** and open it. Count the sessions in the file that are not
   called off and have already ended: that count must equal **Sessions run**.
3. For those sessions, add up the confirmed bookings and divide by their total
   capacity: that must equal **Fill rate**.
4. Among those bookings, divide the no-shows by (attended + no-shows): that must equal
   **No-show rate**. If none are marked, the tile shows "—".
5. Click **Requests CSV**. Add up the credits and the `price_eur` of the rows approved
   this month: they must equal **Credits sold** and **Revenue**.
6. Check that **Called off** equals the sum of the bars in **Call-offs by category**.
7. Choose **Custom** and pick a period of more than 92 days. Expect "Period: … days is
   too long …" and no numbers.
8. Choose a month with no activity. Every count is 0 and both rates show "—".
