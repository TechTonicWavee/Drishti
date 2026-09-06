# Demo script

Three flows, in order, about six minutes end to end. Every timing below was
measured on the development Mac; treat them as "normal", and see
[When it looks wrong](#when-it-looks-wrong) for what a genuine failure looks
like versus a slow model.

**The single most important timing fact:** the first request to any model
includes loading it into memory. A cold Flow B took ~18 s; the same request
with the model already warm took **2 s**. Run each flow once before the
audience arrives so nothing is loading cold on stage.

---

## Before you start

```bash
# 1. Ollama, with all four models present
ollama list          # qwen2.5:7b, qwen2.5-coder:7b, qwen2.5vl:7b, nomic-embed-text

# 2. Backend
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000

# 3. Frontend (second tab)
cd frontend && npm run dev

# 4. Network monitor — keep this terminal visible on screen
cd backend && .venv/bin/python scripts/traffic_monitor.py

# 5. Vector store, if this is a fresh machine
cd backend && .venv/bin/python scripts/ingest_samples.py    # → 6 chunks

# 6. Sandbox image, if this is a fresh machine
docker build -f Dockerfile.sandbox -t drishti-sandbox:latest .
```

Open <http://localhost:5173>. Confirm before speaking:

- the header reads **Backend connected — fully offline**
- the badge, top right, reads **🔒 Air-gapped — 0 external calls**
- Terminal 4 shows **✅ 0 EXTERNAL CONNECTIONS**

**Warm the models** by running each flow once. Then reload the page so the
transcript is clean.

---

## Optional: engage the firewall first

This makes the sovereignty claim physical rather than instrumented.

```bash
sudo ./scripts/airgap_lockdown.sh --duration 600
curl -m 5 https://google.com          # must fail
```

**Always pass `--duration`.** It blocks the whole machine's internet, not just
Drishti's, and schedules an automatic unlock. Afterwards:

```bash
sudo ./scripts/airgap_unlock.sh
```

Everything below works identically with the lockdown on. That is the point.

---

## Flow A — grounded answer from the plant's own documents

**Type exactly:**

```
What is the shutdown procedure for the FCC unit?
```

**Expected routing:** `Routed to: Reasoning Agent (qwen2.5:7b)`
**Expected timing:** ~25 s cold, ~10–15 s warm.

**What to point at, in order:**

1. The **🔧 search_knowledge_base** chip — the model chose to search; nothing
   was keyword-matched.
2. The answer, which reproduces the SOP's own numbers: 72 hours' notice,
   6 barg nitrogen, riser above 480 °C, regenerator 660–700 °C, hard limit
   730 °C.
3. **Sources** → click `fcc_unit_shutdown_procedure.txt`. It expands to the
   actual passage used. *"The citation is checkable, not just asserted."*
4. **Agent trace** → expand. `Router → Reasoning Agent`, then the tool call,
   each with a timestamp and the log file it came from.

**Then ask a question the documents do not cover:**

```
What is the capital of France?
```

It answers *Paris* with **no Sources block at all**. This is the honest half:
retrieval that cites nothing when nothing is relevant. Chunks above a measured
cosine distance of 0.45 are discarded before they reach the prompt.

---

## Flow B — sandboxed code execution

**Type exactly:**

```
Write a python script that prints the first 10 fibonacci numbers.
```

**Expected routing:** `Routed to: Coder Agent (qwen2.5-coder:7b)` — a different
model from Flow A, chosen by the rule-based router.
**Expected timing:** ~18 s cold, **~2 s warm**.

**What to point at:**

1. The **Sandboxed run** block: the code, then **Execution output** showing
   `0 1 1 2 3 5 8 13 21 34`. *"That output was produced by running the code,
   not predicted by the model."*
2. The `exit 0` chip.
3. The container is denied everything: no network, all capabilities dropped,
   read-only root, 256 MB, 50 pids, running as nobody.

**The network proof inside the sandbox** — this one lands well:

```
Write a python script that opens a socket to 1.1.1.1 on port 80 and prints CONNECTED if it succeeds.
```

The generated code runs and prints `[Errno 101] Network is unreachable`. Code
written on the fly, executed for real, and it still cannot reach the internet.

> **On self-correction:** the Coder Agent verifies its code and corrects once
> if it fails. It is now hard to trigger on demand — told the sandbox has only
> the standard library, the model rewrites around a missing package rather than
> failing. Asking for numpy usually produces a correct standard-library answer
> instead of a retry. **Do not promise a live self-correction.** If asked, show
> `backend/tests/test_coder_correction.py`, which exercises all four paths
> deterministically.

---

## Flow C — scanned report to a signed-off Word document

This is the flow to end on: it uses four models and three agents.

**Type into the chat box first:**

```
Draft an approval note from this.
```

**Then drag** `backend/data/sample_docs/scanned/vessel_v204_inspection.png`
onto the drop zone. (Type first — the upload sends whatever is in the box as
its accompanying message.)

**Expected routing:** `Routed to: Vision Agent (qwen2.5vl:7b)`
**Expected timing:** ~70 s. This is the long one. Say what is happening while
it runs — the pipeline below fills the time.

**What to point at:**

1. The scan is **deliberately degraded** — rotated ~1.75°, speckled, unevenly
   lit — because real paperwork is. Open the file beforehand to show it.
2. OpenCV deskews and denoises before the model sees it. The trace reports the
   angle it corrected.
3. **Findings (4)** and the transcription: `V-204`, `R. Menon (Badge 4471)`,
   `0.6 mm`, `300 mm`, `CML-07`, `11.4 mm` against `9.5 mm`. *"Every number
   came off the page."*
4. The **🔧 ask_document_agent** chip — the Vision Agent handed off.
5. The **deliverable card**: 📄 filename, *Word approval note · 36 KB*,
   **Download**.
6. **Download and open it.** It contains the findings, the source scan's
   filename, and a blank signature block. *"That is the deliverable — not a
   chat message someone retypes."*
7. **Agent trace** → expand. The whole chain: `Router → Vision Agent`, the
   page read, `Vision Agent → Document Agent`, the generator call, the file.

---

## Closing beat

Point at the badge: still **0 external calls**, after four models, three
agents, a sandboxed container and a generated document. Point at Terminal 4:
still **✅ 0 EXTERNAL CONNECTIONS**.

If the firewall is engaged, run `curl -m 5 https://google.com` once more and
let it fail on screen.

---

## When it looks wrong

| Symptom | Cause | What to do |
| --- | --- | --- |
| First request hangs 30–60 s | Model loading into memory | Wait. Warm the models beforehand. |
| Flow C takes >2 min | Vision model cold, or a large image | Wait; it completes. |
| Badge shows a number > 0 | Something attempted an outbound call | Real finding. `/system/network-status` names the URL. |
| Badge reads *Backend unreachable* | uvicorn died | Restart Terminal 2. |
| Answer arrives with no Sources | Nothing cleared the relevance threshold | Correct behaviour if the question is off-topic. |
| Trace is empty | Clock skew, or logs cleared mid-session | Cosmetic. The answer is unaffected. |
| Coding answer with no execution block | Model replied without a code block | Re-ask, naming Python explicitly. |
| Upload rejected | Not an accepted type | PNG, JPG, TIFF, BMP, WEBP or PDF, under 25 MB. |
| `Sandbox image is missing` | Docker image not built | `docker build -f Dockerfile.sandbox -t drishti-sandbox:latest .` |

**Recovering mid-demo:** every flow is independent. If one misbehaves, reload
the page and move to the next — nothing carries over between turns.
