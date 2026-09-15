# CLAUDE.md

## Project overview

This repo is an AI-assisted trip planner called AI Assist for Travellers.

- Frontend: Next.js + TypeScript + Tailwind in `frontend/`
- Backend: FastAPI + LangGraph orchestration in `backend/`
- Product spec: `PRD.md`
- Backend overview: `backend/README.md`
- Frontend overview: `frontend/README.md`

The app is designed around a multi-agent trip-planning pipeline:

- Agent 0: destination and best-time research
- Agent 3: itinerary generation and comparison
- Agent 4: route optimization
- Agent 1: flight search / booking
- Agent 2: hotel search / deep-link booking

The pipeline order is described in the PRD and implemented in `backend/app/orchestrator.py`.

## Repository map

- `PRD.md`: product requirements and architecture decisions
- `README.md`: root quickstart and project summary
- `backend/app/`: FastAPI app, orchestrator, shared state, agent implementations
- `backend/app/services/`: LLM, budget, flights, hotels, maps, reviews, NLU, calendar
- `frontend/app/`: Next.js app entry points
- `frontend/components/`: UI components for cards, forms, trip details
- `frontend/lib/`: API helpers and shared types

## Key technical facts

- The backend is Python and uses FastAPI with a LangGraph state machine.
- LLM use is primarily Groq/Llama 3.3 for reasoning and parsing.
- Claude/Anthropic support exists in `backend/app/services/llm.py`, but the repo notes that the Anthropic account currently has no billing credits, so Groq is the active runtime path.
- Booking flow includes human approval gates before irreversible actions.
- Search-heavy stages are parallelized; booking is intentionally kept behind a user choice.

## Local setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Run and verify

- Backend API docs: http://127.0.0.1:8000/docs
- Frontend app: http://localhost:3000

## Working conventions

- Preserve the existing orchestration structure; changes to pipeline order should be made in `backend/app/orchestrator.py`.
- Agent behavior belongs in `backend/app/agents/*.py`.
- External API logic belongs in `backend/app/services/*.py`.
- Keep the shared state contract in `backend/app/state.py` consistent when changing agent payloads.
- For changes to user-facing flow, update the relevant docs and the prompt payloads rather than changing the frontend alone.

## Important notes from project docs

- `backend/README.md` explains the pause/resume graph pattern using LangGraph interrupts.
- The app intentionally interacts the same way as a conversational planner: it emits a prompt, waits for user selection/input, then resumes the graph.
- Flight and hotel searches are modeled as joint/reconciled windows when dates are flexible.
- Hotel booking is currently deep-link based rather than full in-app checkout, because the original hotel booking APIs were not self-serve for this project.

## Default guidance for coding agents

When making changes to this repo:

1. Start by reading the relevant agent/service and the PRD section that matches the change.
2. Keep the architecture consistent with the existing LangGraph pipeline.
3. Prefer minimal, targeted changes over broad rewrites.
4. Validate behavior with the smallest relevant command or local check.
5. Do not assume the climate or pricing logic is already normalized; when working on budget logic, inspect currency handling carefully.

## Useful references

- `PRD.md`
- `README.md`
- `backend/README.md`
- `backend/app/orchestrator.py`
- `backend/app/state.py`
- `backend/app/services/llm.py`
