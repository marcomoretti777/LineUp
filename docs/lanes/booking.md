# Booking lane: walkthrough notes

Owner: Member 2. Capabilities LU03–LU06, rules R3, R4 and R5, scenarios A2–A7.
Spec: `docs/product-spec.md` (sections 5, 6, 8, 13 and 18). Shared functions: `docs/contract.md`.

| Layer | File | Job |
| --- | --- | --- |
| Screens | `app_pages/sessions.py`, `app_pages/my_bookings.py` | Show cards and dialogs; call one service per click |
| Actions | `lineup/services/booking.py` | Permission, rules, writes, notifications: one transaction each |
| Rules | `lineup/logic/booking.py` | Pure checks: no database, no clock, "now" is a parameter |
| Queries | `lineup/queries/booking.py` | Lane SQL in SQLAlchemy Core, bound parameters only |

## 1. A booking click, end to end

1. **Page.** On the Sessions page the student clicks **Book**. `_book_dialog` in `app_pages/sessions.py` opens an `st.dialog` that shows the credit it uses, the free-cancellation deadline (`SessionCard.free_cancel_until`) and the conditions label. For a No-go or Unknown label it also shows `booking.call_off_warning` (R3.10). On **Confirm** the page calls `ui.run_action(booking.book, engine, actor_id, session_id)`.
2. **Service.** `book()` opens one transaction (`engine.begin()`), then:
   - re-reads the actor with `db.get_actor` and checks `permissions.require(actor, Action.BOOK, owner_id=actor.id)`. The role always comes from the database, never from the screen (R3.1);
   - loads the session (`db.get_session`), locks the member row (`db.lock_member`, `SELECT … FOR UPDATE` on Postgres), and reads the balance (`db.ledger_balance`) and the first clashing booking (`_clash_at`).
3. **Rules.** It asks `rules.check_can_book(...)`, which checks in a fixed order: role, called off or past the cutoff (R3.2, R3.3), duplicate (R3.7), clash (R3.5), credits (R3.4). The first broken rule names the refusal. If one is broken, the service returns that `Result` and writes nothing.
4. **Database.** `q.reserve_place` runs a single guarded `UPDATE … SET booked_count = booked_count + 1 WHERE status = 'scheduled' AND booked_count < capacity` (R3.8). With no row changed the session is full: the service returns `full` with `data={"can_join_waitlist": True}`. Otherwise it writes, in the same transaction:
   - `q.insert_booking`: the booking row;
   - `db.ledger_add(-1, "booking:<id>")`: the charge (R3.4, R10.8);
   - the student's own waiting entry, if any, set to `promoted` (R3.9);
   - `db.notify`: the confirmation (R11.1, R11.2).
5. **Back on the page.** The `Result` comes back, and `ui.show_result` shows "Booked: Fri 20 Nov, 10:00. 2 credits left. Free cancellation until Thu 19 Nov, 10:00." An unexpected exception never reaches the student: `run_action` logs it and shows "Something went wrong (ref XXXXXX)".

Cancelling follows the same shape. `cancel_preview` and `cancel_booking` share `_check_cancel`, so the dialog never offers something `cancel_booking` would then refuse (R5.1, R5.2). `cancel_booking` flips the booking with a guarded UPDATE (a second click gets `already_done`, R5.4), frees the place, adds a `refund:<id>` ledger row inside the 24-hour window, and runs `promote_waitlist` in the same transaction (R5.3).

## 2. Why the atomic update and the ledger

**Atomic update (R3.8).** Reading `booked_count`, checking it in Python and then writing it back would let two students both see "1 place left" and both book. The single guarded `UPDATE` hands that decision to the database: whichever statement runs first changes the row, and the second sees `booked_count = capacity` and changes nothing. The service trusts only `rowcount`, never the count it read earlier. Promotion uses the same `reserve_place`, so a promotion and a direct booking can never overfill a session either.

**Ledger (R10.7, R10.8).** There is no balance column. The balance is the sum of the member's ledger rows, and rows are never edited or deleted. This gives three things:
- **History for free.** The statement is just the rows.
- **No double refunds.** Each row has a unique `ref` (`booking:57`, `refund:57`). A second refund for the same booking fails the unique constraint, `ledger_add` returns `False`, and nothing is written.
- **Checkable money.** `db.check_invariants` checks that every booking has exactly one charge, at most one refund, and that `refunded` matches. It runs after every test.

`lock_member` before reading the balance stops two tabs from both spending the last credit on Postgres. SQLite serialises writes on its own.

## 3. Waitlist promotion

- **Order (R4.2).** `rules.promotion_order` sorts by join time, earliest first, with ties broken by entry id so the order is always total. `_rank` turns that order into the "#3" a student sees (R4.6). The join message, the Sessions card and My bookings all use `_rank`, so they always show the same number.
- **When it runs.** `promote_waitlist(conn, session_id, now)` runs inside the caller's transaction: after a cancellation (R5.3) and after an instructor raises capacity (R2.10, called from the sessions lane).
- **What it does (R4.3).** While places are free, it takes the next waiting student, locks them, and runs the same `check_can_book` that `book()` uses. If the student can book, it reserves the place, charges 1 credit, marks the entry `promoted` and notifies "You got a place". If they cannot (no credits, or a clash), the entry becomes `removed` with a short reason ("no credits", "clash"), the student is notified with the refusal message, and the next student is tried.
- **When it stops (R4.4).** Once booking has closed (less than 2 h before the start) it promotes nobody, and the free place stays empty. It also stops for a called-off session, and when `reserve_place` reports no place.
- **Joining and leaving.** Joining needs no credit (R4.1): the credit is checked at promotion. `check_can_join_waitlist` reports `duplicate` before `not_full`, so a booked student hears "already booked" rather than "book directly". Leaving goes through `check_can_leave_waitlist`, which stays open after the booking cutoff right up to the start (R4.5).

## 4. What the tests cover and do not cover

| File | Layer | Covers | Cases |
| --- | --- | --- | --- |
| `tests/test_booking_rules.py` | Pure rules | Every R3, R4.1, R4.2, R4.5 and R5 check: allowed, refused and boundary; check order; messages come from the catalogue and name the right time | 66 |
| `tests/test_booking.py` | Service | R3.1–R3.5, R3.7–R3.9 on a real (in-memory) database: charges, cutoff at 2:00/1:59, clash and back-to-back, last place, waitlist exit | 13 |
| `tests/test_waitlist.py` | Service | R4.1–R4.6 and R2.10: join rules and the cutoff boundary, position, leave (including after the booking cutoff, twice, after promotion), promotion order, skip with a reason, no promotion at 1:59, promotion at exactly 2:00 | 24 |
| `tests/test_cancellation.py` | Service | R5.1–R5.4: refund at 24:00 and none at 23:59, one minute before the start, at the start, another's booking, twice, preview, promotion triggered | 13 |
| `tests/test_booking_views.py` | Read models | Card states, disabled-button labels, statuses, My bookings lists | 42 |
| `tests/test_scenarios.py` (lead) | End to end | A2–A7, one test each | 6 |

Every test that touches the database also runs `db.check_invariants`, so a bug that breaks counts, ledger or overlaps fails even when no assertion looks for it.

**Not covered by automated tests:**

| Gap | Why | How it is checked instead |
| --- | --- | --- |
| Screen layout, dialogs and wording on the page | Streamlit pages are not unit-tested | The manual checklist below, on the live URL |
| Truly simultaneous clicks; Postgres `FOR UPDATE` | Tests run on SQLite, in sequence | The atomic UPDATE is tested in sequence; locking is reasoned about |
| R3.6, the Intermediate level rule | A Should, not built yet | Listed as a limit below |
| Exact-minute boundaries on the live app | The real clock cannot be fixed | Covered by the fixed-`now` tests; the checklist checks either side |

## 5. Three limits and how each could change

1. **A place freed inside the last two hours stays empty (R4.4).** Promotion stops at the booking cutoff, so a late cancellation wastes the place even with people waiting.
   *Change:* at the cutoff, notify the waiting students with a "last-minute place" message and let the first to book take it, which still goes through `reserve_place`. The cutoff in `rules.booking_open` would become a separate, shorter "late booking" limit.
2. **Concurrency on Postgres is reasoned about, not tested.** The atomic UPDATE and `lock_member` are correct by design, but the suite runs on SQLite. Also, `join_waitlist` does not lock the member, so two joins in the same instant could hit the unique index and show a generic error instead of `duplicate`.
   *Change:* run the suite on Postgres in CI (spec section 19) and add a two-connection test; take the member lock in `join_waitlist` as `book` does.
3. **Everyone can book Intermediate sessions (R3.6 not built).** The spec makes the level rule a Should, so until it ships a beginner can book an Intermediate session.
   *Change:* pass the student's level and attended-Beginner count into `check_can_book` and `check_can_join_waitlist` and return `level` (the code and message already exist). Promotion would then skip such a student automatically, because it uses the same check.

## 6. Manual checklist A2–A7 (live URL)

Run on the deployed app with the demo accounts from spec section 14 (Tiago instructor; Ana, Bruno, Carla students; Marta admin). The automated tests fix the clock at exact boundaries. On the live app you check the behaviour on either side of each boundary. Times are Lisbon time.

**Setup (once).**
- ☐ As Marta, approve credit requests so that Ana has 3 credits, Bruno 2 and Carla 0. Students request packs on the Credits page; Marta approves them on Credit requests.
- ☐ Note each student's balance in the sidebar before each scenario.

### A2. Booking cutoff (R3.3)
- ☐ As Tiago, create a Beginner session, capacity 4, starting about 3 h 15 min from now (the earliest allowed, R2.2). Note its start time S.
- ☐ Before S − 2:00, as Ana, click **Book** → **Confirm**. Expect "Booked: …", her balance down by 1, and her card showing her as booked.
- ☐ After S − 2:00, as Bruno, open Sessions. Expect the card's button disabled with the text **Booking closed** and the session missing from "Only sessions I can book".
- ☐ If Bruno's page was opened before the cutoff, click **Book** → **Confirm** after it. Expect "Too late: booking closed at <S − 2:00>." and no balance change.

### A3. Last credit (R3.4, R10.7)
- ☐ Give a student exactly 1 credit (for example Carla after one 1-pack approval). As Tiago, create two non-overlapping sessions X and Y.
- ☐ As that student, book X. Expect "Booked: … 0 credits left …" and sidebar balance 0.
- ☐ Book Y. Expect "You have no credits left. Request a pack on the Credits page." and the balance still 0, never negative.

### A4. Clash (R3.5)
- ☐ As Tiago, create a 90-minute session 10:00–11:30 on a future day. As Inês, create 11:00 (60 min) and 11:30 (60 min) sessions the same day.
- ☐ As Ana, book 10:00. Then book 11:00. Expect "You already have a session at that time (10:00)." and no charge.
- ☐ Book 11:30. Expect "Booked: …" (back-to-back is fine).

### A5. Last place (R3.8, R4.1)
- ☐ As Tiago, create a session with capacity 2. As Carla (given a credit) or another student, book one place.
- ☐ As Ana, book. Expect "Booked: …" and the card showing 0 places left.
- ☐ As Bruno, open Sessions. Expect the card full, with **Join waitlist** instead of Book. Click it. Expect "You're on the waitlist for …: #1." and My bookings showing #1.
- ☐ Ask Tiago to open the roster. Expect exactly 2 booked.
- ☐ Optional race: Ana and Bruno open the dialog for the last place at the same time and both confirm. The second sees "This session just filled up. Join the waitlist to get the next free place."

### A6. Promotion with a skip (R4.3, R5.2)
- ☐ As Tiago, create a capacity-1 session at least 30 h from now. As Ana, book it.
- ☐ As Carla (0 credits), click **Join waitlist**: #1. As Bruno (at least 1 credit), join: #2.
- ☐ As Ana, on My bookings click **Cancel**. Expect the dialog to say "Your credit will be refunded." Confirm. Expect "Cancelled: … 1 credit refunded." and her balance up by 1.
- ☐ As Carla, open Inbox. Expect "Removed from the waitlist for … You have no credits left. …" and the session gone from her waitlist.
- ☐ As Bruno, expect the session under upcoming bookings in My bookings, the balance down by 1, and an Inbox message "You got a place: … Free cancellation until …".

### A7. Refund window (R5.1, R5.2)
- ☐ As Tiago, create one session more than 24 h away and one less than 24 h away (but more than 3 h). Ana books the first; Bruno books the second.
- ☐ As Ana, click **Cancel**. Expect the dialog to say "Your credit will be refunded."; confirm, and expect a refund (balance +1).
- ☐ As Bruno, click **Cancel**. Expect the dialog to warn "Less than 24 hours before the start: no refund." *before* the button. Confirm; expect "No refund: cancelled less than 24 h before the start." and no balance change.
- ☐ For a booking whose session has started (for example the A2 session after S), as Ana, open My bookings. Expect no Cancel button: the booking now sits in the history list, because cancellation closed at the start.

**Afterwards.** Note any step that failed, with the time and account, in the B07 pull request.
