# AGENTS.md: LineUp

## Project
LineUp is a Streamlit app that books surf sessions for a campus surf club, with an Open-Meteo forecast labelling each session. Full spec: docs/product-spec.md. Shared functions and file ownership: docs/contract.md. Read the rules a task names before changing behaviour.

## Commands
- Install: uv sync
- Run the app: uv run streamlit run app.py
- Run all tests: uv run pytest -q
- Reset local demo data: uv run python scripts/seed.py

## Where code goes
- Screens: app.py and app_pages/. Only these and lineup/ui.py import streamlit.
- Rules: lineup/logic/. Pure functions only: no streamlit, sqlalchemy, httpx or clock reads; "now" is a parameter.
- Actions: lineup/services/. Load actor, check permissions, apply logic, write in ONE transaction (notifications included), return Result.
- Storage: tables only in lineup/schema.py; shared queries in lineup/db.py; lane queries in lineup/queries/<lane>.py.
- Open-Meteo: only lineup/openmeteo.py. Supabase Auth: only lineup/auth.py. Secrets: only lineup/config.py.

## File ownership
Each member edits only the files their lane owns (docs/contract.md). Shared files change only through the lead.

## Conventions
- Services never raise for expected problems; they return Result with a Code from lineup/models.py.
- Database datetimes are naive UTC; screens show Europe/Lisbon via lineup/timeutil.py.
- Money is integer cents; credits are integers.
- SQL uses SQLAlchemy Core with bound parameters; never build SQL from strings.
- Every public function has a docstring ending with "Rules: <rule ids>".
- Comments explain why, not what. No commented-out code. No TODO without a task id.
- Never use unsafe_allow_html with text a user typed. Never cache the Supabase client.

## Git
- One task = one branch named <task-id>-<slug>, created from an up-to-date main.
- Small commits: failing tests first ("test(scope): ..."), then the implementation ("feat(scope): ..."), then fixes ("fix(scope): ...").
- Stage files by name. Never use "git add ." or "git add -A".
- Before pushing, merge origin/main into the branch and rerun all tests.
- Never commit or push to main, never force-push, never merge a pull request, never rewrite pushed history.
- No AI attribution lines in commits or pull requests (no Co-Authored-By, Claude-Session or 'Generated with' lines).

## Rules for every task
- Write the task's tests first and show them failing.
- After every change run uv run pytest -q and paste the final output. The output is the proof, not a sentence.
- Never edit, delete or skip existing tests unless the task says so. If a test looks wrong, say so and stop.
- Tests never touch the network or Supabase.
- Do not add or upgrade dependencies without asking.
- Never create, read, edit or print .streamlit/secrets.toml or .env. Never write keys, passwords or connection strings anywhere.
- Never run scripts/seed.py --target live without asking first.
- When finished, list every file you changed.
