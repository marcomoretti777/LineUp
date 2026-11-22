# Sessions and forecast lane: walkthrough notes

Owner: Member 3. Capabilities LU07, LU09 and LU14 (Settings, not built yet). Rules R2, R6, R7 and R8. Scenarios A8–A12 and A14.
Spec: `docs/product-spec.md` (sections 5, 6, 10, 13 and 18). Shared functions: `docs/contract.md`.

| Layer | File | Job |
| --- | --- | --- |
| Screens | `app_pages/instructor_sessions.py` | My sessions: "Needs your decision", the create form, edit, delete and call-off dialogs |
| Actions | `lineup/services/sessions.py` | Create, edit, delete, list, call off, decision list: one transaction each |
| Actions | `lineup/services/forecast.py` | Refresh, fallback and the labels for a list of sessions (read-only, no actor) |
| Rules | `lineup/logic/sessions.py` | Pure R2 checks and the call-off input check (R8.2) |
| Rules | `lineup/logic/conditions.py` | Pure R6.1–R6.4: hour window, maximum, thresholds, Unknown cases |
| Client | `lineup/openmeteo.py` | Two GET requests, a 5-second timeout and strict parsing. No database code |
| Queries | `lineup/queries/sessions.py`, `lineup/queries/forecast.py` | Lane SQL in SQLAlchemy Core, bound parameters only |

## 1. The forecast flow (R7)

`forecast.get_forecast(engine, now, fetch)` is the only place that decides whether to call Open-Meteo. Every screen goes through `conditions_for_sessions`, which calls it once per page run. It checks in this order (spec section 10):

1. **Saved-only mode** (`app_settings.forecast_mode = "saved_only"`): use saved data, never call (R7.6).
2. **Newest saved fetch under 60 minutes old**: use saved data (R7.1). The age comes from `max(forecast_hours.fetched_at)`, so 59 minutes means no call and 60 minutes means a call.
3. **Last attempt failed under 10 minutes ago** (`last_forecast_attempt_at` and `last_forecast_error`): use saved data (R7.5). This is the back-off, so a dead API is tried at most every 10 minutes rather than on every click.
4. **Otherwise call both feeds**, each with a 5-second timeout (R7.2, `config.HTTP_TIMEOUT_S`).
   - **Both succeed:** the waves, wind and sunsets are saved in one transaction with `fetched_at = now`, replacing rows for the same hours or days (R7.3). The error setting is cleared.
   - **Either fails** (timeout, HTTP 400, invalid JSON, a missing array or arrays of different lengths, all raised as `ForecastError`): nothing new is saved, the attempt time and error are recorded, and the saved data is used for everything (R7.4). A good marine answer is thrown away if the weather call fails, so labels never mix two fetches.

The settings are read in one short connection and then closed before the network call. Holding a transaction open across a 5-second request would block every other writer.

The note under each badge comes from `_note`:

| Situation | Note |
| --- | --- |
| Just fetched, or saved data under 60 min old | Forecast updated 09:12 |
| Saved data after a failed update (or inside the back-off) | Forecast from 09:12 (live update failed) |
| Saved-only mode, however recent the data | Forecast from 09:12 (saved data, live updates paused) |
| Nothing saved | Forecast unavailable (every label Unknown) |
| Session after the last saved hour | Forecast available closer to the date |

Times are shown in Lisbon time (`timeutil.fmt_time`). The database holds naive UTC.

## 2. How a label is computed (R6)

`conditions.evaluate` is pure. It receives the hour maps, the fetch time, `now` and the thresholds:

1. **Unknown first (R6.4).** The label is Unknown if nothing is saved, or if the newest fetch is more than 12 h old (11:59 is used, 12:01 is not). It is also Unknown if the session's last hour is after the last saved hour (with the "closer to the date" note), or if any hour it needs is missing or empty.
2. **Hour window (R6.1).** `hours_in_window` runs from the hour holding the start to the hour holding the last surfed minute (end − 1 min). A 10:00–11:00 session uses only 10:00.
3. **Worst case (R6.2).** It takes the highest wave and the highest wind across those hours.
4. **Thresholds (R6.3).** The result is Go if waves ≤ Go-wave **and** wind ≤ Go-wind. Otherwise it is Marginal if waves ≤ Marginal-wave and wind ≤ Marginal-wind. Otherwise it is No-go.

**Worked example.** A Beginner session runs 10:00–11:30, and the thresholds are (1.5 m, 25 km/h, 2.0 m, 35 km/h).

| Hour (UTC) | Waves | Wind |
| --- | --- | --- |
| 10:00 | 1.2 m | 18 km/h |
| 11:00 | 1.6 m | 22 km/h |

- The window is 10:00 and 11:00, because the last minute is 11:29.
- The maximums are 1.6 m and 22 km/h.
- 1.6 > 1.5, so it is not Go. 1.6 ≤ 2.0 and 22 ≤ 35, so the label is **Marginal**, and the badge reads "Marginal · Waves 1.6 m · Wind 22 km/h".
- If the 11:00 wind were 35.1 km/h instead, the label would be No-go, even though the waves are calm.

Labels are advice only (R6.5). Booking never reads them, except to show the call-off warning for No-go or Unknown (R3.10). `test_r6_5_*` books a session with each of those labels.

## 3. What call-off does, and why it cannot refund twice (R8)

`sessions.call_off(engine, actor_id, session_id, category, reason, now)` opens one transaction and runs these steps in order:

1. **Actor and permission.** It loads the actor. An unknown session id returns `not_found` to staff and `forbidden` to students, so students can't probe ids. `require(actor, CALL_OFF, owner_id=session.instructor_id)` allows only the session's own instructor or an admin (R8.1).
2. **Repeat and time checks.** An already called-off session returns `already_done`. This is checked before the clock, so a repeat never reads as "closed". If `now ≥ end`, it returns `closed` (R8.1).
3. **Input.** `logic.sessions.check_call_off_input` requires one of the three categories and a trimmed reason of 3–200 characters (R8.2).
4. **The deciding write.** `mark_called_off` runs `UPDATE … SET status='called_off' WHERE id=? AND status='scheduled'`. If no row changes, someone else got there first and the result is `already_done`.
5. Every **confirmed** booking becomes `called_off`. Each gets `ledger_add(+1, "refund:<booking_id>")` and is flagged `refunded`, whatever the time (R8.3). Cancelled bookings are not touched.
6. Every waiting entry becomes `cleared`. Each booked and waiting student gets one `called_off` notification, written in the same transaction (R8.4, R11.2).

**Why no double refund.** There are three independent guards:
- **The status guard.** The status-guarded UPDATE in step 4 lets exactly one call-off win, even if two clicks race.
- **The unique ledger reference.** The ledger's `ref` is unique. A second `refund:57` is blocked, `ledger_add` returns `False`, and nothing is written (R10.8).
- **Only confirmed bookings.** Only confirmed bookings are refunded. A booking already cancelled (and maybe refunded) keeps its own history (`test_r8_3_cancelled_booking_is_not_refunded_again`).

`db.check_invariants`, run after every test, checks that each booking has at most one refund and that the `refunded` flag matches the ledger.

**Session rules (R2).** `validate_new_session`, `check_edit` and `check_delete` are pure. The service adds two things the rules can't know:
- **Clashes with the instructor's other sessions (R2.6).**
- **The latest end (R2.7).** This is the saved sunset for that Lisbon date, read in the same transaction, or 17:00 when no sunset is saved. The refusal names which limit applied ("after sunset (17:15)" or "after 17:00 (no sunset data)"). A capacity-only edit is never re-checked against it.

Raising capacity runs `booking.promote_waitlist` in the same transaction (R2.10).

## 4. What the tests do not cover

| Not covered | How it is checked instead |
| --- | --- |
| The live Open-Meteo service and real network timeouts | Fixtures recorded from real answers; one manual call; the fake fetcher and fake `get` |
| Screen layout and wording, including the R7.7 footer | Manual checklist below |
| The create form saying "17:00 (no sunset data)" before submitting | Only the service message says it today; the page caption shows sunset only. Follow-up for `app_pages/instructor_sessions.py` once S07 is merged |
| Two call-offs at the same instant on Postgres | The guarded UPDATE is tested in sequence; row-level behaviour on Postgres is reasoned about |
| Scenarios A8–A12 and A14 as end-to-end scenario tests | Covered rule by rule in this lane's tests; `tests/test_scenarios.py` is lead-owned |

**Not built (S08):** R6.6 threshold validation and the Settings page (the threshold form, and the switch between live and saved-only). Saved-only mode works if the setting row is set, but no screen sets it yet.

## 5. Three limits and how each could change

1. **The forecast reaches about 7 days ahead.** Sessions can be created up to 14 days ahead, so later ones show Unknown with "Forecast available closer to the date".
   *Change:* ask for `forecast_days=14`. That's one parameter in `openmeteo.py`, but accuracy drops after a week, so the note should then say the forecast is long-range.
2. **"Fetched more than 12 h ago" uses the newest fetch time across all rows.** A refresh replaces only the hours it returns. Hours from an older fetch beyond the new range keep their old values, but are judged by the new fetch time.
   *Change:* load `fetched_at` per hour and let `evaluate` take the oldest fetch time in the session's window.
3. **One sea grid cell, two levels, waves and wind only.** The marine model describes a cell a few kilometres off Carcavelos. Wave period and wind direction, which matter a lot for surf, are ignored.
   *Change:* add a `spots` table with coordinates (forecast rows gain a spot id) and thresholds per spot and level. Then add `wave_period` and `wind_direction_10m` to the requests and to `classify`.

## 6. Manual checklist: A8–A12 and A14 on the live URL

Run it on the deployed URL as each demo role. Tick a box only when the expected result appears exactly.

**Before you start**
- [ ] Log in as an instructor and as an admin.
- [ ] Every screen with a conditions badge ends with "Weather data: Open-Meteo.com, wave models by Météo-France, ECMWF, NOAA and DWD", linked to the licence page (R7.7).

**A8 – Thresholds (R6.3)**

The live sea can't be set to 1.50 m, so the exact edges are proven by `test_r6_3_beginner_threshold_edges`. On the live app, check that the labels agree with the numbers shown.
- [ ] Open Sessions and pick a Beginner session within 7 days. Read "Waves X m · Wind Y km/h" on its badge.
- [ ] Check the word against the Beginner table:
  - Go: X ≤ 1.5 and Y ≤ 25.
  - Marginal: X ≤ 2.0 and Y ≤ 35.
  - No-go: anything else.
- [ ] Do the same for an Intermediate session (2.5/30, 3.0/40).
- [ ] The word is always written in the pill, not shown by colour alone.

**A9 – Forecast failure (R7.4, R6.4)**

There is no Settings page yet (S08), so on the live URL you can only watch this step. Force the failure on a local run.
- [ ] Live: the caption under a badge reads "Forecast updated HH:MM". The time is within the last hour, in Lisbon time.
- [ ] Local, with saved data: run the app, open Sessions once (this fetches), and wait 60 minutes or more. Then disconnect from the network and reload. The badges keep their labels, and the caption reads "Forecast from HH:MM (live update failed)" with the earlier time.
- [ ] Local, in the same state: reload within 10 minutes. The caption doesn't change, and no new attempt is made (back-off, R7.5).
- [ ] Local, with nothing saved: delete `data/lineup.db`, disconnect, and start the app. Every badge is Unknown with "Forecast unavailable".
- [ ] In both local cases, log in as a student with a credit and book a session. The booking succeeds, and the dialog warns that the instructor may call it off.

**A10 – Beyond range (R6.4)**
- [ ] As an instructor, create a session 10 days ahead.
- [ ] On Sessions and on My sessions, it shows Unknown with "Forecast available closer to the date".

**A11 – Call-off (R8.3–R8.5)**
- [ ] Set-up: a session where three students are booked (one of them booked within 24 h of the start) and two students are on the waitlist.
- [ ] As the instructor, open My sessions → Call off. The dialog says "3 students will be refunded and notified".
- [ ] Choose Conditions and type a reason of 2 characters. It is refused: "Reason: it has 2 characters. Allowed: 3 to 200 characters."
- [ ] Type a valid reason and confirm. The result says 3 credits refunded and 2 waiting students notified.
- [ ] Each of the 5 students sees one "Called off: …" notification in their Inbox. Each booked student's balance is up by 1, including the one who booked late.
- [ ] The session shows "Called off" and has no Call off button. Trying again from a stale tab gives "Nothing changed: this was already done.", and no new credits or notifications appear.

**A12 – Wrong person (R8.1)**
- [ ] As a second instructor, open My sessions. The first instructor's session isn't listed, so there is nothing to call off.
- [ ] As a student, the My sessions page says "My sessions is for instructors."
- [ ] (Service-level `forbidden` is covered by `test_r8_1_other_instructor_is_forbidden`. The credit-request half of A12 belongs to the credits lane.)

**A14 – Session validation (R2.1–R2.7)**

Set-up: the instructor already has 10:00–11:30 tomorrow.
- [ ] Capacity 9: the form stops at 8. If you get past it, the refusal reads "Capacity: 9 is above 8. Allowed: a whole number from 1 to 8."
- [ ] A 07:45 start is refused: "Start time: 07:45 is before 08:00…".
- [ ] Choose tomorrow and read "Sunset HH:MM: sessions must end by then" under the time field. Pick a start whose end falls after it. The refusal names the end and "sunset (HH:MM)". If no sunset is saved for that date, no caption appears, and an end after 17:00 is refused with "17:00 (no sunset data)".
- [ ] An 11:00 start is refused: "You already have a session at that time (Sat 21 Nov, 10:00)." (date as shown).
- [ ] An 11:30 start (90 min) is created, and its success message shows the date, time and places.
