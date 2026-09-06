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
│   │   ├── core/       configuration (MODEL_SERVER_URL lives here)
│   │   ├── services/   model_client.py    — engine-agnostic inference client
│   │   │                router.py          — rule-based task classifier
│   │   │                knowledge_base.py  — chunking, embedding, retrieval
│   │   ├── core/       outbound.py — counts every attempted HTTP request
│   │   ├── data/       sample_docs/ (committed), chroma/ (gitignored)
│   │   └── scripts/    ingest_samples.py, traffic_monitor.py
├── scripts/            airgap_lockdown.sh, airgap_unlock.sh
├── docs/               air_gap_proof.md
│   │   └── routers/    one module per feature area; health.py, chat.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/           Vite + React + TypeScript + Tailwind + shadcn/ui
│   ├── src/
│   │   ├── assets/fonts/   self-hosted Inter & Source Serif 4 (committed)
│   │   ├── components/     Chat.tsx — streaming chat box
│   │   ├── lib/api.ts      backend client
│   │   ├── index.css       theme tokens
│   │   └── App.tsx         health-check page + chat
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

**Models** — pull them once (this is the only step that needs the internet):

```bash
ollama pull qwen2.5:7b          # reasoning
ollama pull qwen2.5-coder:7b    # coding
ollama pull nomic-embed-text    # embeddings for retrieval
```

Then build the vector store from the sample documents:

```bash
cd backend && .venv/bin/python scripts/ingest_samples.py
```

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

# Streaming chat — tokens arrive one SSE frame at a time.
curl -N -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Say hello","model":"qwen2.5:7b"}'
```

## How the pieces talk

The browser only ever calls same-origin relative paths. The Vite dev server
proxies `/api/*` to the backend (see `frontend/vite.config.ts`), so no backend
hostname is compiled into the bundle. The proxy target is `BACKEND_ORIGIN`,
which docker-compose sets to `http://backend:8000` and which defaults to
`http://127.0.0.1:8000` on a developer machine.

The backend reaches the model server at `MODEL_SERVER_URL` using `httpx`. See
**Model serving** below.

## Model serving — and swapping Ollama for vLLM

`app/services/model_client.py` talks to an **OpenAI-compatible
`/v1/chat/completions` endpoint** and nothing more specific than that. Ollama
and vLLM both implement that same contract, so the file contains no reference
to either product — not in its code, its imports, or its error messages.

Changing engines is therefore a configuration change, not a code change:

| Environment | `MODEL_SERVER_URL` |
| --- | --- |
| Mac development / demo (Ollama) | `http://localhost:11434/v1` |
| docker compose (Ollama) | `http://ollama:11434/v1` |
| MRPL GPU server (vLLM) | `http://gpu-server.internal:8000/v1` |

**vLLM is deliberately not a dependency of this repository.** It requires
NVIDIA CUDA and will not install or run on the Mac dev machines, so adding it
would break local development for everyone. It is a deployment target, not a
package: on the GPU server you run vLLM separately and point
`MODEL_SERVER_URL` at it.

### The chat endpoints

Two routes expose the same stream, because the browser's native `EventSource`
can only issue GET requests and so cannot consume a streaming POST:

- `POST /chat` — the canonical API. Body: `{"message": ..., "model": ...}`.
  Use it from curl or any client that reads a streaming response body.
- `GET /chat/stream?message=...&model=...` — the identical stream, reachable
  from `new EventSource(...)`. This is what the frontend uses.

Both delegate to one generator in `app/routers/chat.py`, so they cannot drift
apart. Frames are SSE:

```
event: routing                    ← always first: which agent was chosen, and why
data: {"delta": "some text"}      ← one per token
event: stream-error               ← the model failed mid-stream
event: done                       ← client must close(); EventSource otherwise reconnects
```

`model` is optional on both routes. Omit it and the router chooses; supply it
to override (the router still classifies, so `router.log` records what it
would have picked).

## Task routing

`app/services/router.py` picks the model before any inference happens.
`classify_task(message, has_attachment)` returns `"reasoning"`, `"coding"` or
`"vision"`, mapped to:

| Task | Model | Status |
| --- | --- | --- |
| `reasoning` | `qwen2.5:7b` | live |
| `coding` | `qwen2.5-coder:7b` | live |
| `vision` | — | recognised, not yet implemented |

**It is regular expressions, not an LLM.** Routing sits in front of every
request, so it has to be fast, and an operator asking "why did it pick that
model?" deserves a concrete answer. Rules are ordered and the first match
wins, so the logged reason names exactly the rule that fired.

The keyword list is deliberately refinery-aware, because refinery English
collides with programming English:

| Message | Routes to | Why |
| --- | --- | --- |
| "the ASME **code** requires…" | reasoning | bare "code" is not a coding signal |
| "the **function** of the reflux drum" | reasoning | bare "function" is not either |
| "**shell**-and-tube exchanger" | reasoning | "shell" is excluded entirely |
| "**rust** on the overhead line" | reasoning | "rust" is excluded entirely |
| "pump mal**function**" | reasoning | word boundaries prevent the match |
| "**fix the function** that computes reflux ratio" | coding | action verb + code noun |

Those words only trigger the coding route with programming context around
them. Every decision is appended to `backend/logs/router.log`:

```
2026-09-06 21:12:06 | INFO | task=reasoning | reason=no coding or vision signals matched | message="Summarize this SOP: operators must purge…"
2026-09-06 21:12:12 | INFO | task=coding | reason=matched programming language or library: 'python' | message="Write a python script that reads a CSV…"
```

The log is a runtime artefact and is gitignored. It records a truncated copy
of each message so a routing decision can be traced back to its input; the
file stays on the plant's own disk like everything else here.

## The system prompt

`ModelServingClient` prepends `settings.system_prompt` to every conversation
that does not already carry a system message. Users never see or set it:

> You are Drishti, an AI assistant for MRPL refinery staff. Always respond in
> English unless the user explicitly writes in another language.

The language clause is load-bearing. Qwen2.5 drifts into Chinese when a prompt
does not establish a language — "Name two products made in an oil refinery"
reliably came back in Chinese before this was added. A caller that supplies
its own system message still wins, so the default only fills a gap.

## Proving the air gap

The claim is instrumented, not asserted. Three independent layers:

1. **In-process counter** — `app/core/outbound.py` counts every HTTP request
   the backend *attempts*, split into internal and external.
   `GET /system/network-status` reports it, and the 🔒 badge in the UI polls
   it every three seconds. The badge shows local calls too, because a counter
   that only ever reads "0 external" is indistinguishable from a broken one.
2. **Operating system** — `backend/scripts/traffic_monitor.py` reads the
   kernel socket table via psutil, independently of the application.
3. **Firewall** — `scripts/airgap_lockdown.sh` loads a pf ruleset that drops
   all outbound traffic except loopback and private ranges.
   `scripts/airgap_unlock.sh` reverses it.

```bash
sudo ./scripts/airgap_lockdown.sh --duration 600   # auto-unlocks after 10 min
curl -m 5 https://google.com                       # fails
# ... use the app normally; it keeps working ...
sudo ./scripts/airgap_unlock.sh
```

**Always pass `--duration` when demoing.** The lockdown blocks the whole
machine's internet, not just Drishti's.

The full stage script, including the awkward questions and their answers, is
in [docs/air_gap_proof.md](docs/air_gap_proof.md).

## Retrieval (RAG)

Reasoning turns are grounded in a local document store before the model is
called. Nothing leaves the machine: documents are chunked, embedded through
the same local model server that serves chat, and stored in an **embedded**
ChromaDB under `backend/data/chroma/` — in-process, no vector-store server, no
port listening.

```
question → embed (nomic-embed-text) → ChromaDB cosine search
         → drop chunks above the distance threshold
         → surviving chunks go into the system message
         → model answers, citing the source
```

### Two ChromaDB defaults that had to be switched off

Both would have broken the air gap silently:

1. **Anonymised telemetry** posts usage data to PostHog. Disabled through both
   the `ANONYMIZED_TELEMETRY` environment variable (set before the import,
   since the telemetry client reads it during module init) and the `Settings`
   object.
2. **The default embedding function** downloads an ONNX model from the
   internet the first time it is called. It is unreachable here: the
   collection is created with `embedding_function=None` and every call passes
   vectors computed locally.

Verified rather than assumed — during three consecutive RAG queries the
backend process held only these sockets:

```
127.0.0.1:8000  (LISTEN)          ← inbound
127.0.0.1:*  ->  127.0.0.1:11434  ← the local model server
```

Zero non-loopback connections.

### Why answers do not cite the wrong document

Relevance is a measured threshold, not a guess. Across the sample corpus:

| | cosine distance |
| --- | --- |
| on-topic questions | 0.260 – 0.314 |
| off-topic questions | 0.518 – 0.693 |

`rag_max_distance` sits at **0.45**, in the gap. Chunks above it are dropped
before they reach either the prompt or the UI, so an unrelated question has
nothing to cite. An earlier guess of 0.55 would have let *"write a haiku about
the sea"* (0.518) cite a refinery SOP.

Coding turns are deliberately left ungrounded — an SOP corpus is noise in a
request to write a script.

### Sample documents

`backend/data/sample_docs/` holds three synthetic SOP excerpts (~450 words
each): an FCC unit shutdown procedure, pressure vessel inspection guidelines,
and a confined space entry procedure. Each opens with a banner stating it is
fictional and must not be used for actual plant operations — they read like
real procedures, and one being mistaken for an operational document is a
safety problem, not just a data-quality one. **No real MRPL data is used, and
none is needed.**

### Adding your own documents

`.txt` and `.pdf` are supported (PDF text via `pypdf`):

```python
from app.services.knowledge_base import ingest_document
await ingest_document("/path/to/procedure.pdf")
```

Re-ingesting a file replaces its chunks rather than duplicating them, so
`scripts/ingest_samples.py` is safe to re-run. The store is gitignored;
rebuild it with that script.

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
