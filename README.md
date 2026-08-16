# AI Assist for Travellers

- [`PRD.md`](PRD.md) — product spec (problem, agents, requirements, tech stack)
- [`backend/`](backend/README.md) — FastAPI + LangGraph agent pipeline
- [`frontend/`](frontend/README.md) — Next.js UI that drives the pipeline

## Quickstart (run both together)

**Terminal 1 — backend:**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Terminal 2 — frontend:**

```bash
cd frontend
npm install
copy .env.local.example .env.local
npm run dev
```

Then open http://localhost:3000. See each subfolder's README for the full
walkthrough (there's a scripted example matching the PRD's "vague hill
station input" case in `backend/README.md`, which the UI also exercises).
