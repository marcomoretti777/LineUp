# docs/contract.md - shared functions every lane codes against
# Change this file only through the lead. Spec: docs/product-spec.md.

## lineup/models.py
class Code(StrEnum):  FORBIDDEN="forbidden"  INVALID="invalid"  NOT_FOUND="not_found"
    CLOSED="closed"  NOT_YET="not_yet"  NO_CREDITS="no_credits"  CLASH="clash"
    LEVEL="level"  DUPLICATE="duplicate"  FULL="full"  NOT_FULL="not_full"
    ALREADY_DONE="already_done"

@dataclass(frozen=True)
class Result:
    ok: bool
    message: str
    code: Code | None = None
    data: Any = None
    @classmethod success(cls, message, data=None) -> Result
    @classmethod fail(cls, code, message, data=None) -> Result

MESSAGES: dict[Code, str]        # one template per code, spec section 11
fill(code, **values) -> str      # MESSAGES[code].format(**values)

StrEnums (value = lower-case word):
  Role: student, instructor, admin
  Level: beginner, intermediate
  SessionStatus: scheduled, called_off
  BookingStatus: confirmed, cancelled, called_off
  Attendance: attended, no_show
  WaitStatus: waiting, promoted, left, removed, cleared
  RequestStatus: pending, approved, rejected, withdrawn
  LedgerKind: purchase, booking, refund
  CallOffCategory: conditions, instructor_unavailable, other
  Label: go, marginal, no_go, unknown

@dataclass(frozen=True) Actor(id: int, email: str, full_name: str, role: Role, level: Level)
@dataclass(frozen=True) SessionView(id: int, instructor_id: int, instructor_name: str,
    starts_at: datetime, duration_min: int, level: Level, capacity: int,
    booked_count: int, status: SessionStatus)      # property ends_at
@dataclass(frozen=True) Condition(label: Label, wave_m: float | None,
    wind_kmh: float | None, note: str)

## lineup/config.py   (values from spec section 5)
TIMEZONE="Europe/Lisbon"  LATITUDE=38.68  LONGITUDE=-9.34
EARLIEST_START=time(8,0)  FALLBACK_LATEST_END=time(17,0)  START_STEP_MIN=15
MIN_LEAD=timedelta(hours=3)  MAX_DAYS_AHEAD=14  DURATIONS=(60,90,120)
CAPACITY_MIN=1  CAPACITY_MAX=8
BOOKING_CUTOFF=timedelta(hours=2)  REFUND_WINDOW=timedelta(hours=24)
ALLOWED_EMAIL_DOMAIN="novasbe.pt"
DEFAULT_THRESHOLDS={"beginner": (1.5, 25, 2.0, 35), "intermediate": (2.5, 30, 3.0, 40)}
    # (go_wave_m, go_wind_kmh, marginal_wave_m, marginal_wind_kmh)
FORECAST_REFRESH=timedelta(minutes=60)  FORECAST_RETRY=timedelta(minutes=10)
FORECAST_STALE=timedelta(hours=12)  HTTP_TIMEOUT_S=5
CREDIT_PACKS=[("1 session", 1, 1500), ("5 sessions", 5, 6500), ("10 sessions", 10, 12000)]
get_secret(name) -> str | None          # environment first, then st.secrets
demo_mode_allowed(database_url, supabase_url) -> bool     # rule R1.7

## lineup/timeutil.py   (database = naive UTC; screens = Europe/Lisbon)
utcnow() -> datetime
to_local(dt) -> datetime                 # aware, Europe/Lisbon
from_local(day: date, clock: time) -> datetime   # naive UTC
local_date(dt) -> date
floor_hour(dt) -> datetime
fmt_dt(dt) -> str    # "Fri 20 Nov, 10:00"
fmt_time(dt) -> str  # "10:00"

## lineup/db.py   (all functions except make_engine and init_db take an open
##                 connection: `with engine.begin() as conn:`)
make_engine(url: str | None = None) -> Engine
init_db(engine) -> None      # create tables; insert packs + thresholds if empty;
                             # enable Row Level Security on Postgres
get_actor(conn, member_id) -> Actor | None
lock_member(conn, member_id) -> None        # SELECT ... FOR UPDATE on Postgres
ledger_add(conn, member_id, delta, kind, ref, note=None) -> bool
                             # False = ref already exists, nothing written
ledger_balance(conn, member_id) -> int
notify(conn, member_id, kind, message) -> None
unread_count(conn, member_id) -> int
get_session(conn, session_id) -> SessionView | None
upcoming_sessions(conn, now, days=14) -> list[SessionView]   # scheduled, by start
check_invariants(conn) -> list[str]

## lineup/permissions.py
class Action(StrEnum): VIEW_SESSIONS BOOK CANCEL_BOOKING JOIN_WAITLIST
    LEAVE_WAITLIST REQUEST_CREDITS WITHDRAW_REQUEST VIEW_STATEMENT
    READ_NOTIFICATIONS MANAGE_OWN_SESSIONS VIEW_ROSTER MARK_ATTENDANCE
    EXPORT_ROSTER CALL_OFF DECIDE_CREDITS MANAGE_MEMBERS EDIT_SETTINGS
    VIEW_REPORTS
require(actor, action, owner_id=None) -> Result | None    # None = allowed

Ownership rule: For an 'own' action, always pass owner_id. When the action creates a record for the actor, pass owner_id=actor.id. Missing owner_id is refused (fail closed).

## Cross-lane functions (the lead creates stubs; the owner replaces the body)
lineup/services/booking.py   (Member 2)
    promote_waitlist(conn, session_id, now) -> list[int]   # promoted member ids
lineup/services/forecast.py  (Member 3)
    conditions_for_sessions(engine, sessions, now=None) -> dict[int, Condition]
    sunset_for(engine, day) -> datetime | None
lineup/services/sessions.py  (Member 3)
    call_off(engine, actor_id, session_id, category, reason, now=None) -> Result

## lineup/ui.py (lead)
get_engine()  current_actor(engine) -> Actor | None
show_result(result)  run_action(fn, *args, **kwargs) -> Result | None
badge(condition)  plain(text) -> str  footer_credit()

## Service pattern (every action in every lane)
def action_name(engine, actor_id: int, ..., now: datetime | None = None) -> Result:
    now = now or utcnow()
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)          # None -> Code.NOT_FOUND
        denied = permissions.require(actor, Action.X, owner_id)
        if denied: return denied
        ... load data; ask the pure rule in lineup/logic/ ...
        ... refused -> return Result.fail(code, fill(code, ...)) ...
        ... write all changes + db.notify(...) here, same transaction ...
        return Result.success(message, data)

## tests/conftest.py (lead)
fixtures: engine (in-memory SQLite, init_db done), now = datetime(2026, 11, 20, 9, 0)
make_member(engine, role="student", level="beginner", name=None, email=None) -> int
make_session(engine, instructor_id, start, duration_min=90, capacity=4,
             level="beginner", status="scheduled") -> int
give_credits(engine, member_id, n) -> None
make_booking(engine, member_id, session_id) -> int   # charges 1 credit: give credits first
add_waiting(engine, member_id, session_id, joined_at) -> int
check_invariants runs automatically after every test that used `engine`.
Need another helper? Define it at the top of your own test file.

## File ownership
- Lead (Member 1): pyproject.toml, uv.lock, .python-version, .gitignore, AGENTS.md, CLAUDE.md, .claude/settings.json, .github/*, .streamlit/*, README.md, docs/* (except docs/lanes/), app.py, lineup/config.py, lineup/models.py, lineup/timeutil.py, lineup/permissions.py, lineup/schema.py, lineup/db.py, lineup/ui.py, lineup/auth.py, lineup/logic/accounts.py, lineup/services/members.py, app_pages/login.py, app_pages/admin_members.py, scripts/seed.py, tests/conftest.py, tests/test_smoke.py, tests/test_core_types.py, tests/test_permissions.py, tests/test_db_core.py, tests/test_persistence.py, tests/test_accounts.py, tests/test_members.py, tests/test_seed.py, tests/test_scenarios.py
- Member 2: Booking: lineup/logic/booking.py, lineup/services/booking.py, lineup/queries/booking.py, app_pages/sessions.py, app_pages/my_bookings.py, tests/test_booking_rules.py, tests/test_booking.py, tests/test_cancellation.py, tests/test_waitlist.py, tests/test_booking_views.py, docs/lanes/booking.md
- Member 3: Sessions and forecast: lineup/logic/sessions.py, lineup/logic/conditions.py, lineup/openmeteo.py, lineup/services/sessions.py, lineup/services/forecast.py, lineup/queries/sessions.py, lineup/queries/forecast.py, app_pages/instructor_sessions.py, app_pages/admin_settings.py, tests/test_session_rules.py, tests/test_sessions.py, tests/test_openmeteo.py, tests/test_conditions.py, tests/test_forecast.py, tests/test_call_off.py, tests/fixtures/*, docs/lanes/sessions-forecast.md
- Member 4: Credits and reports: lineup/logic/credits.py, lineup/logic/reports.py, lineup/services/credits.py, lineup/services/notifications.py, lineup/services/attendance.py, lineup/services/reports.py, lineup/queries/credits.py, lineup/queries/reports.py, app_pages/credits.py, app_pages/inbox.py, app_pages/roster.py, app_pages/admin_requests.py, app_pages/admin_reports.py, tests/test_credit_rules.py, tests/test_credits.py, tests/test_notifications.py, tests/test_attendance.py, tests/test_reports.py, docs/lanes/credits-reports.md
