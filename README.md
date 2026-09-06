# Drishti Workbench

> ## ⚠️ Do not add cloud API dependencies
>
> **Read this before writing any code in this repository — this applies to
> human contributors and to AI coding agents equally.**
>
> Drishti Workbench runs air-gapped inside a refinery network. The running
> application must make **zero external network calls**. Concretely, the
> following are forbidden anywhere in this project:
>
> - Cloud LLM SDKs or clients — `openai`, `anthropic`, `google-generativeai`,
>   `google-genai`, `cohere`, `mistralai`, `litellm`, `replicate`,
>   `langchain-openai`, Bedrock/Vertex clients.
> - Any API key, token, or cloud credential — in code, in `.env.example`, in
>   config, or in comments as a "TODO".
> - CDN-loaded assets — fonts, scripts, stylesheets, icon sets. Fonts are
>   self-hosted in [`frontend/src/assets/fonts/`](frontend/src/assets/fonts/)
>   and are committed on purpose.
> - Telemetry, analytics, crash reporting, or "phone home" update checks.
> - Runtime package installs, remote schema fetches, or remote config pulls.
>
> **All model inference goes through a locally-running Ollama instance, and
> nothing else.** If a feature seems to require an internet call, it needs a
> different design — not an exception. Installing dependencies (`pip install`,
> `npm ci`, `docker pull`) does use the network; that is setup, not runtime,
> and it is the only time this project touches the internet.

---

## What this is

Drishti Workbench is a self-hosted agentic AI workbench built for **MRPL**, an
oil refinery. It is designed to run entirely on hardware inside the plant
network, where there is no route to the public internet and where operational
data cannot legally or safely leave the premises.

This repository currently contains the project scaffold: a FastAPI backend, a
React + Vite + TypeScript frontend, and a `docker-compose.yml` that wires both
together with an Ollama service for local inference.

Built for **Smart India Hackathon**.

## Why air-gapped

Refinery process data — sensor histories, incident reports, maintenance logs,
standard operating procedures — is both safety-critical and commercially
sensitive. Sending it to a third-party inference endpoint is not acceptable to
the client, and in an isolated OT network it is not even physically possible.
Every architectural decision here follows from that constraint.

## Layout

```
drishti-workbench/
├── backend/            FastAPI + Uvicorn
│   ├── app/
│   │   ├── main.py     app factory, middleware, router registration
│   │   ├── core/       configuration
│   │   └── routers/    one module per feature area; health.py today
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/           Vite + React + TypeScript + Tailwind + shadcn/ui
│   ├── src/
│   │   ├── assets/fonts/   self-hosted Inter & Source Serif 4 (committed)
│   │   ├── lib/api.ts      backend client
│   │   ├── index.css       theme tokens
│   │   └── App.tsx         health-check page
│   └── Dockerfile
├── docker-compose.yml  backend + frontend + ollama
├── .env.example
└── README.md
```

## Running it

### Option A — docker compose (closest to the target deployment)

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: <http://localhost:5173>
- Backend:  <http://localhost:8000> (docs at `/docs`)
- Ollama:   <http://localhost:11434>

No model is pulled automatically. Pull one deliberately when you need it:

```bash
docker compose exec ollama ollama pull llama3.1:8b
```

### Option B — run the two services directly on your machine

**Backend** (Python 3.11+):

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend** (Node 20+), in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The page calls `GET /health` on load and should
show **"Backend connected — fully offline"**. If the backend is not running it
shows an explicit error state with a retry button.

### Verifying the round-trip by hand

```bash
curl http://localhost:8000/health
# {"status":"ok","offline":true}
```

## How the pieces talk

The browser only ever calls same-origin relative paths. The Vite dev server
proxies `/api/*` to the backend (see `frontend/vite.config.ts`), so no backend
hostname is compiled into the bundle. The proxy target is `BACKEND_ORIGIN`,
which docker-compose sets to `http://backend:8000` and which defaults to
`http://127.0.0.1:8000` on a developer machine.

The backend will reach Ollama at `OLLAMA_HOST` using `httpx` — that dependency
is installed now and unused until inference routes land.

## Adding a route

Create `backend/app/routers/<feature>.py` with an `APIRouter`, then include it
in `backend/app/main.py`:

```python
from app.routers import chat
app.include_router(chat.router, prefix="/chat")
```

## Adding a UI component

shadcn/ui is initialised (`frontend/components.json`); no components are
vendored yet. Add them as needed — the CLI copies source into
`src/components/ui/`, so nothing is fetched at runtime:

```bash
cd frontend && npx shadcn@latest add button
```

## Design language

A calm, editorial, paper-like interface — deliberately not a cold dark-mode
dashboard. Warm cream ground `#F5F3EE`, warm off-black ink `#2B2725`, and a
single muted rust accent `#C15F3C` used sparingly. Body text is Inter,
headings are Source Serif 4; both are variable fonts served from the app's own
bundle. Tokens live in `frontend/src/index.css`.
