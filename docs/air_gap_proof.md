# Proving the air gap, live

This document is for a judge, a teammate, or anyone who reasonably declines to
take "it's air-gapped" on trust. It sets out how to check the claim on stage
in about two minutes.

The claim under test:

> While Drishti Workbench is running, it makes no network connection to
> anything outside this machine. All inference, retrieval and storage happen
> locally.

## Why there are three separate checks

One measurement is easy to fake. These three are independent, sit at different
layers, and would have to agree in order to be wrong together:

| Layer | What it observes | Where it lives |
| --- | --- | --- |
| **1. Application counter** | Every HTTP request the backend *attempts* | Inside the process — `app/core/outbound.py` |
| **2. Operating system** | The kernel's actual socket table | Outside the process — `scripts/traffic_monitor.py` |
| **3. Firewall** | Packets permitted to leave the host at all | Below both — `pf`, via `scripts/airgap_lockdown.sh` |

Layer 1 is the badge in the UI. Layer 2 is a terminal reading the OS, which
does not trust the application. Layer 3 makes the question moot: even a
deliberate attempt to phone home is dropped by the kernel.

An honest limit, stated up front: layer 1 counts requests made through the
HTTP clients the application creates. It would not see a third-party library
opening a raw socket. That is exactly why layers 2 and 3 exist — they cannot
be bypassed from inside the code.

## Setting up the stage

Three terminals and a browser. Start these before the audience arrives.

**Terminal 1 — the app**

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000
cd frontend && npm run dev          # in another tab
```

**Terminal 2 — the live network monitor (keep this visible)**

```bash
cd backend && .venv/bin/python scripts/traffic_monitor.py
```

It refreshes every two seconds and shows every socket the backend holds:

```
──────────────────────────────────────────────────────────────
 DRISHTI WORKBENCH — LIVE NETWORK MONITOR      21:37:03
 backend pid 13185  ·  port 8000  ·  via psutil
──────────────────────────────────────────────────────────────
  LOCAL                  REMOTE                 STATE        SCOPE
  127.0.0.1:54979        127.0.0.1:11434        ESTABLISHED  internal
  127.0.0.1:8000         127.0.0.1:54977        ESTABLISHED  internal
  127.0.0.1:8000         -                      LISTEN       internal
──────────────────────────────────────────────────────────────
  ✅  0 EXTERNAL CONNECTIONS — all traffic is loopback or private
──────────────────────────────────────────────────────────────
```

**Terminal 3 — for the live curl test.**

**Browser** — <http://localhost:5173>, with the 🔒 badge visible top-right.

## The demonstration

### 1. Engage the lockdown

```bash
sudo ./scripts/airgap_lockdown.sh --duration 600
```

`--duration 600` schedules an automatic unlock after ten minutes. Use it. This
blocks the whole machine's internet, not just Drishti's, and a demo laptop
that stays cut off after the session is a bad afternoon.

The script prints exactly what it allows: loopback, `10/8`, `172.16/12`,
`192.168/16`, `169.254/16` and the IPv6 local ranges. Everything else
outbound is dropped. The rules are commented line by line in the script if
anyone wants to read them.

### 2. Show that the internet is genuinely gone

```bash
curl -m 5 https://google.com
```

Expected: it fails. `curl: (28) Connection timed out` or
`curl: (7) Failed to connect`. Nothing renders.

This is the moment worth pausing on. The machine now has no route off itself.

### 3. Use the app normally

With the internet demonstrably gone, in the browser:

- Ask **"What is the shutdown procedure for the FCC unit?"** — it answers from
  the sample SOP and cites `fcc_unit_shutdown_procedure.txt` under **Sources**.
- Ask **"Write a python script that reads a CSV and prints the max."** — the
  badge above the answer switches to the **Coding Agent**, a different local
  model.

Both work. The reasoning model, the coding model, the embedding model and the
vector store are all on this machine.

### 4. Point at the two counters

- The **🔒 badge** reads `0 external calls`, with a local count that climbs as
  you use the app. That climbing number matters: it shows the counter is live
  rather than hardcoded.
- **Terminal 2** shows connections only to `127.0.0.1:11434` — the local model
  server — and `✅ 0 EXTERNAL CONNECTIONS`.

The application says zero. The operating system independently agrees.

### 5. Release the lockdown

```bash
sudo ./scripts/airgap_unlock.sh
curl -m 5 -o /dev/null -s -w '%{http_code}\n' https://google.com   # 200
```

The unlock restores `/etc/pf.conf` and returns `pf` to whichever state it was
in before — enabled or disabled — rather than assuming.

## Questions you should expect

**"Could it be caching answers from an earlier online session?"**
No. Ollama loads model weights from local disk and runs inference on this
CPU/GPU. Ask something no cache could hold — a question about the specific
sample SOPs, or a fresh coding problem — and watch tokens stream in at the
speed of local generation.

**"Are there API keys hidden somewhere?"**
There is no cloud client to authenticate to. `backend/requirements.txt` has no
`openai`, `anthropic`, `google-generativeai`, `cohere`, `litellm` or Bedrock
package, and carries an explicit deny-list. `.env.example` has one variable,
`MODEL_SERVER_URL`, pointing at localhost. `grep -ri "api_key" backend/app`
returns only a comment explaining why there isn't one.

**"What about the frontend — fonts, analytics, a CDN?"**
Inter and Source Serif 4 are committed to the repo as `.woff2` files and
served from the app's own bundle. A DevTools capture of a full page load plus
a chat turn records 18 requests, all to localhost. There is no analytics
script.

**"ChromaDB has telemetry."**
It does, and it is switched off deliberately — via both the environment
variable and the `Settings` object, because the two are read at different
points during start-up. Its default embedding function, which downloads a
model from the internet on first call, is never reachable either: the
collection is created with `embedding_function=None` and every vector is
computed locally. This was verified by watching sockets during RAG queries,
not by reading the documentation.

**"Will this work on the real deployment?"**
The plant server runs Linux with NVIDIA GPUs, where the equivalent lockdown is
an `iptables` policy rather than `pf`, and inference moves from Ollama to vLLM.
That swap is one environment variable — `MODEL_SERVER_URL` — because the
client speaks the OpenAI-compatible protocol both engines implement, and names
neither of them in its code.

## If something looks wrong

If the badge ever shows a non-zero external count, it turns red and records
the URL and timestamp of the last attempt, readable at
<http://localhost:8000/system/network-status>. That is a real finding, not a
display bug — it means something in the process tried to reach the outside
world, and the URL says what.
