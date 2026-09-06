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

## What is built

Everything below runs locally, today, and is verified rather than asserted.

| Capability | Status |
| --- | --- |
| Engine-agnostic model client (OpenAI-compatible; Ollama today, vLLM later) | ✅ |
| Rule-based task router — reasoning / coding / vision, with an audit log | ✅ |
| Local RAG over plant documents (ChromaDB + `nomic-embed-text`), with citations | ✅ |
| Agent framework: whitelisted tools, one registry, delegation between agents | ✅ |
| Sandboxed code execution (Docker, no network, verified) | ✅ |
| Vision extraction from scanned pages and PDFs (OpenCV + `qwen2.5vl`) | ✅ |
| Real deliverables — `.docx`, `.pptx`, `.xlsx` — with download | ✅ |
| Network-isolation proof: in-process counter, OS socket monitor, pf firewall | ✅ |
| Agent trace in the UI, read back from the audit logs | ✅ |

Four local models: `qwen2.5:7b` (reasoning), `qwen2.5-coder:7b` (coding),
`qwen2.5vl:7b` (vision), `nomic-embed-text` (embeddings).

## Roadmap — not yet built

Listed so nobody mistakes an intention for a feature. **None of this exists in
the repository today.**

- **vLLM in production.** The client already speaks the protocol both engines
  implement and names neither, so this is expected to be a change to
  `MODEL_SERVER_URL` — but it has never been run against vLLM, and that claim
  is untested.
- **Authentication and RBAC.** There is no login, no user model and no
  per-role permissions. Anyone who can reach the port can use everything.
  A plant deployment needs this before it touches real data.
- **Hardware tiers.** Model choice is currently one setting for one machine.
  A real rollout wants a small tier for a laptop and a larger tier for the
  GPU server, selected by profile.
- **Concurrency.** The agent trace correlates by time window because the logs
  carry no request id; under simultaneous users a trace would collect its
  neighbours' steps. Threading a request id through every log line fixes it.
- **Vision beyond one page at a time.** PDFs are capped at five pages, and
  each page is an independent call with no cross-page reasoning.
- **Human-in-the-loop approval.** Generated documents carry a signature block,
  but nothing tracks whether anyone signed. There is no workflow state.
- **Retention and deletion policy.** Uploads are swept after an hour and
  generated files are kept indefinitely. A real deployment needs a stated
  policy, not a default.

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
│   │   ├── agents/     base_agent.py, reasoning_agent.py, coding_agent.py,
│   │   │                tool_registry.py — the only route to a tool
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

## Running the demo from a clean machine

The full sequence, assuming only Docker, Python 3.11+, Node 20+ and Ollama.
This is the only part that needs the internet.

```bash
git clone <this repo> && cd Drishti

# 1. Models (~16 GB total, once)
ollama pull qwen2.5:7b
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5vl:7b
ollama pull nomic-embed-text

# 2. Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3. Vector store from the sample SOPs
.venv/bin/python scripts/ingest_samples.py          # → 6 chunks

# 4. Sandbox image
cd .. && docker build -f Dockerfile.sandbox -t drishti-sandbox:latest .

# 5. Frontend
cd frontend && npm ci
```

Then, in three terminals:

```bash
cd backend  && .venv/bin/python -m uvicorn app.main:app --port 8000
cd frontend && npm run dev
cd backend  && .venv/bin/python scripts/traffic_monitor.py   # keep visible
```

Open <http://localhost:5173>. **From here on, nothing needs the internet** —
see [docs/air_gap_proof.md](docs/air_gap_proof.md) to prove it, and
[docs/demo_script.md](docs/demo_script.md) for the three flows to walk
through, with expected routing and timings.

Regenerate the synthetic scanned samples at any time with
`.venv/bin/python scripts/make_scanned_samples.py`.

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

## Agents

An agent is a name, a bound model, a system prompt and a **whitelist of tool
names**. It owns its turn: deciding whether to use a tool, running it, feeding
the result back to the model, and answering.

| Agent | Model | Tools |
| --- | --- | --- |
| **Reasoning Agent** | `qwen2.5:7b` | `search_knowledge_base`, `ask_coder_agent` |
| **Coder Agent** | `qwen2.5-coder:7b` | `execute_code` |
| **Vision Agent** | `qwen2.5vl:7b` | `ask_document_agent` (handoff runs on `qwen2.5:7b`) |
| **Document Agent** | `qwen2.5:7b` | the three generators |

Tool selection is **model-driven**, not keyword-matched: agents pass their tool
schemas to the OpenAI-compatible `/v1/chat/completions` endpoint and the model
decides. "What is the shutdown procedure for the FCC unit?" produces a
`search_knowledge_base` call with the query it chose; "What is the capital of
France?" produces no call at all.

### Everything goes through the registry

`app/agents/tool_registry.py` is the only route to a tool. Agents hold tool
*names*, never function references, and every invocation passes through
`call()`. That indirection buys three things that direct calls cannot:

- **one place** where every call is logged;
- **whitelist enforcement at the point of invocation** — the model picks the
  tool name, so a model reaching outside its permitted set is exactly what
  needs catching, and catching it in the caller would mean trusting the caller;
- uniform handling of malformed arguments, which are returned to the model as
  a tool result so it can correct itself rather than ending the turn.

Adding a capability means registering it here and naming it in an agent's
`allowed_tools`. There is no other way in.

### Deliverables

The workbench produces real `.docx`, `.pptx` and `.xlsx` files, not chat text
someone then retypes. All three libraries write Office Open XML locally, which
is what makes this possible with no service call.

| Tool | Produces |
| --- | --- |
| `generate_approval_note` | Word note: findings plus a signature block |
| `generate_summary_deck` | PowerPoint: title slide, one slide per section |
| `generate_calculation_sheet` | Excel: one row per step — description, formula, result |

Either the Reasoning Agent or the Vision Agent can hand off via
`ask_document_agent`. Findings travel through the **tool context**, not the
model's arguments: making a model retype a page of extracted text into a tool
call is how a measurement gets quietly reworded.

`GET /files/{filename}` serves them, restricted to `backend/data/generated/`
by two checks — the name must equal its own basename, and the resolved path
must still be inside that directory.

**Two things had to be made deterministic**, both found by running the chain
and getting a confident reply with no file:

1. **The model does not reliably call a generator.** Asked to draft an
   approval note it would reply with the text of one. The Document Agent now
   checks whether a file appeared, nudges once, and failing that builds the
   document directly from the findings in context.
2. **An artifact produced inside a delegated agent was lost.** The shared list
   was drained on emit, so a sub-agent emptied it and left its caller nothing
   to report — the file existed on disk and was never offered. Draining is
   replaced by per-level index tracking, which works at any nesting depth.

A third fix came from reading a generated file: asked for a list of strings
the model sent a list of objects, putting raw `{'description': ...}` into a
document meant to be signed. Structured arguments are now coerced to their
meaningful text.

Verified end to end — uploading the V-204 scan with *"draft an approval note
from this"* routes to the Vision Agent, delegates to the Document Agent, and
produces a 37 KB `.docx` containing **9 of 9 ground-truth details**, citing
the scan as its source, with no placeholder text.

### Reading scanned documents

Drop an image or PDF onto the upload zone and it routes to the Vision Agent.
Pages go through OpenCV first — grayscale, denoise, deskew, CLAHE, downscale —
because real inspection paperwork arrives a couple of degrees off-square and
speckled, and a vision model reads a clean page noticeably better.

Order matters in that pipeline: deskew depends on thresholding the page to
find the text, and thresholding speckle produces a cloud of false ink that
drags the angle estimate around, so denoising comes first.

The skew estimator is a projection-profile search, not `minAreaRect`. The
latter was tried and **failed silently** — on one sample scan it reported
exactly 0.00° for a visibly skewed page, and a deskew step that quietly does
nothing is worse than none. The profile method asks the question that matters:
at which rotation do the text lines align with image rows? All three samples
now correct to 0.00°.

PDFs are rendered page by page at 200 dpi via PyMuPDF and go through the same
pipeline, capped at `vision_max_pages` (5) — each page is a separate model
call on the only local GPU.

**The model had to be changed.** `llava:7b` cannot read dense documents. Given
a synthetic inspection scan it produced a *NASA equipment satisfaction report*
with handwritten remarks — none of it on the page — and hallucinated just as
confidently on a cropped three-line strip, so it is not a resolution problem
preprocessing could fix. Its encoder is built for describing photographs.
`qwen2.5vl:7b` transcribes the same scan exactly. The setting stays
configurable, but on an inspection report a fluent invention is far more
dangerous than a refusal, because a maintenance decision could be taken on it.

Measured against the V-204 sample: **12 of 12 ground-truth tokens** — tag,
inspector, badge number, all four measurements, the re-inspection interval —
with nothing invented.

```bash
ollama pull qwen2.5vl:7b
.venv/bin/python scripts/make_scanned_samples.py   # regenerate the samples
```

`vision.log` records source, page count, findings count and the deskew angles
applied — never the extracted text, which belongs in the response rather than
in a file accumulating the contents of everything ever uploaded. Uploads land
in `backend/data/uploads/` under a generated UUID name (a client filename is
never used as a path) and are swept after an hour.

### Sandboxed code execution

Code the Coder Agent writes is **always run before you see it**, in a Docker
container that is denied almost everything:

| Flag | What it denies |
| --- | --- |
| `--network=none` | No sockets. Executed code cannot become the hole in an air-gapped product. |
| `--cap-drop ALL` | No Linux capabilities to escalate with. |
| `--security-opt no-new-privileges` | A setuid binary is not a ladder to root. |
| `--read-only` | The root filesystem cannot be modified for a later run. |
| `tmpfs /tmp` (noexec, nosuid, nodev) | Scratch space that cannot be used to write and run a payload. |
| `--memory 256m` | A runaway allocation hits a wall. |
| `--pids-limit 50` | Caps process creation. |
| `user 65534` | Unprivileged even inside the container. |

Every one of these was verified rather than assumed:

```
socket to 1.1.1.1:80   → OSError: [Errno 101] Network is unreachable
DNS lookup             → gaierror
urllib fetch           → URLError
write to /usr/lib      → OSError: [Errno 30] Read-only file system
write to /tmp          → succeeds (scratch space works)
os.getuid()            → 65534
infinite loop          → killed, timed_out=True
```

`Dockerfile.sandbox` installs nothing beyond `python:3.12-slim`. Build it once:

```bash
docker build -f Dockerfile.sandbox -t drishti-sandbox:latest .
```

**Verification is deterministic, not model-driven.** `qwen2.5-coder:7b` does
not emit real tool calls — Ollama advertises the `tools` capability for it, but
it writes the tool-call JSON into its reply as text (0 real calls in 3
attempts). So the Coder Agent extracts the code the model wrote and runs it
unconditionally. That matches the requirement better than a tool call would:
code is *always* checked, not checked whenever the model remembers to ask.
Execution still goes through `tool_registry.call`, so the whitelist and the
central log entry apply exactly as for a model-initiated call.

On failure it corrects **exactly once**, then reports honestly. The limit is
enforced by the loop, not requested in the prompt — and both runs are shown in
the UI, because hiding a failed first attempt would make a retry look like a
first-time success. `tests/test_coder_correction.py` covers all four paths
with a stubbed model and a real sandbox.

### Logs hold metadata, never content

`sandbox.log` records a hash of the code, exit code, duration and output sizes
— never the code or its output. `tools.log` redacts the `code` argument the
same way, using **the same hash**, so the two entries correlate without either
file holding the content:

```
tools.log    agent=Coder Agent | tool=execute_code | args={"code": "<sha256=a84bb123…, 142 chars>"} | result=exit=0 stdout=34B
sandbox.log  sha256=a84bb123… | exit_code=0 | timed_out=False | duration=0.097s | stdout_bytes=34
```

A log that accumulates arbitrary model-written code and arbitrary program
output is a liability, not an audit trail.

### Delegation

The Reasoning Agent is instructed **not to write code**. A coding sub-question
goes to `ask_coder_agent`, which runs `CoderAgent.run()` and returns its
answer. Without that instruction the reasoning model simply answers coding
requests itself and the specialist never earns its place.

Delegation is capped at one level by an explicit depth counter, not by relying
on CoderAgent happening to have no tools today.

### Two honest limitations

**The rule-based router acts before the agent does.** A mixed request
containing the word "python" is classified as `coding` and sent straight to the
Coder Agent, so the Reasoning Agent never sees it and cannot delegate.
Delegation therefore only fires on mixed requests that do *not* trip the
coding classifier. These are two different mechanisms and the router wins
first.

**qwen2.5:7b's multi-step tool discipline is imperfect.** When the document
lookup comes first in a mixed request, the model frequently finishes the
coding part itself instead of making a second tool call — even when explicitly
instructed not to. Delegation is reliable when the coding ask comes first
(*"Build me a helper that flags an out-of-range reading. Separately, what does
the SOP say about oxygen limits?"* calls both tools). A larger model on the
GPU server should behave better; this is a model-capability limit, not a
plumbing failure.

### Audit logs

Three files under `backend/logs/`, one concern each:

```
router.log      task=reasoning | reason=no coding or vision signals matched | message="…"
tools.log       agent=Reasoning Agent | tool=ask_coder_agent | args={…} | result=delegated; 772 char reply
delegation.log  from=Reasoning Agent | to=Coder Agent | ASKED | question="…"
```

All three use `WatchedFileHandler`, so rotating or deleting a log while the
server runs does not silently send every later entry into a deleted inode.

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

Use the **Knowledge base** panel at the top of the UI: drag in a `.txt`, `.md`
or `.pdf` and it is indexed immediately, listed with its chunk count, and
citable from the next question onward. The same panel removes a document from
both the index and disk.

> **This is not the chat's upload zone.** Dropping a scan into the chat sends
> it to the Vision Agent, which reads the page once and discards it. Only the
> Knowledge base panel indexes anything.

| | Where |
| --- | --- |
| Source files | `backend/data/sample_docs/` |
| Searchable index (embeddings) | `backend/data/chroma/` |

Equivalent API and script routes:

```bash
curl -X POST http://localhost:8000/documents -F "file=@procedure.txt"
curl http://localhost:8000/documents            # list what is indexed
```

```bash
cd backend && .venv/bin/python scripts/ingest_samples.py   # rebuild from disk
```

Re-adding the same filename updates that document rather than duplicating it.
The store is gitignored; the script rebuilds it from `sample_docs/`.

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
