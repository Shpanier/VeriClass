# OS Lab — Instructor-Controlled LLM (MVP)

Locally-hosted LLM system for the Intro to Operating Systems course. Students chat
with a local LLM about exercise `ex3-mcalc`; the instructor sees their activity in
real time and can push variant-targeted questions that the student must answer
before continuing.

The repo ships with a built-in demo exercise (`ex3-mcalc`, 8 variants) so the
system is usable the moment it's installed — zero configuration.

## Components

| # | Component        | Stack                      | Port  |
|---|------------------|----------------------------|-------|
| 1 | Local LLM        | Ollama + `qwen2.5-coder:7b`| 11434 |
| 2 | Cloud LLM        | Gemini 2.5 Pro (via API)   | —     |
| 3 | Backend          | FastAPI + SQLite           | 8000  |
| 4 | Student app      | Chainlit                   | 8001  |
| 5 | Instructor dash  | React + Vite + TypeScript  | 5173  |

## Quick start

```bash
# 1. Install Ollama and pull the model (one time)

# 2. Python deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Set the cloud LLM key
cp .env.example .env
# edit .env and set GEMINI_API_KEY

# 4. Seed students for the pilot
python scripts/add_students.py --names "Yossi Cohen,Shira Levi,Ahmed Alyan"

| Name                     | Login code |
|--------------------------|------------|
| Yossi Cohen              | STU1-XXXX   |
| Shira Levi               | STU2-XXXX   |
| Ahmed Alyan              | STU3-XXXX   |

# 5. Run the three processes (separate terminals)
uvicorn backend.main:app --reload --port 8000
chainlit run student_app/app.py --port 8001
cd dashboard && npm install && npm run dev
```

Students go to `http://localhost:8001`, instructor to `http://localhost:5173`.

## Layout

```
config/
  exercises/ex3-mcalc.yaml   # the demo exercise + 8 variants
  cloud_llm.yaml             # provider: gemini | openai | anthropic
  instructors.yaml.example   # copy to instructors.yaml and edit
backend/                     # FastAPI app
student_app/                 # Chainlit
dashboard/                   # React + TS
scripts/add_students.py      # CLI to seed login codes
```

## Privacy

Student chat traffic never leaves the local network. The only egress is the
instructor's `/api/probe/suggest` call to the cloud LLM, with all PII stripped
by `backend/sanitize.py` before sending. Every cloud call is logged in
`api_audit_log` with token counts and latency.
