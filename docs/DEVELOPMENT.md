# Development

## Run from source

VeriClass uses [uv](https://docs.astral.sh/uv/) for Python and its packages
(`pyproject.toml`, locked in `uv.lock`), and Node 18+ for the dashboard.

```bash
./start.sh                       # the server: dashboard at /, chat at /chat, API at /api
cd dashboard && npm ci && npm run dev    # the dashboard with hot reload, at http://localhost:5173
```

`npm run dev` proxies `/api` to `http://127.0.0.1:8010` (another server:
`VERICLASS_API=http://127.0.0.1:8020 npm run dev`). Changes to `student_app/`
or `backend/` need a server restart.

The server is one process (`backend/cli.py` → `uvicorn backend.main:app`):

| Path | What |
|---|---|
| `/` | the lecturer's dashboard, built into `backend/web/` |
| `/chat/` | the students' chat (`student_app/app.py`, Chainlit, mounted with `STUDENT_CHAT_PATH`) |
| `/api/…` | the API (`backend/routes/`) |
| `/healthz` | `{"status": "ok"}` |

`API_DOCS=true` turns on the interactive API pages at `/docs`.

## Tests

```bash
uv run --frozen pytest -q             # the backend and the chat's texts
cd dashboard && npx tsc --noEmit -p . # the dashboard's types
```

Tests use a throwaway database and data folder (`tests/conftest.py`). Never
point `DB_PATH` at a real class's database while testing.

## The dashboard

React + TypeScript + Vite, with its own small design system: tokens and
classes in `dashboard/src/styles/`, building blocks in
`dashboard/src/components/ui/`, and the rules in
[dashboard/DESIGN.md](../dashboard/DESIGN.md). Strings are in English and
Hebrew (`dashboard/src/i18n.tsx`, `dashboard/src/i18n/<area>.ts`).

`npm run build` type-checks and writes the dashboard into `backend/web/`, which
is committed: lecturers run VeriClass without Node. Rebuild and commit it with
every dashboard change.

## The students' chat

`student_app/app.py` (Chainlit 2.x). Everything the chat itself says is in
`student_app/chat_texts.py`, in Hebrew and English; Chainlit's own labels are
in `.chainlit/translations/{en-US,he-IL}.json`; the look is in `public/`
(`theme.json`, logos, `vericlass-chat.css`, and `vericlass-chat.js`, which lays
Hebrew out right to left).

## Layout

```
backend/            FastAPI server
  cli.py            the `vericlass` command the start scripts run
  main.py           the app: routes, the chat mount, the dashboard
  settings.py       .env read and written by the dashboard's Settings
  tunnel.py         the students' link: cloudflared / ngrok
  routes/           the API (setup.py: first run, settings, sharing)
  agents/           drafted answers, suggested questions, grading (CrewAI)
  pacing.py, steps.py, transcript.py, review queue in routes/review.py
  web/              the built dashboard (generated)
student_app/        the students' chat
dashboard/          the lecturer's dashboard (source)
config/exercises/   the three sample exercises that ship with VeriClass
examples/           a sample package and the package format
vericlass_mcp/      MCP tools for writing exercises with a coding agent
scripts/            account and exercise helpers
tests/
```

## Settings

All settings are in `.env` (see `.env.example`, which documents each one). The
dashboard writes the provider, the API key and the chat language there; the
running server picks those up at once. Anything else needs a restart.

## Writing exercises with a coding agent

`vericlass_mcp/` is an MCP server that gives a coding agent (Claude Code or
any MCP client) tools for your own running VeriClass: create a package in
`data/drafts/`, check it (`validate_exercise`), install it (`push_exercise`,
optionally into a course or as a dated meeting), import students, and read an
anonymized class report. It authenticates with a key the server keeps in its
data folder, so it works only on the same computer.

```bash
./start.sh                      # once, so .venv exists; keep it running
bash scripts/install_mcp.sh     # registers "vericlass" with Claude Code for this folder
```

## The IDE plugin

A PyCharm plugin (the same chat in the IDE, an exam mode, a monitored
terminal) lives on the `pycharm-plugin` branch. The server here keeps the
plugin's API, and the dashboard shows the plugin's screens (exam monitoring,
terminal log, submissions) once a plugin was used with this server, or with
`PLUGIN_UI=on` in `.env`.

## Releasing

1. `cd dashboard && npm run build`, and commit `backend/web/`.
2. After changing dependencies in `pyproject.toml`: `uv lock`, then
   `uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt`.
3. The CI workflow (`.github/workflows/ci.yml`) runs the tests and a start-up
   check on Linux, macOS and Windows.
