# Speaking Portuguese: what a language toggle would take

LineUp is a Lisbon surf club and most of its members speak Portuguese, so a
language toggle is the most obvious next feature. It was scoped on 23 Nov 2026
and deliberately **not** built before submission: the work touches every lane's
files, and a half-translated app reads worse than a consistent English one.

This note records the measurement and the design so it can be built properly.

## The measurement

Counted on commit `0f3abc7`, not estimated.

| Surface | Strings | Where | Owner |
| --- | --- | --- | --- |
| Widget labels, headers, buttons, captions | **139** | `app_pages/*.py`, `app.py` | all four lanes |
| Messages built inside services | **93** | `lineup/services/*.py` | Members 2, 3, 4 |
| The message catalogue | **13** | `lineup/models.py` `MESSAGES` | lead |
| Refusal reasons from pure rules | ~14 | `lineup/logic/*.py` | Members 2, 3, 4 |
| **Total** | **~250** | | |

Two further surfaces are easy to miss:

- **Dates are English.** `timeutil.fmt_dt` produces `"Fri 20 Nov, 10:00"` with
  `strftime`, whose weekday and month names follow the C locale, not the app
  language. Portuguese needs its own name tables — `locale.setlocale` is
  process-global and unsafe in a threaded Streamlit server.
- **41 test assertions read the English wording**, across nine test files.
  They assert on `result.message`, not only on `Code`.

## Why it is not a small change

`docs/contract.md` says services return a `Result` carrying a **finished
sentence**. The wording is built where the action happens:

```python
return Result.success(
    f"Booked: {fmt_dt(session.starts_at)}. {left} credits left. "
    f"Free cancellation until {fmt_dt(deadline)}."
)
```

So translating the app means touching `lineup/services/booking.py`,
`sessions.py`, `credits.py`, `attendance.py` and `notifications.py` — files
owned by three other members. That is the real cost, not the vocabulary.

## The design

### 1. Move wording out of the services

Services should return a **key and its values**, not a sentence:

```python
return Result.success(Msg.BOOKED, {"when": ..., "left": ..., "until": ...})
```

`Result.message` becomes a property that renders the key in the current
language. This is the only structural change, and it is worth making on its
own merits: it is what `MESSAGES` already does for refusals (`fill(code, …)`),
extended to successes. Every lane keeps ownership of *which* key its service
returns; the translations live in one place.

### 2. One catalogue module

`lineup/i18n.py`, owned by the lead, with no Streamlit import so logic and
services can use it:

```python
LANGUAGES = {"en": "English", "pt": "Português"}
def t(key: str, lang: str, **values) -> str
def fmt_dt(dt, lang) -> str          # Portuguese weekday and month tables
```

Catalogues as plain dictionaries, `en` and `pt`, with the **same key set** — a
test should fail if either language is missing a key, which is the cheapest
guard against a half-translation.

### 3. The toggle

A `st.segmented_control` in the sidebar beside the member's name, stored in
`st.session_state["lang"]` and defaulting to `pt` once the translation is
complete. `ui.show_result`, `ui.page_header`, `ui.chip` and `ui.empty_state`
read it, so most pages change only where they hold a literal.

Storing it per session is enough; a `language` column on `members` would make
it stick across devices and is a later refinement.

### 4. Dates

Add Portuguese weekday and month tables to `lineup/timeutil.py` and give
`fmt_dt`/`fmt_time` a `lang` argument defaulting to English. Never
`locale.setlocale`: it is global to the process and two members browsing in
different languages would fight over it.

### 5. Tests

- Both catalogues expose the same keys.
- Every `Code` has a Portuguese message.
- `fmt_dt` renders a known date correctly in both languages.
- The 41 assertions on English wording move to asserting on the **key**, which
  is what they should have asserted on all along. `docs/contract.md` already
  says "Tests check `code`, never the wording".

## Order of work

1. `lineup/i18n.py` with both catalogues and the key-parity test. **Lead, no
   other lane affected.**
2. `timeutil` date names. **Lead.**
3. `Result` carries a key; `MESSAGES` moves into the catalogue. **Lead, but it
   changes a shared contract, so it needs every lane's agreement first.**
4. Each lane converts its own services to return keys. **One pull request per
   lane, reviewed by its owner.**
5. The pages, lane by lane.
6. The toggle, and `pt` becomes the default.

Steps 1 and 2 are independent and safe. Step 3 is the one that needs the team
in a room, because it changes `docs/contract.md`.

## What it is worth

Most members read Portuguese more comfortably than English, and the words that
matter most are the refusals — "Too late: booking closed at 08:00" is exactly
where a misunderstanding costs someone a session. That argues for translating
the **message catalogue first**, before any page chrome: it is 13 strings and
the highest value per string in the app.
