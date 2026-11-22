# LineUp design system

A calm surf look with one obvious next step per screen. **Presentation only:**
task F11 changed no service, no rule, no message and no permission. The
behaviour inventory below was written from the source *before* any edit and
checked against the diff afterwards.

## Palette

Every pair below was measured with the WCAG formula. Body text is AA or better
everywhere.

| Token | Hex | Used for | Measured |
| --- | --- | --- | --- |
| Ocean navy | `#0B2E4A` | body text, headings | **12.98:1** on sand · 13.96 on white · 12.35 on seafoam |
| Muted slate | `#4A6572` | captions | **5.75:1** on sand |
| Ocean teal | `#0E7C86` | theme primary, chips | white on teal **4.95:1** |
| Teal dark | `#0B646C` | links, focus ring | **6.39:1** on sand |
| Seafoam | `#E6F4F1` | secondary surface | — |
| Warm sand | `#FBF6EE` | page background | — |
| Sunset coral | `#FF6B57` | the one primary action | **navy on coral 4.98:1** |

**Coral buttons carry navy text, not white.** White on `#FF6B57` measures
2.80:1 and fails AA; navy measures 4.98:1 and passes. That is why the primary
button looks the way it does.

### Condition colours

The four labels keep their meanings and are darkened so the text on each tint
passes AA. **The word is always shown — colour never carries the meaning.**

| Label | Text | Background | Measured |
| --- | --- | --- | --- |
| Go | `#0F5A40` | `#DCF2E8` | **7.00:1** |
| Marginal | `#7A4E00` | `#FDF0D5` | **6.38:1** |
| No-go | `#A3201A` | `#FBE3E1` | **6.18:1** |
| Unknown | `#3F4D57` | `#E8ECEF` | **7.33:1** |

These are set through `theme.greenColor` and friends in
`.streamlit/config.toml`, so **`ui.badge()`'s code was not touched** — only its
palette.

## Typography

| Role | Face | Licence | Why |
| --- | --- | --- | --- |
| Display | **Baloo 2** | SIL Open Font License 1.1 | Rounded and warm, which suits a surf club, and still crisp at heading sizes |
| Body | **Nunito Sans** | SIL Open Font License 1.1 | Humanist with open apertures: the most legible of the candidates on a phone outdoors |

Both are **self-hosted** in `static/` as single variable `.woff2` files
(62 KB together) and declared with `[[theme.fontFaces]]`, served by
`server.enableStaticServing`. The app fetches **no remote asset**. System
fallbacks follow if a file is missing. Body text is 16 px (`baseFontSize`).

## Components

All live in `lineup/ui.py`. The seven contract functions — `get_engine`,
`current_actor`, `show_result`, `run_action`, `badge`, `plain`,
`footer_credit` — keep their names, signatures and behaviour.

| Helper | Use it for |
| --- | --- |
| `page_header(title, subtitle=None)` | The top of every screen. The subtitle goes through `plain`. |
| `card()` | One session, booking or request. Context manager over a bordered container. |
| `chip(text, kind)` / `chip_markup` | A state in words: `neutral`, `info`, `good`, `warn`, `bad`. Text escaped through `plain`; an unknown kind falls back to neutral. |
| `empty_state(message, icon)` | An empty list, using the **catalogue's own wording**. It never invents a sentence. |
| `loading(text="Paddling out…")` | Slow work. A shaka waves 3° over 1.2 s. |
| `inject_styles()` | Puts `static/lineup.css` on the page. The argument is a module constant. |
| `WAVE_SVG` | The drawn wave on the login and demo screens. |

### Rules the components follow

- **No user text in any HTML or CSS string.** `STYLES` is read from a static
  file and asserted in the tests to contain no placeholder (`{}`, `%s`).
  `WAVE_SVG` is a constant with no `http` reference.
- **Every state is named.** Chips and badges always carry their word.
- **Motion is optional.** `@media (prefers-reduced-motion: reduce)` stops the
  shaka and every other animation. The information is identical either way.
- **Focus is visible.** A 3 px teal-dark ring at 6.39:1 on all interactive
  elements.
- **One primary action per screen**, in coral. Everything else is quiet.

## Behaviour inventory

Written before any edit; the verification table below is checked against it.

| Page | Role | Primary action | Services | States |
| --- | --- | --- | --- | --- |
| Sessions | all; actions student-only | **Book** | `booking.session_cards`, `book`, `join_waitlist`, `call_off_warning`, `forecast.conditions_for_sessions` | empty, no match, disabled-with-reason, book dialog → full → waitlist, 10 s fragment, badge, footer credit |
| My bookings | student | **Cancel** | `booking.list_my_bookings`, `cancel_preview`, `cancel_booking`, `leave_waitlist`, `forecast.conditions_for_sessions` | staff notice, empty + link, refund info vs no-refund warning, waitlist, history |
| Credits | student | **Request pack** | `credits.statement`, `list_packs`, `my_requests`, `request_pack`, `withdraw_request` | balance, packs, pending + withdraw, no pending, empty statement, CSV |
| Inbox | all | **Mark all as read** | `notifications.list_notifications`, `mark_all_read` | empty, unread, button only when unread exists |
| My sessions | instructor | **Call off** on a decision | `sessions.decision_needed`, `list_my_sessions`, `create_session`, `edit_session`, `delete_session`, `call_off`, `forecast.sunset_for`, `conditions_for_sessions` | instructors only, no decisions, no upcoming, three dialogs, called off, delete only when empty, sunset line |
| Roster | instructor, admin | **Save attendance** | `attendance.roster_sessions`, `roster`, `mark_attendance`, `roster_csv`, `sessions.call_off` | no sessions, nobody booked, nobody waiting, attendance opens at, called off, nothing to save, CSV |
| Credit requests | admin | **Approve** | `credits.pending_requests`, `decided_requests`, `approve_request`, `reject_request` | pending/history tabs, both empties, reject needs a note |
| Reports | admin | period picker | `reports.kpis`, `chart_data`, three CSV exports | no data, KPI row, charts, downloads |
| Members | admin | **Save** | `members.list_members`, `change_role`, `change_level` | forbidden, no match, nothing to save |
| Login | visitor | **Log in** | `auth.sign_in`, `sign_up`, `members.login_member` | per-field errors, wrong credentials, needs confirmation |
| Shell | all | — | `members.list_demo_members`, `db.ledger_balance`, `unread_count` | **red demo banner**, empty picker, balance for students, 10 s unread fragment, log out |

## What changed, page by page

| Page | After |
| --- | --- |
| Sessions | Cards read in decision order: time range, level chip, instructor, places or "Full, n waiting", conditions, "Uses 1 credit", then a **full-width** Book |
| My bookings | The next session leads; waitlist follows; **history moved into an expander** |
| Credits | Balance leads with the request beneath it; **statement moved into an expander** |
| Inbox | Unread carries an "Unread" chip instead of a caption suffix |
| My sessions | "Needs your decision" keeps the top with Call off as its coral action; **create form moved into an expander** |
| Roster | Students and attendance come before the waitlist and the export |
| Credit requests | Pending queue leads; history stays a tab |
| Reports | Numbers lead; **downloads moved into an expander** |
| Members | Header and search above a clean table |
| Login | Wordmark, tagline and a drawn wave above the unchanged forms |
| Shell | Material icons per screen, 🤙 favicon, grouped sidebar; demo banner unchanged |

## What was verified

- **`uv run pytest -q` → 796 passed.** The 770 that existed before are
  untouched; 26 are new, for the components above.
- **Every page, every role, zero exceptions.** A throwaway `AppTest` sweep ran
  12 pages × 3 roles after each lane.
- **Services identical.** Every page's set of service calls was compared
  against `main` and matched exactly, page by page.
- **Messages, controls and states compared from the diff.** Three differences
  were found and each is a move, not a loss: the level moved from a caption to
  a chip (Sessions, My sessions); the login tagline moved into
  `page_header`'s caption; "Uses 1 credit" moved onto the card, where it had
  previously appeared only in the booking dialog.
- **Fonts and stylesheet served**: `/app/static/nunitosans.woff2`,
  `baloo2.woff2` and `lineup.css` all return 200, with no config warnings.

## Ideas needing data or rules

Out of scope for a presentation change — each needs a new field, service or
club decision, and **none was invented into the interface**:

1. **Meeting point and what to bring.** Cards have room for "Meet at the north
   steps" and a kit list, but the club has no such data. It needs a field on
   the session or a club-wide setting.
2. **A photo or map of the spot.** Ruled out deliberately: no stock photography
   and no remote images. An in-house illustration or an owned photo could be
   added to `static/`.
3. **Instructor avatars or initials.** There is no photo field, and generated
   initials would need a display-name rule for people with one name.
4. **"Sessions like this usually fill in n hours."** Needs a derived statistic
   and a rule for when the sample is too small to show.
5. **Price shown beside a credit.** Packs carry prices, but a single session
   has no price; implying one would be wrong.
6. **Weather beyond waves and wind** (water temperature, tide). Open-Meteo
   offers more, but every extra field needs a threshold rule to mean anything.
7. **A dark theme.** The palette has the contrast headroom, but every pair
   above would need re-measuring against dark surfaces.
