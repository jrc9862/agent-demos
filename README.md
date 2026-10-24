# agent-demos

**Four small agent systems built with Claude, each one a worked example of an architectural
decision and the reasoning behind it.**

Coding agents have made building an agent system cheap. Deciding what to build has not gotten
cheaper. Where does enforcement live? What does a tool return when it fails? What does a
subagent need to be told? Which decisions need a probability and which need an `if`? Those are
the questions that separate a demo that works once from a system that works on Tuesday.

The code is the evidence. The argument is below. Each demo is self-contained, with its own
dependencies, run instructions, offline tests, committed live output, and a counter-demo that
runs the naive approach under the same conditions.

| Demo | Decision | Tests | Committed output |
|---|---|---|---|
| [`support-agent/`](support-agent/) | Enforce the refund ceiling in a hook, not the prompt | 22 | 10 transcripts |
| [`extraction-pipeline/`](extraction-pipeline/) | Validate semantics after the schema; make absent fields nullable | 29 | 30-document batch report, counter-demo transcript |
| [`research-pipeline/`](research-pipeline/) | Give subagents their full context; return records, not prose | 20 | 4 runs with latency logs, counter-demo verdicts |
| [`jev-decision-gated-agent/`](jev-decision-gated-agent/) | Rules in code, judgments in a probability model, prose in the LLM | 107 | 13 transcripts, 60-message eval, threshold sweep |

## Quick start

```bash
git clone <this repo> && cd agent-demos/support-agent
python3 -m venv .venv && source .venv/bin/activate      # Python 3.11+; uv venv also works
pip install -r requirements.txt
python -m pytest -q                                      # offline: fakes and mocks, no key
cp .env.example .env                                     # set ANTHROPIC_API_KEY
python agent.py --scenario refund-750                    # the hook blocks a $750 refund
```

Every folder's `README.md` lists its commands and what each produces. Live runs require the key
in the environment; the demos do not fall back to a Claude Code login.

---

## Demos

### [`support-agent/`](support-agent/) — Where enforcement lives

A customer support agent calling backend tools over MCP, with a hard refund ceiling.

**The decision.** The $500 refund limit is enforced by a hook that intercepts the tool call in
code, not by an instruction in the system prompt.

**Why.** A prompt is a probabilistic input. Under adversarial pressure, a long conversation, or a
model update, compliance drifts. A hook runs every time, before the tool executes, and the model
never gets a vote. The counter-demo runs the same agent with the hook removed and the rule in the
prompt only, against a customer who argues for $750 with a fake approval code and a fake policy
change. The transcripts show what the model did; the hook's guarantee does not depend on it.

**Alternatives rejected.**
- *Stronger prompt language.* Improves the odds. Odds are the problem.
- *Validate in the tool itself.* Works, but couples the policy to the backend. The hook keeps
  policy in the agent layer where it can change without touching the tool.
- *Post-hoc audit.* Catches the violation after the money moved.

**Other decisions in this demo.** Tool errors carry `errorCategory` and `isRetryable` so the
agent can tell "the order system is down" from "no orders exist" and never report one as the
other. The retry bound lives in the MCP server, which flips `isRetryable` to false on the second
failure, so it does not depend on the model counting. The hook tracks a per-order cumulative
total, denies amounts it cannot parse, and releases an amount when the refund call fails, so a
retry after a timeout is not blocked. Tool count is held at five because selection accuracy
degrades as the menu grows, and two of the five are deliberately similar to show that
descriptions, not names, drive selection.

---

### [`extraction-pipeline/`](extraction-pipeline/) — Shape is not truth

Documents in, validated JSON out, at scale, with human review where it is needed.

**The decision.** Schema-constrained output via tool use is the first stage, not the last. A
validator checks semantics, retries carry the specific error back to the model, and fields that
are absent from the source are nullable so the model is never asked to invent them.

**Why.** A JSON schema guarantees the output parses and has the right fields. It does not
guarantee `subtotal + tax == total`, or that a warranty date exists in the document at all. The
two failure classes need different fixes: arithmetic errors respond to a retry with the error
attached; absent information does not respond to any number of retries. Treating them the same
burns tokens. The counter-demo runs invoices with no warranty date through a
non-nullable schema: every retry is spent. The pipeline returns `null` in one call.

**Alternatives rejected.**
- *Prompt the model to "be careful" and "return null if unsure."* Vague instructions do not
  change precision. A nullable field in the schema does.
- *Retry until it passes.* Spends every retry when the data is not there.
- *Trust aggregate accuracy.* The report breaks down by document type and field, and
  low-confidence fields route to review, so a weak type or field is visible on its own row.

**Other decisions in this demo.** The bulk path uses the Message Batches API, which halves cost
in exchange for up to 24 hours of latency and no multi-turn tool use. That trade is right for an
overnight corpus and wrong for anything on a request path; the demo states the SLA arithmetic.
`strict: true` on the tool holds the schema with `tool_choice: auto`. Field descriptions pin the
output form where a value has more than one spelling.

---

### [`research-pipeline/`](research-pipeline/) — Subagents start empty

A coordinator decomposes a research question, fans out to parallel subagents, and synthesizes a
report that keeps its sources.

**The decision.** Every subagent prompt carries its full context explicitly. Subagents return
structured records (`claim`, `evidence_excerpt`, `source_url`, `publication_date`), never prose.
The coordinator writes findings to a scratchpad file before handing off to synthesis.

**Why.** A subagent does not inherit the coordinator's conversation. It sees only its prompt.
Anything not in the prompt does not exist. And once findings pass through a prose summary,
numbers, dates, and attribution are the first things lost. By the time a synthesizer writes the
report, "one source said 40%, another said 55%, published two years apart" has become "roughly
half." Structured records make provenance a field instead of a sentence, so it survives.

**Alternatives rejected.**
- *Shared conversation across agents.* Not how the runtime works. The counter-demo runs the same
  searcher with a context-stripped prompt and a full one, and checks every record it returns
  against the corpus.
- *Sequential subagents for simplicity.* Independent subtasks have no reason to wait on each
  other. Parallel dispatch is measured against sequential by wall-clock and by peak concurrent
  searches taken from source timestamps.
- *Fail the run if any subagent fails.* One timeout produces a report with a "coverage gaps"
  section, not no report.
- *Pick the more recent number when sources conflict.* The synthesizer keeps both, with dates
  and attribution, under "contested." Silent tie-breaking is how reports lie. If the
  synthesizer's prose drops a URL, date, or value, a deterministic report is written instead.

---

### [`jev-decision-gated-agent/`](jev-decision-gated-agent/) — Three kinds of logic, three homes

The support agent again, with a decision model in front of the LLM.

**The decision.** Triage, routing, escalation scoring, and reply verification are made by
TypeSafe AI's Jev, a System One model that returns typed answers with probabilities. Code
applies the thresholds. The LLM calls tools and writes prose. The refund ceiling stays an `if`.

**Why.** An agent is full of decisions that are not generative: which team, how urgent, does
this need a human, did the reply answer the question. Making the LLM answer them costs a full
round trip each, and asking it "how confident are you" yields a number that does not track
accuracy, so no threshold on it can be trusted. A model built to return a probability gives
code something it can gate on. And once rules, judgments, and generation are split, each can be
tested, tuned, and swapped on its own.

**Alternatives rejected.**
- *LLM does everything.* The baseline. The eval runs both on the same 60 labeled messages and
  commits accuracy and calibration tables for each.
- *Jev decides the refund ceiling too.* It is `amount > 500`. Nothing probabilistic belongs in
  front of it.
- *Regex and keyword routing.* Cheap, but brittle on phrasing and silent on uncertainty. The
  fallthrough from low-confidence triage to the full LLM path is what keyword routing cannot do.

**Other decisions in this demo.** One fan-out call asks all triage questions at once. Six
intents have fast paths: a tool call and a template, or a direct handoff, with no LLM. Only
single-concern messages from a calm customer qualify, and no fast path moves money. Thresholds
come from a sweep over the labeled messages that maximizes non-LLM routing with zero misroutes.
Every decision is logged with its probabilities. A Jev outage falls through to the LLM.

---

## Conventions

Every demo folder follows the same shape.

```
<demo-name>/
├── README.md        what it is, how to run it, what each command produces
├── requirements.txt
├── .env.example
├── tests/           offline: fakes, mocked clients, no key
├── transcripts/ or runs/ or results/    committed live output
└── *.py             small enough to read in one sitting
```

- **Python 3.11+**, one `requirements.txt` per demo. No root-level package.
- **Claude Agent SDK** for the three agents with tools and hooks; the **`anthropic` SDK**
  directly for single-shot extraction. Model `claude-opus-5-5` throughout, with
  `claude-haiku-5-5` for the support agent's counter-demo.
- **`ANTHROPIC_API_KEY`** from the environment, required for live runs. `.env.example`
  committed, `.env` ignored at every depth.
- **Fakes, not integrations.** Backends and sources are in-memory Python with injectable failure
  flags, so every failure demo is deterministic and reproducible on demand.
- **Every demo includes a counter-demo.** The naive approach, run under the same conditions,
  output committed.
- **Offline tests pass without a key.** They cover the deterministic parts: hooks, validators,
  routers, schemas, fakes.
- **No RAG, no persistence beyond flat files, no UI, no auth, no deployment config.** If it does
  not demonstrate the decision, it does not belong.
- **Files under 300 lines.** Split or cut. Generated data files are exempt.

## Adding a demo

1. Create `<demo-name>/`, kebab-case, named for the pattern.
2. Decide the one thing the demo exists to defend, and the counter-demo that shows the
   alternative under the same conditions.
3. Build it, with offline tests and committed live output.
4. Write the folder `README.md`: what it is, how to run it, what each command produces.
5. Add a section above: the decision, why, alternatives rejected. Keep it under 300 words. If
   the argument needs more than that, the demo is probably two demos.
