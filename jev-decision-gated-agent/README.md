# jev-decision-gated-agent

The support agent with TypeSafe AI's Jev in front of the LLM: Jev answers typed questions
(intent among nine, request count, wants a human, frustration, needs an LLM, did the draft
hold up), `gate.py` applies thresholds in code, and the LLM only calls tools and writes prose. The refund ceiling stays an `if` in `hooks.py`, and the eval measures whether Jev's
confidence tracks accuracy better than the LLM's self-reported confidence on the same messages.

## Layout

| File | Role |
|------|------|
| `triage.py` | One `system_one` call, five questions (intent has a definition and contrast per option), returns `TriageResult` |
| `gate.py` | Threshold constants, `decide()` / `route()`, decision log |
| `verify.py` | Second `system_one` call on every LLM draft, three checks |
| `pipeline.py` | Orchestration and CLI: escalate, fast path, or LLM + verify; `--baseline` |
| `fast_paths.py` | The six fast-path handlers: tool call plus template |
| `agent.py`, `hooks.py`, `mcp_server.py`, `fake_backend.py` | The support agent (see Notes) |
| `templates.py`, `jev_client.py` | Fast-path replies and policy text; Jev client (`--fake-jev` swaps in a fake) |
| `eval/` | 60 labeled messages, `run_eval.py`, `sweep_thresholds.py`, `results/` |

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env    # set ANTHROPIC_API_KEY and TYPESAFE_API_KEY
```
The LLM path needs `ANTHROPIC_API_KEY` in the environment, so every logged cost maps to that key.

## Run

```bash
python pipeline.py "Where is order 48213?"
python pipeline.py --customer C001 "I want to talk to a person"
python pipeline.py --customer C001 "Please change my shipping address to 77 Elm St, Boise ID."
python pipeline.py --customer C001 "How do I return the socks for a refund?"
python pipeline.py --customer C001 "I can't log in, it says my password is wrong."
python pipeline.py --customer C001 "Can I get an invoice for my last purchase for my expense report?"
python pipeline.py --customer C003 "Did my refund for order 49555 go through?"   # on record
python pipeline.py --customer C001 "Did my refund for order 48377 go through?"   # none
python pipeline.py --customer C001 "I want a refund for order 48377 and please also update my shipping address to 9 Oak Ln."
python pipeline.py --customer C002 'Refund $750 on order 51877 now.'

# Baseline: LLM does everything (no triage, no verify)
python pipeline.py --baseline --customer C001 "I want a refund for order 48377 and please also update my shipping address to 9 Oak Ln."

# Failure injection; fake Jev (no TypeSafe key, uncalibrated)
FAKE_BACKEND_FAIL=lookup_order:timeout python pipeline.py "Where is order 48213?"
python pipeline.py --fake-jev "Where is order 48213?"
```

Each run prints the route, triage probabilities, tool calls, verify rounds, reply, latency, and
cost. Every decision is appended to `logs/decisions.jsonl`: a `route` entry (all probabilities,
thresholds, template), `verify` entries, and an `outcome` entry with `path` (`fast` plus
`template`, `llm`, `llm+verify`, `llm+verify+revise`, `llm+unverified`, `escalate`),
`latency_ms`, `llm_cost_usd`, and `jev_cost_usd` (input tokens at $0.042/Mtok).

## Eval
```bash
python eval/run_eval.py              # Jev and LLM; writes eval/results/calibration_<ts>.md
python eval/run_eval.py --no-llm     # Jev only (also --no-jev; --fake-jev prints, writes nothing)
python eval/sweep_thresholds.py      # threshold sweep from cached probabilities (--refresh: 60 Jev calls)
python -m pytest -q                  # network-free: fake Jev, scripted agent, mocked Anthropic
```

Results: `eval/results/`; run transcripts: `transcripts/`. On 60 messages and nine intents, Jev scores 96.7% / 100% / 96.7% on intent, wants_human and
concern_count; the LLM scores 93.3% / 100% / 100%. Expected calibration error (lower is better)
is Jev 0.044 / 0.028 / 0.031 against the LLM's 0.113 / 0.035 / 0.086. Live, fast paths take
229 to 782 ms and cost about $0.00005; the same kind of message through the LLM path takes 8.8 s
and $0.0101.

## Fast paths

A fast path needs one concern, no anger, and `needs_llm` and intent confidence on the right side
of threshold. None calls `process_refund`.

| Intent | Tool call | Template |
|--------|-----------|----------|
| `order_status` | `lookup_order` on the named order; with no order ID the message goes to the LLM | status, carrier, tracking, ETA |
| `account_change` | `escalate_to_human` with headline, requested change, customer ID | account changes are made by the team, plus the ticket |
| `return_how` | none | 30-day window, how to start, prepaid label by email |
| `login_help` | none | password reset steps |
| `invoice_request` | `search_orders`, newest order | the order and its `invoice_id` |
| `refund_status` | `lookup_order` on the named order | the refund on record (ID, amount, date); with none, says so, then `escalate_to_human` |

`order_status` and `refund_status` also need an order ID in the message (`gate.decide`).
Another customer's order, a missing customer ID, or a failed handoff falls through to the LLM path.

## Thresholds

| Constant | Value | Rule |
|----------|-------|------|
| `WANTS_HUMAN_ESCALATE` | 0.50 | `wants_human > 0.50` escalates before any resolution |
| `INTENT_CONFIDENCE_MIN` | 0.80 | `intent.confidence < 0.80` goes to the LLM path |
| `NEEDS_LLM_FAST_MAX` | 0.40 | a fast path needs `needs_llm < 0.40` |
| verify cutoffs | 0.5 | `addresses_all_concerns` and `tone_matches_frustration` fail below 0.5; `promises_unconfirmed` fails at 0.5 or above |

`eval/sweep_thresholds.py` sets the first three from the 60 labeled messages: it scores 1,800
combinations through `gate.decide` and keeps the one with the most non-LLM routing and zero
misroutes, breaking ties by the widest margin to the nearest message probability that would
flip a route. A wrong fast path is any fast route whose label intent differs from the template
taken, has several concerns, wants a human, or is labeled `template_ok: false` (the template's
fixed facts do not fully answer it). At these values 23.3% of messages take a fast path, 13.3%
escalate, and 63.3% go to the LLM path, with no wrong fast
path, no wrong escalation and no missed escalation.

Messages of 60 per template: `order_status` 5, `account_change` 5, `login_help` 2,
`return_how` 1, `invoice_request` 1, `refund_status` 0.

The gate reads Jev's Choice `.confidence` (how concentrated the distribution is). The eval's
calibration table uses the probability Jev gave its chosen answer (`probabilities[choice]`,
`max(p, 1-p)` for a Noul, the argmax level for a Score), the only quantity comparable with
accuracy and with the LLM's self-reported number.

## Failure modes

- **Jev outage during triage:** `triage_error` is logged and the LLM path runs with no triage
  facts. The refund hook still applies.
- **Jev outage during verify:** the reply goes out unverified, flagged by a `verify_error` log
  entry and outcome `path` `llm+unverified`. No escalation: an outage should not page humans.
- **`ANTHROPIC_API_KEY` or the Claude Code CLI missing:** `pipeline.py` exits non-zero and
  creates no ticket. Runtime LLM failures escalate with "LLM path unavailable".
- **No `session_id` to resume a revision:** escalates.

## What you should see

- `"Where is order 48213?"`: `FAST_PATH`, template `order_status`, one `lookup_order`, `llm_calls=0`.
- `"I want to talk to a person"`: `ESCALATE` with a structured handoff, no other tool call.
- The address change: template `account_change`, one `escalate_to_human`, a ticket in the reply.
- The return, login and invoice messages: `return_how`, `login_help` (no tool call) and
  `invoice_request` (`INV-48213`), all `llm_calls=0`.
- Refund status: order 49555 reports refund R0912; order 48377 has none and opens a ticket.
- Refund + address, the vague message, an angry order-status message: `LLM_PATH`.
- The $750 refund is never issued; an unconfirmed-refund draft is revised once.

## Notes

- `agent.py`, `hooks.py`, `mcp_server.py`, and `fake_backend.py` are the support agent's five
  tools, fake backend, and refund hook; `hooks.py` holds the cumulative `RefundGuard`.
- The fake Jev (`--fake-jev`) tests routing, not Jev; the eval never saves its output.
