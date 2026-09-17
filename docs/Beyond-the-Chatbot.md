Table of Contents

# Drishti — Beyond the Chatbot: The Next Build Phase

**Purpose:** a plan for the single biggest risk left in this project — not a missing feature, but a *perception* problem. Everything below is planning only; nothing here was built for you.

* * *

## 0\. The problem, stated plainly

Walk into a judging room and open Drishti today. What a judge sees in the first ten seconds: a text box, a send button, and streaming words. That is exactly what every other team's ChatGPT\-wrapper also looks like. The fact that four different local models, a task router, a sandboxed executor, a tamper\-evident audit chain, and a real privacy\-preserving memory system are all working underneath is *true* — and *invisible*. A judge who is seeing forty projects today will not read your code. They will look at the screen for ninety seconds and form an opinion. Right now, that opinion is "another chatbot," no matter how real the engineering underneath is.

This is not a reason to distrust the engineering — Section 2 of the earlier build plan already confirmed the architecture is genuinely sophisticated and the regressions are fixed. It is a reason to recognize that **sophistication that isn't visible doesn't count in a demo.** The next build phase is not "add more backend capability" (you have plenty). It is: **make the sophistication impossible to miss, in a form a judge experiences directly rather than has to take your word for.**

Everything below is organized around one test for every proposed addition: *if a judge saw only this, for ten seconds, would they still think "chatbot"?* If the honest answer is yes, it doesn't go in this plan, however technically interesting it is.

* * *

## 1\. Why "just a chatbot" is the perception, even though it's wrong

- The only screen most of a demo lives on is the Chat panel. The Knowledge Base panel, the Audit trail, and the air\-gap badge exist, but the natural flow of a Q&A demo never has to leave the chat box.
- Every real capability — routing, delegation, RAG, sandboxing, citation verification — surfaces as *text in a chat bubble*. A sandboxed code execution and a plain LLM guess render identically to a skimming eye: some text appeared, with a code block in it.
- The demo script (as currently written) is a sequence of questions and answers. A sequence of questions and answers is the definition of a chatbot demo, regardless of what happens between question and answer.
- Nothing in the current UI is *proactive*. The system only ever responds to something typed at it. A system that only answers when spoken to reads as an assistant; a system that is visibly working, watching, or flagging things on its own reads as infrastructure.
- There is no single moment in the current flow where a judge sees multiple models, or multiple steps, or a structured model of the plant, all at once, without reading a log file.

None of this requires new backend intelligence. It requires new **surfaces** — places for the intelligence that already exists to become visible, plus a small number of specific new capabilities chosen because they are structurally incapable of looking like a chatbot.

* * *

## 2\. The four advancements that change the perception

These are ordered by how directly they defeat the "just a chatbot" reaction. Build in this order if time runs short — stop after any one of them and you already have a materially different demo than today.

### 2\.1 A visible task graph — the plan, not just the answer

This was already the top item in the existing 4\-week plan (Week 2) for architectural reasons; it is *also* the single highest\-leverage item for this problem, for a different reason: **a visible multi\-step plan is the one thing a single\-model chatbot structurally cannot produce**, because a chatbot has no notion of a plan — it has a prompt and a completion.

What to build:

- A planning step ahead of the router that, for a multi\-part request, produces an explicit ordered list of typed steps (retrieve, compute, delegate\-to\-coder, delegate\-to\-document, answer) *before* any of them run.
- A new UI element — not a chat bubble — that renders this plan as a checklist or a small flowchart, each step lighting up as it starts and getting a checkmark as it completes, live, while the answer is still being generated below it.
- The plan persists in the transcript after the turn finishes, so scrolling back through a thread shows a trail of little completed flowcharts, not just paragraphs.

Why this defeats the reaction: a judge watching a checklist populate itself, in order, with named steps, cannot describe what they're looking at as "a chatbot answering a question." They are watching a system *reason about how to reason*, which is the literal definition of what separates an agentic system from a completion API.

### 2\.2 A knowledge graph you can see, not just query

The decision to build a curated equipment\-and\-revision layer instead of GraphRAG was already right for accuracy reasons. It is *also* your best weapon against the chatbot perception, but only if it has a face.

What to build:

- The schema from the existing plan: equipment → governing procedure → revision chain → standard reference.
- A dedicated screen — a second tab alongside Chat and Audit — that renders this as an actual node\-and\-edge graph: click a piece of equipment, see its procedure, click the procedure, see its revision history and superseding versions, click a standard, see what else cites it.
- Wire chat answers about equipment/compliance questions to *highlight the relevant path through this graph* when they're given, so a judge sees the answer and the structured reasoning behind it side by side.

Why this defeats the reaction: nobody mistakes a graph explorer for a chatbot. A judge who clicks through equipment → procedure → revision chain themselves has now directly experienced "this system has modeled our plant," which is an entirely different claim than "this system can answer questions about documents."

### 2\.3 A workbench home screen, not a bare chat box

Right now the product's default, opening view is a chat box. Change what a judge sees *before they type anything*.

What to build:

- A landing/overview screen a user sees before opening a conversation: tiles showing the four models and their live status, a count of indexed documents and equipment records, a small ticker of the most recent audit events, the air\-gap badge, and — once 2.4 below exists — a count of open findings awaiting review.
- Chat becomes one panel you navigate *into*, not the whole application. The mental model shifts from "I am talking to a chatbot" to "I opened a workbench and one of its tools is a chat interface."

Why this defeats the reaction: the first screen sets the frame for everything after it. A dashboard\-first product reads as infrastructure; a chat\-first product reads as a chatbot, no matter what's on the other panels.

### 2\.4 Proactive behavior — something the system does without being asked

Every capability today is reactive: type a question, get an answer. Nothing currently happens unless a person initiates it. This is the deepest structural reason the chatbot perception is hard to shake, and it's worth building even a small, honest version of the opposite.

What to build (pick the smaller one if time is short):

- **A triggerable "compliance sweep"**\: a button (not a chat message) that runs the equipment graph against today's date, flags every piece of equipment whose governing procedure is overdue for review or has been superseded without action, and produces a findings list — without any question being typed. This can run live in the demo in a few seconds against the small sample corpus.
- **A scheduled version of the same thing**, if time allows: it runs automatically (a simple interval trigger is enough for a demo) and populates the "open findings" tile on the workbench home screen from 2.3 before anyone opens the app that day.

Why this defeats the reaction: a system that surfaces a problem before anyone asked about it cannot be described as "answering questions." It is doing something closer to what a junior engineer on the team would do — noticing things — which is a completely different pitch than a Q&A tool.

* * *

## 3\. The demo scenario that proves it, in one continuous flow

Do not demo these four things as four separate features. Stitch them into one uninterrupted story that a judge watches unfold across screens, not a list of questions and answers:

1. Open on the **workbench home screen** (2.3). Point at the four model tiles, the air\-gap badge, and the open\-findings count.
2. Click into **open findings**, produced by the **compliance sweep** (2.4) that already ran. One finding: a pressure\-vessel procedure is past its revision review date.
3. Ask Drishti to look into it. Watch the **task graph** (2.1) build live: check equipment record → check revision status → check superseding procedure → draft escalation. Each step lights up in order.
4. Click through to the **knowledge graph** (2.2) to show the actual revision chain the system just reasoned over, superseded version and all.
5. The system hands off to the Document Agent and produces a real approval/escalation note — already\-built capability, now arriving as the payoff of a chain a judge just watched form, not a standalone chat reply.
6. Close on the **audit trail**, showing every one of those steps recorded in the tamper\-evident chain, and the sovereignty badge showing zero external calls throughout.

No part of this sequence is "ask a question, get an answer, ask another question." It is a single problem discovered, investigated, and resolved by a system a judge watched *think in steps, model the plant, notice something itself, and prove nobody tampered with the record of it doing so.* That is not a chatbot demo. It does not need to be described as not a chatbot — a judge watching it will not reach for the word.

* * *

## 4\. How this reshapes the existing 4\-week plan

This does not replace the Week 2–4 plan from the existing build\-plan document — it re\-prioritizes and adds a UI dimension to the same underlying work, since the planner and the knowledge graph were already scheduled. The change is: build the *visible surface* for each capability in the same week as the capability itself, rather than treating the UI as a follow\-on.

| Week | Backend (as already planned) | New: the visible surface |
| --- | --- | --- |
| Now → Week 2 | Multi\-step planner / task\-graph ahead of the router | The live checklist/flowchart UI element (2.1) — build together, not sequentially |
| Week 3 | Equipment\-and\-revision knowledge layer \+ retrieval reranking | The graph\-explorer screen (2.2) — the schema is only worth building if it has a face |
| Week 3–4 | — (new, small addition) | The compliance\-sweep trigger (2.4) — a few hours of work once the knowledge layer exists, disproportionate payoff |
| Week 4 | Auth/RBAC, per\-user memory, concurrency, measured eval | The workbench home screen (2.3) — folds naturally into this week's UI hardening pass |

If time is genuinely short, the floor is: 2.1 (visible planner) alone. It is buildable on top of what already exists (the delegation mechanism is real; it only needs to become an explicit, displayed plan instead of an implicit tool\-call chain), and it alone is enough that a judge can no longer honestly call what they're watching a chatbot.

* * *

## 5\. What NOT to build for this reason

To keep this plan honest about trade\-offs: a few tempting additions do not belong here, because they add visual complexity without changing the "is this just a chatbot" verdict.

- **A prettier chat UI** (better bubbles, avatars, animations) — this makes the chatbot look like a *better* chatbot, which is the opposite of the goal.
- **More sample documents alone**, without the graph or the sweep — more text to retrieve from does not change what a judge sees happen on screen.
- **A settings/admin panel** — useful for the auth work in Week 4, but invisible to a judge unless they ask to see it, and not part of the story in Section 3.
- **Voice input, a mobile view, or other input\-modality additions** — these change how you talk to the chatbot, not whether it looks like one.

* * *

## 6\. The one sentence to say before the demo starts

Whatever else is said, open with a framing sentence that tells the judge what they are about to *not* see, before they can form the wrong impression themselves: *"What you're about to watch isn't a system answering questions — it's a system that noticed a compliance gap on its own, reasoned through it in steps you can watch, checked it against a live model of the plant's equipment and procedures, and produced a signed\-off deliverable — with a tamper\-evident record of every step."* Then let Section 3's flow do the rest of the work without narrating each screen as "look, not a chatbot" — the flow itself should make that argument.
