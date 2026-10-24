# agent-demos

**Four small agent systems built with Claude. Each one defends a single architectural decision.**

Building an agent is cheap now. Deciding where enforcement lives, what a failed tool returns,
what a subagent needs to be told, and which decisions need a probability versus an `if` is not.
Each demo is self-contained: its own dependencies, offline tests, committed live output, and a
counter-demo that runs the naive approach under the same conditions.

| Demo | Decision | Tests | Committed output |
|---|---|---|---|
| [`support-agent/`](support-agent/) | Enforce the refund ceiling in a hook, not the prompt | 22 | 10 transcripts |
| [`extraction-pipeline/`](extraction-pipeline/) | Validate semantics after the schema; make absent fields nullable | 29 | 30-document batch report, counter-demo transcript |
| [`research-pipeline/`](research-pipeline/) | Give subagents their full context; return records, not prose | 20 | 4 runs with latency logs, counter-demo verdicts |
| [`jev-decision-gated-agent/`](jev-decision-gated-agent/) | Rules in code, judgments in a probability model, prose in the LLM | 107 | 13 transcripts, 60-message eval, threshold sweep |

## Quick start

```bash
git clone <this repo> && cd agent-demos/support-agent
python3 -m venv .venv && source .venv/bin/activate      # Python 3.11+
pip install -r requirements.txt
python -m pytest -q                                      # offline: fakes and mocks, no key
cp .env.example .env                                     # set ANTHROPIC_API_KEY
python agent.py --scenario refund-750                    # the hook blocks a $750 refund
```

Each folder's `README.md` lists its commands and what they produce. Live runs need the key in
the environment; nothing falls back to a Claude Code login.

---

## Demos

### [`support-agent/`](support-agent/) — Where enforcement lives

A support agent calling five backend tools over MCP, with a $500 refund ceiling enforced by a
`PreToolUse` hook in code.

```
 customer message
        │
        ▼
 ┌──────────────┐   tool call    ┌──────────────────┐  allow   ┌─────────────────┐
 │  Claude      │ ─────────────► │  PreToolUse hook │ ───────► │  MCP server     │
 │  (Agent SDK) │                │  refund > $500 ? │          │  5 tools        │
 │              │ ◄───────────── │  per-order total │ ◄─────── │  fake backend   │
 └──────────────┘  result or     └──────────────────┘  result  └─────────────────┘
        │          hook error             │                     errors carry:
        │                           deny: model never           errorCategory
        ▼                           gets a vote                 isRetryable
 reply or escalate_to_human
 (headline, reason, attempted actions, open uncertainty)
```

**Why a hook.** A prompt is a probabilistic input; compliance drifts under argument, long
conversations, or a model update. The hook runs before every tool call, whatever the model
decided. The counter-demo removes the hook, puts the rule in the prompt, and lets the customer
argue for $750 with a fake approval code.

**Rejected.** Stronger prompt language improves the odds, and odds are the problem. Validating
in the tool couples policy to the backend. A post-hoc audit catches the violation after the money
moved.

**Also here.** Tool errors carry `errorCategory` and `isRetryable`, so "the order system is
down" is never reported as "no orders exist". The MCP server flips `isRetryable` to false on the
second failure, so the retry bound does not depend on the model counting.

---

### [`extraction-pipeline/`](extraction-pipeline/) — Shape is not truth

Documents in, validated JSON out. A schema guarantees the output parses; a validator checks
whether it is true.

```
 document ──► build_params ──► messages.create ──► parse_response ──► validate
                                (strict tool,         (JSON or            │
                                 nullable fields)      NoToolCall)        │
                                       ▲                                  │
                                       │ retry: doc + failed JSON         │
                                       │        + each failing check      │
                                       └───────────── arithmetic error ◄──┤
                                                                          │
                       absent from source ──► null, no retry ◄────────────┤
                       identical output   ──► unresolvable  ◄─────────────┤
                       passes             ──► accepted      ◄─────────────┘

 bulk:  100 docs ──► Message Batches ──► round 2 resubmit ──► review_router
                     (custom_id = doc id)  (errored, retryable)   accuracy by type
                                                                  + review queue
```

**Why two stages.** The schema cannot check `subtotal + tax == total`, or whether a warranty
date exists in the document at all. Those are different failures: arithmetic responds to a retry
with the error attached; absent information responds to nothing. A nullable field lets the model
say so in one call. The counter-demo runs invoices with no warranty date through a non-nullable
schema and spends every retry.

**Rejected.** "Return null if unsure" in the prompt does not change precision; a nullable field
in the schema does. Retrying until it passes burns tokens when the data is not there. A single
aggregate accuracy hides the hard document type, so the report is stratified by type and field.

**Also here.** Batches halve cost for up to 24 hours of latency and no multi-turn tool use.
Right for an overnight corpus, wrong for a request path; the folder README does the SLA
arithmetic.

---

### [`research-pipeline/`](research-pipeline/) — Subagents start empty

A coordinator decomposes a question, fans out to parallel searchers, and synthesizes a report
that keeps its sources.

```
 research question
        │
        ▼
 ┌─────────────┐  full prompt: question, subtask,   ┌──────────────┐
 │ coordinator │  source ids, topic key, schema ───► │ searcher     │──► search_source
 │             │ ─────────────────────────────────► │ searcher     │──► search_source
 │             │ ─────────────────────────────────► │ searcher     │──► search_source
 │             │                                    └──────────────┘    (one may time out)
 │             │ ◄── Finding records, not prose ─────────┘
 │             │     {claim, evidence_excerpt, source_url, publication_date, topic, value}
 └─────────────┘
        │  write runs/findings.md
        ▼
 ┌─────────────┐          ┌──────────────┐  drops a URL,   ┌─────────────────────┐
 │ scratchpad  │ ───────► │ synthesizer  │  date, value?   │ deterministic       │
 │ findings.md │          │ (LLM prose)  │ ──────────────► │ report.py fallback  │
 └─────────────┘          └──────────────┘                 └─────────────────────┘
                                 │
                                 ▼
             report: Established / Contested / Single source / Coverage gaps
```

**Why.** A subagent does not inherit the coordinator's conversation; anything not in its prompt
does not exist. And once findings pass through prose, numbers, dates, and attribution are the
first things lost. Structured records make provenance a field instead of a sentence. The
counter-demo runs the same searcher with a stripped prompt and a full one: the stripped searcher
returns nothing and searches nothing.

**Rejected.** Sequential subagents: independent subtasks have no reason to wait, and the
`--compare` run measures it. Failing the run on one timeout: a timed-out source becomes a
"coverage gaps" section instead. Picking the newer number when sources conflict: both stay under
"contested" with dates. Silent tie-breaking is how reports lie.

---

### [`jev-decision-gated-agent/`](jev-decision-gated-agent/) — Three kinds of logic, three homes

The support agent with a decision model in front of the LLM. Rules are code, judgments are
probabilities, prose is the LLM.

```
 customer message
        │
        ▼
 ┌────────────────────┐  intent, concern_count, wants_human,
 │ triage.py  (Jev)   │  frustration, needs_llm  ── each with a probability
 └────────────────────┘
        │
        ▼
 ┌────────────────────┐   wants_human > 0.50 ──────────────────► ESCALATE
 │ gate.py  (code)    │   1 concern, calm, intent ≥ 0.80,
 │ thresholds from    │   needs_llm < 0.40 ─────────────────────► FAST PATH
 │ sweep over 60 msgs │                                           tool call + template
 └────────────────────┘                                           no LLM, never a refund
        │  everything else, or Jev outage
        ▼
 ┌────────────────────┐        ┌────────────────────┐  fail   ┌──────────────┐
 │ LLM path           │ ─────► │ verify.py  (Jev)   │ ──────► │ revise once  │
 │ tools + hooks.py   │ draft  │ answered all?      │         └──────────────┘
 │ refund > 500 = if  │        │ tone? promises?    │  pass ──► reply
 └────────────────────┘        └────────────────────┘
```

**Why.** Routing, urgency, and "did the reply answer the question" are not generative. Asking
the LLM costs a round trip each, and its self-reported confidence does not track accuracy, so no
threshold on it can be trusted. A model built to return a probability gives code something to
gate on. The eval runs Jev and the LLM on the same 60 labeled messages and commits accuracy and
calibration for both.

**Rejected.** LLM does everything: that is the `--baseline`. Jev decides the refund ceiling: it
is `amount > 500`, and nothing probabilistic belongs in front of it. Regex routing: cheap, but
silent on uncertainty, and the fallthrough from low-confidence triage to the LLM is exactly what
it cannot do.

---

## Conventions

```
<demo-name>/
├── README.md        what it is, how to run it, what each command produces
├── requirements.txt
├── .env.example
├── tests/           offline: fakes, mocked clients, no key
├── transcripts/ or runs/ or results/    committed live output
└── *.py             small enough to read in one sitting
```

- Python 3.11+, one `requirements.txt` per demo, no root package.
- Claude Agent SDK for the agents with tools and hooks; the `anthropic` SDK for single-shot
  extraction. Model `claude-opus-5-5` throughout.
- `ANTHROPIC_API_KEY` from the environment. `.env.example` committed, `.env` ignored.
- Fakes, not integrations: in-memory backends with injectable failures, so every failure demo
  is deterministic.
- Every demo has a counter-demo with committed output.
- No RAG, no persistence beyond flat files, no UI, no deployment config. Files under 300 lines.

## Adding a demo

1. Create `<demo-name>/`, kebab-case, named for the pattern.
2. Pick the one decision it defends and the counter-demo that shows the alternative.
3. Build it with offline tests and committed live output.
4. Write the folder `README.md`.
5. Add a section above: diagram, why, rejected. Under 300 words. If the argument needs more,
   it is two demos.
