# Manual test checklist

The automated suite runs against SQLite with no network, so it cannot prove the deployed app
behaves the same. This checklist walks every acceptance scenario of spec section 6 on the live
app.

Run it on **LIVE_URL_PENDING**. Passwords for the demo accounts are shared privately and are never
written here. Use a private browser window so a stale session does not hide a problem, and tick
each step only when you have seen the stated result with your own eyes.

| Account | Name | Role |
| --- | --- | --- |
| lineup.admin@novasbe.pt | Marta Silva | Admin |
| lineup.tiago@novasbe.pt | Tiago Costa | Instructor |
| lineup.ines@novasbe.pt | Inês Rocha | Instructor |
| lineup.ana@novasbe.pt | Ana Martins | Student |
| lineup.bruno@novasbe.pt | Bruno Lopes | Student |
| lineup.carla@novasbe.pt | Carla Dias | Student |
| lineup.diogo@novasbe.pt | Diogo Alves | Student |

Run `uv run python scripts/seed.py --target live` before a demo if the data has drifted. It asks
you to type RESET first.

## 0. The one check that must pass before any other

**1. Open LIVE_URL_PENDING in a private window, signed out.**
You must see the **Log in / Sign up** page.

**If you see a red "Local demo mode" banner or a "Sign in as" member picker, stop and tell the
team immediately.** That means the deployed app found no Supabase settings and fell back to
passwordless demo mode, so anyone on the internet can sign in as the admin. Nothing else on this
list matters until that is fixed.

## A1 — Sign-up domain (R1.1)

2. On the Sign up tab, enter a name, `someone@gmail.com` and a password twice. **Refused**, with
   the reason under the email field, and no account created.
3. Repeat with a fresh `@novasbe.pt` address. **Accepted**, and you arrive as a **Student** at
   level Beginner with the student navigation: Sessions, My bookings, Credits, Inbox.
4. Log out. On the Log in tab, enter Ana's address with a wrong password. The message is
   **"Email or password is wrong."** and names neither field.

## A2 — Booking cutoff (R3.3)

5. Log in as **Ana**. On Sessions, find a session starting in less than two hours. Its Book button
   is disabled and says why ("Booking closed").
6. A session starting later the same day is bookable.

## A3 — Last credit (R3.4, R10.7)

7. Log in as **Carla**, who has 0 credits. Try to book anything. **Refused** with "You have no
   credits left. Request a pack on the Credits page.", and the balance stays 0.

## A4 — Clash (R3.5)

8. As **Ana**, book the session tomorrow at 10:00. Then try the one at 10:30 the same day.
   **Refused**, naming the clashing time.
9. A session that starts exactly when the first one ends is accepted — back to back is allowed.

## A5 — Last place (R3.8, R4.1)

10. Find the session two days out with capacity 2 and one place taken. As **Bruno**, book it: it
    becomes full.
11. As **Diogo**, try the same session. You are told it is full and offered the waitlist. Join:
    you are **#1**, no credit is taken, and the booked count stays 2.

## A6 — Promotion with a skip (R4.3, R5.2)

12. Use the Intermediate session three days out: Carla and Diogo booked, Bruno waiting. Make sure
    Carla has **0** credits and Bruno has at least 1.
13. As **Carla**, cancel more than 24 hours before the start. Carla is refunded.
14. The freed place goes to **Bruno**, not to anyone without credits: Bruno's balance drops by 1
    and he has a booking. Check Bruno's Inbox for the notification.

## A7 — Refund window (R5.1, R5.2)

15. As **Ana**, open Cancel on a booking more than 24 hours away. The dialog states the refund
    **before** the button. Confirm: 1 credit back.
16. On a booking less than 24 hours away, the dialog warns there is **no** refund before you
    confirm. Confirm: the booking goes, the balance does not change.
17. A session that has already started cannot be cancelled at all.

## A8 — Thresholds (R6.3)

18. On Sessions, every card shows a badge that **carries the word** — Go, Marginal, No-go or
    Unknown — never colour alone, with the wave and wind numbers beside it.
19. Beginner and Intermediate sessions at the same hour may carry different labels, because the
    thresholds differ per level.

## A9 — Forecast failure (R7.4, R6.4)

20. If Open-Meteo is reachable, a card reads "Forecast updated HH:MM".
21. To see the fallback, wait for an hour when the service is down, or check a session whose
    forecast is older: the note reads "Forecast from HH:MM (live update failed)".
22. **Booking still works in both cases.** Labels advise; they never block.

## A10 — Beyond range (R6.4)

23. Find the session about nine days out. It is **Unknown**, and says the forecast will be
    available closer to the date. It is still bookable.

## A11 — Call-off (R8.3–R8.5)

24. Log in as **Tiago**. On My sessions, call off a session that has people booked, category
    **Conditions**, with a reason.
25. Every booked student is refunded, the waitlist is cleared and everyone involved gets a
    notification. Check one student's Inbox and balance.
26. Try to call the same session off again. **Nothing changes** and you are told so.

## A12 — Wrong person (R8.1, R10.5)

27. Log in as **Inês** and try to call off one of **Tiago's** sessions. **Refused** —
    "You don't have permission to do that." — and nothing changes.
28. Log in as **Ana** and try to reach Credit requests by editing the URL. **Refused**, no data
    shown.

## A13 — Credit approval (R10.2, R10.5, R10.6)

29. As **Ana**, request a 5-pack with a payment reference. One pending request appears.
30. Request a second pack. **Refused**: only one request may be pending.
31. As **Marta**, approve Ana's request. Ana's balance rises by exactly 5. Approve again if the
    button is still there: nothing changes a second time.
32. Reject another request with an **empty** note. **Refused** until you give a note.

## A14 — Session validation (R2.1–R2.7)

33. As **Tiago**, try to create a session with capacity **9**. Refused with the allowed range.
34. Try a start at **07:45**. Refused.
35. Try a start less than three hours from now. Refused.
36. Try a start that is not on a 15-minute step. Refused.
37. Create a valid session: accepted, and it appears in My sessions and on Sessions.

## A15 — Attendance unlocks Intermediate (R9.1, R3.6)

38. As **Tiago**, open Roster for a session that has **not** started. Attendance controls are not
    available yet and say when they open.
39. After a session starts, mark one student attended and one a no-show. Both save.
40. A Beginner student with fewer than 3 attended Beginner sessions is refused an Intermediate
    session, and the message says how many they have.

## A16 — Survives a restart (persistence)

41. Note Ana's balance, one booking, one waitlist place and a pending request.
42. Wait for the app to sleep, or redeploy it, then open it again. **Every one of those is
    unchanged.**

## A17 — Report numbers (R12.2–R12.6)

43. As **Marta**, open Reports and choose a period covering the seeded data. The KPI row fills in,
    and a period with no data shows "—" rather than an error.
44. Download the bookings, ledger and requests CSVs. Open one in a spreadsheet: **no cell runs as
    a formula**, and names starting with `=`, `+`, `-` or `@` are shown as text.
45. Try an end date before the start date. Refused with the reason.

## A18 — Last admin (R1.6)

46. As **Marta**, open **Members**. The seven demo accounts are listed with role, level and
    balance: Ana 3, Bruno 2, Carla 0, Diogo 2.
47. Search `ana`, then `bruno@`. Each returns only that member. Clear the box: all seven return.
48. Promote a student to instructor. **One** green message, and the table updates.
49. Click through another member and back to Marta. The role and level pickers must show
    **Marta's** values, not the member you just looked at.
50. With Marta selected, set Role to **Student** and save. **Refused** — the club would be left
    without an admin — and Marta is still an admin.

## Cross-cutting checks

51. **Times** everywhere read as Lisbon time with the weekday, for example
    "Fri 20 Nov, 10:00–11:30".
52. The **Open-Meteo credit** appears wherever conditions are shown.
53. On a **phone-width** window every page is one column with no sideways scrolling.
54. The **sidebar** shows your name and role, your credit balance if you are a student, and the
    unread count, which refreshes on its own within about ten seconds.
55. **Log out** returns you to the login page, and the back button does not get you back in.
56. No screen ever shows a stack trace. An unexpected failure shows a short message with a
    six-character reference instead.

## Known gap

The admin **Settings** screen (stretch task S08) was not built, so it is not in the navigation.
Thresholds and forecast mode use the defaults in `lineup/config.py`. The services behind that
screen exist and are tested; only the screen is missing.
