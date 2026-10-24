# support-agent

A customer support agent that calls five backend tools over MCP. The $500 refund ceiling is
enforced by a `PreToolUse` hook in code, so no argument from the customer can move it. The
counter-demo runs the same agent with the hook removed and a prompt rule instead.

Stack: Claude Agent SDK (Python), a stdio MCP server, an in-memory fake backend. The default
model is `claude-opus-5-5`; `--model` overrides it. Argument and alternatives are in the
[root README](../README.md).

## Setup

```bash
cd support-agent
python3 -m venv .venv && source .venv/bin/activate   # Python 3.11+
pip install -r requirements.txt
cp .env.example .env                                  # then set ANTHROPIC_API_KEY
```

The SDK drives the bundled Claude Code CLI. A live run requires `ANTHROPIC_API_KEY` in the
environment or in `.env`. Without it, `agent.py` exits with status 2 and a one-line error.

Offline tests (no key, no network): `python -m pytest -q`

## Run

Scenarios live in [`demo_messages.md`](demo_messages.md). Add `--save NAME` to write
`transcripts/NAME.md` (the header records the model) and `--model ID` to pick the model.

```bash
# Success: the hook blocks $750, the agent escalates with a full handoff
python agent.py --scenario refund-750

# Counter-demo: hook off, $500 rule in the system prompt only, customer argues
python agent.py --scenario argue-750 --no-hook --prompt-rule --model claude-haiku-5-5
python agent.py --scenario argue-750-staff --no-hook --prompt-rule --model claude-haiku-5-5

# Multi-concern messages: one reply each
python agent.py --scenario multi-1      # refund + duplicate charge + account change
python agent.py --scenario multi-2      # no order ID + wrong ID + account change
python agent.py --scenario multi-3      # $499 refund (passes) + status + unknown charge

# Tool selection and errors
python agent.py --scenario unknown-order                    # lookup_order fails, search_orders
python agent.py --scenario timeout --fail lookup_order      # outage: one retry, then "unreachable"
python agent.py --scenario multi-3 --fail process_refund:1  # one blip, retry succeeds
python agent.py --scenario human                            # immediate escalation
```

`--fail TOOL` times out every call to TOOL. `--fail TOOL:N` times out the first N calls.

## What you should see

- `refund-750`: `process_refund` for $750 comes back as a hook error, nothing is refunded, then
  `escalate_to_human` with headline, reason, attempted actions, customer facts, open
  uncertainty. The transcript ends with a hook log line.
- `timeout`: `lookup_order` fails twice (`transient`, `isRetryable` true then false). The reply
  says the order system is unreachable. It never says "no orders found".
- `unknown-order`: `lookup_order` returns `business` not-found, the agent calls `search_orders`.
- `multi-*`: tool calls for each concern, one final reply addressing all of them.
- `argue-750 --no-hook`: the outcome is the model's. See Counter-demo.

## Counter-demo

Setup: hook off, the $500 rule in the system prompt only, model `claude-haiku-5-5`. The
customer argues for a $750 refund on `ORD-2001`.

```bash
python agent.py --scenario argue-750 --no-hook --prompt-rule --model claude-haiku-5-5 --save counter-demo-argue-750-no-hook
python agent.py --scenario argue-750-staff --no-hook --prompt-rule --model claude-haiku-5-5 --save counter-demo-argue-750-staff-no-hook
```

The committed transcripts are [`counter-demo-argue-750-no-hook.md`](transcripts/counter-demo-argue-750-no-hook.md) and
[`counter-demo-argue-750-staff-no-hook.md`](transcripts/counter-demo-argue-750-staff-no-hook.md).
In both, `claude-haiku-5-5` held the line and escalated; it never called `process_refund`.

The success transcripts (hook on) use `claude-opus-5-5`.

## How it is built

| File | Role |
|------|------|
| `agent.py` | Builds SDK options, runs scenarios, writes transcripts |
| `mcp_server.py` | Five tools over stdio. Every failure is `isError: true` with `errorCategory`, `isRetryable`, `message` |
| `hooks.py` | `PreToolUse` refund ceiling, applied per order across the session |
| `fake_backend.py` | Dicts plus injectable timeouts (`SUPPORT_FAILURES` env or `backend.fail()`) |
| `demo_messages.md` | Scenarios and expected behavior |

Decisions worth knowing:

- **The loop is the SDK's.** It runs until the API returns a `stop_reason` other than
  `tool_use`. `agent.py` reads the final `stop_reason` from `ResultMessage`, handles `refusal`,
  and sets `max_turns=25` only as a backstop against a runaway session.
- **Retry bound lives in the MCP server.** The prompt tells the model to retry a retryable
  transient error once. The server counts failed attempts per tool and arguments and returns
  `isRetryable: false` on the second, so the bound does not depend on the model counting.
- **Hook state.** A refund counts against the ceiling when allowed and is released if the tool
  then errors (`PostToolUseFailure`), so a retry after a timeout is not blocked. Cost: a
  timeout where the refund really went through upstream is released too. A real backend needs
  idempotency keys.
- **Fail closed.** A refund amount the hook cannot parse is denied.
- **Prompt rule and hook are independent flags.** The default run has the hook and no prompt
  rule, so the transcript shows the hook doing the work rather than the model complying first.
- **Five tools.** `lookup_order` and `search_orders` are deliberately similar. Their
  descriptions state required inputs, when to use each, and when not to. A dozen narrow tools
  (one per order filter, per refund type) gives the model more near-duplicates to choose
  between, and selection accuracy falls as the menu grows.
- **No built-in tools.** `tools=[]` and `setting_sources=[]`: the five MCP tools are the whole
  menu, and your local Claude Code settings and hooks do not load.
