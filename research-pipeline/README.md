# research-pipeline

A coordinator splits a research question into independent subtasks and dispatches searcher
subagents with every piece of context written into their prompts. Subagents return structured
records, so source, date, and number survive to the report. The coordinator writes a scratchpad
file (not transcripts) and a synthesizer reads that. One timed-out source becomes a "coverage
gaps" section instead of a failed run.

Built on the Claude Agent SDK (`claude-agent-sdk`), model `claude-opus-5-5`.

## Setup

```bash
cd research-pipeline
uv venv --python 3.12 .venv && source .venv/bin/activate   # or python3.12 -m venv .venv
uv pip install -r requirements.txt                          # or pip install -r requirements.txt
cp .env.example .env && export ANTHROPIC_API_KEY=...        # live runs only
```

The Agent SDK drives the Claude Code CLI as a subprocess; the pip package usually bundles it.
`coordinator.py` exits with a one-line message if `ANTHROPIC_API_KEY` is not set, so a run never
falls back to a local Claude Code login.

## Tests (no key, no network)

```bash
python -m pytest
```

Covers the corpus, record schema, scratchpad round trip, contested handling, coverage gaps on
timeout, and the API key guard, with canned model output.

## Commands

```bash
python coordinator.py                    # parallel dispatch, then synthesis
python coordinator.py --inject-timeout   # office-vacancy-2025 times out
python coordinator.py --compare          # parallel then sequential
python coordinator.py --counter-demo     # context-stripped vs full subagent prompt
```

| Command | Produces |
|---|---|
| plain run | `runs/findings.md` (written before synthesis), `runs/report_parallel.md` with `Established`, `Contested`, `Single source`, `Coverage gaps`, plus latency and transcript files |
| `--inject-timeout` | `runs/report_timeout.md`; `office-vacancy-2025` appears under `Coverage gaps`, the other 5 records are intact |
| `--compare` | `runs/latency.md`, and the parallel and sequential reports, latency logs, and transcripts |
| `--counter-demo` | `runs/counter_demo_stripped.txt` and `runs/counter_demo_full.txt` |

`runs/README.md` maps each file to its command. `--compare` overwrites the plain run's parallel
files and `findings.md`.

The corpus is six fictional sources in `fake_sources.py`: two disagree (28%, 22%), two agree
(33%), one can be made to time out. Under `Contested`, 28% (wfh-research-2023, 2023-01-20) and
22% (census-pulse-2025, 2025-04-02) both appear with URL and date. Neither is chosen.

If the synthesizer's report drops any record's URL, date, or value, `report.verify_report`
rejects it, the deterministic report in `report.py` is written instead, and the rejected text
is kept as `runs/report_*.synth_rejected.md`.

## Parallel vs sequential

The coordinator is told to dispatch Agent calls concurrently (parallel) or one at a time
(sequential); sequential mode is set by instruction to the coordinator, not by the runtime.
Each fake source sleeps 2s. Parallelism is measured as peak concurrent searches, computed from
timestamps in `FakeSources`, not from anything the model reports. Wall-clock includes model
turns and varies run to run.

| mode | wall-clock (s) | Agent calls per response | peak concurrent searches |
|---|---|---|---|
| parallel | 19.4 | [1, 1, 1, 1] | 2 |
| sequential | 45.6 | [1, 1, 1, 1] | 1 |

## Counter-demo: a context-stripped subagent

The same searcher runs twice: first with `Find the numbers on that and report them.`, then
with the full template (question, subtask, source ids, topic key, output format). A subagent
does not inherit the coordinator's conversation.

The harness checks every record against the corpus: the URL must exist, the date must match,
and `evidence_excerpt` must be verbatim. Records that fail are counted as fabricated. Each
output file ends in a `VERDICT:` line:

- stripped: `VERDICT: records accepted: 0; fabricated or altered: 0; other gaps: 1; search calls: 0`
- full: `VERDICT: records accepted: 2; fabricated or altered: 0; other gaps: 0; search calls: 2`

The stripped subagent returns an `invalid_input` error naming the missing question, source ids,
and topic key, and searches nothing. The full prompt returns two verified records.

## Design notes

- `Finding` has `topic` and `value` fields so code can tell which records disagree.
- The SDK names its subagent tool `Agent` (`Task` in older versions); `allowed_tools` lists both.
- `search_source` returns url, date, and passages, never page boilerplate. Subagent results
  pass through `Finding` validation before reaching the scratchpad.

## Layout

| File | Role |
|------|------|
| `coordinator.py` | prompts, dispatch, `Collector` (stream to records and gaps), CLI |
| `subagents/searcher.md`, `synthesizer.md` | subagent definitions and output schema |
| `fake_sources.py` | corpus, failure flags, call log |
| `records.py` | `Finding` schema, envelope parser, corpus check |
| `scratchpad.py` | `findings.md` writer and reader |
| `report.py` | established/contested grouping, deterministic report, report verifier |
| `tools.py` | `search_source` tool (trims to needed fields), agent-file loader |
