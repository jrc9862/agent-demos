"""Decompose -> parallel subagents -> scratchpad -> synthesize.

    python coordinator.py                       parallel run
    python coordinator.py --mode sequential     one subagent at a time
    python coordinator.py --inject-timeout      office-vacancy-2025 times out
    python coordinator.py --compare             parallel then sequential, writes runs/latency.md
                                                (overwrites the plain-run parallel files)
    python coordinator.py --counter-demo        context-stripped vs full subagent prompt
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKError, CLINotFoundError,
                              ProcessError, ResultMessage, TextBlock, ToolResultBlock, ToolUseBlock,
                              query)

from fake_sources import CORPUS, FakeSources
from records import Finding, corpus_problems, parse_envelope
from report import render_report, verify_report
from scratchpad import Gap, read_findings, write_findings
from tools import MODEL, SEARCH_TOOL, build_server, load_agent

RUNS = Path(__file__).parent / "runs"
QUESTION = "How much US work is done from home, and what do hybrid schedules do to retention and office demand?"
AGENT_TOOL_NAMES = ("Agent", "Task")  # the SDK emits "Agent"; older versions emitted "Task"
DISPATCH_TIMEOUT_S = 240

# Every searcher prompt is built from this. Nothing is assumed inherited.
SUBTASK_TEMPLATE = """Research question: {question}
Your subtask: {subtask}
Assigned source ids (call search_source for each): {sources}
Topic key to put on every record from these sources: {topic}
Required output: one JSON object {{"records": [...], "errors": [...]}} exactly as your
definition specifies. Copy evidence_excerpt verbatim. Report source errors; do not fill gaps."""

COORDINATOR_PROMPT = """You coordinate a research run. You have one tool, Agent. Use subagent_type "searcher".

Question: {question}

Source catalog (id, title, topic key):
{catalog}

Steps:
1. Split the catalog into independent subtasks, one per topic key. Do not search yourself.
2. {dispatch}
3. Each Agent prompt must be this template with every field filled in. The subagent sees
   nothing else, so do not abbreviate it:
---
{template}
---
4. When all results are back, reply with the single word DONE. Do not summarize them."""

PARALLEL = ("Issue ALL Agent calls in ONE response, with run_in_background=false, so they run "
            "concurrently.")
SEQUENTIAL = ("Issue exactly ONE Agent call per response, with run_in_background=false. Wait for "
              "its result before the next call.")


@dataclass
class Collector:
    """Accumulates structured results from the message stream. No model calls."""

    records: list[Finding] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    calls: dict[str, dict] = field(default_factory=dict)  # tool_use_id -> Agent input
    per_message: list[int] = field(default_factory=list)  # Agent calls per top-level assistant message
    transcript: list[str] = field(default_factory=list)

    def feed(self, msg) -> None:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            return
        if isinstance(msg, AssistantMessage) and msg.parent_tool_use_id is None:
            n = 0
            for b in content:
                if isinstance(b, ToolUseBlock) and b.name in AGENT_TOOL_NAMES:
                    self.calls[b.id] = b.input
                    n += 1
            if n:
                self.per_message.append(n)
        for b in content:
            if isinstance(b, ToolResultBlock) and b.tool_use_id in self.calls:
                self._take(self.calls[b.tool_use_id], b)

    def _take(self, call: dict, block: ToolResultBlock) -> None:
        text = block.content if isinstance(block.content, str) else \
            " ".join(p.get("text", "") for p in (block.content or []))
        assigned = [s for s in CORPUS if s in call.get("prompt", "")]
        try:
            if block.is_error:
                raise ValueError(text[:200] or "subagent returned an error")
            env = parse_envelope(text)
        except ValueError as e:
            kind = "transient" if block.is_error else "malformed_output"
            self.gaps += [Gap(what=s, errorCategory=kind, message=str(e)) for s in assigned] or \
                [Gap(what=call.get("description", "unknown subtask"), errorCategory=kind, message=str(e))]
            return
        for r in env.records:
            bad = corpus_problems(r)
            if bad:  # fabricated or altered record: keep it out of the scratchpad, say so
                self.gaps.append(Gap(what=r.source_url, errorCategory="rejected_unverified",
                                     message="; ".join(bad)))
            else:
                self.records.append(r)
        self.gaps += [Gap(what=e.source_id, errorCategory=e.errorCategory, message=e.message)
                      for e in env.errors]


def log_message(msg, lines: list[str]) -> None:
    """Append a readable transcript line for each content block."""
    who = "subagent" if getattr(msg, "parent_tool_use_id", None) else "coordinator"
    for b in getattr(msg, "content", None) or []:
        if isinstance(b, TextBlock):
            lines.append(f"[{who}] {b.text}")
        elif isinstance(b, ToolUseBlock):
            lines.append(f"[{who}] TOOL_USE {b.name} {json.dumps(b.input)}")
        elif isinstance(b, ToolResultBlock):
            lines.append(f"[{who}] TOOL_RESULT error={b.is_error} {str(b.content)[:600]}")


def options(sources: FakeSources, **kw) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(model=MODEL, setting_sources=[], mcp_servers={"src": build_server(sources)},
                              **kw)


async def run_dispatch(question: str, mode: str, sources: FakeSources) -> tuple[Collector, float]:
    catalog = "\n".join(f"- {c['source_id']} | {c['title']} | {c['topic']}" for c in sources.catalog())
    prompt = COORDINATOR_PROMPT.format(question=question, catalog=catalog, template=SUBTASK_TEMPLATE,
                                       dispatch=PARALLEL if mode == "parallel" else SEQUENTIAL)
    opts = options(sources, tools=["Agent"], allowed_tools=["Agent", "Task", SEARCH_TOOL],
                   agents={"searcher": load_agent("searcher")}, max_turns=20)
    col, t0 = Collector(), time.monotonic()
    try:
        async with asyncio.timeout(DISPATCH_TIMEOUT_S):
            async for msg in query(prompt=prompt, options=opts):
                col.feed(msg)
                log_message(msg, col.transcript)
    except (TimeoutError, ProcessError, CLINotFoundError, ClaudeSDKError) as e:
        # Keep whatever arrived. The unanswered subtasks become coverage gaps.
        col.transcript.append(f"[coordinator] dispatch ended early: {type(e).__name__}: {e}")
        done = {g.what for g in col.gaps} | {r.source_url for r in col.records}
        col.gaps += [Gap(what=s.source_id, errorCategory="transient", message=f"{type(e).__name__}")
                     for s in CORPUS.values() if s.url not in done and s.source_id not in done]
    return col, time.monotonic() - t0


async def run_synthesis(findings: Path) -> str | None:
    prompt = (f"Use the synthesizer agent. Give it this prompt verbatim: 'Read {findings} and write "
              f"the report as your final message.' Then output the synthesizer's report unchanged.")
    opts = ClaudeAgentOptions(model=MODEL, setting_sources=[], tools=["Agent", "Read"],
                              allowed_tools=["Agent", "Task", "Read"],
                              agents={"synthesizer": load_agent("synthesizer")}, max_turns=10)
    final = None
    try:
        async for msg in query(prompt=prompt, options=opts):
            if isinstance(msg, ResultMessage) and not msg.is_error:
                final = msg.result
    except (TimeoutError, ProcessError, CLINotFoundError, ClaudeSDKError):
        return None
    return final


async def run_pipeline(mode: str = "parallel", inject_timeout: bool = False, tag: str | None = None) -> dict:
    tag = tag or ("timeout" if inject_timeout else mode)
    sources = FakeSources(failures={"office-vacancy-2025": "timeout"} if inject_timeout else {})
    col, wall = await run_dispatch(QUESTION, mode, sources)
    findings = RUNS / "findings.md"
    write_findings(findings, QUESTION, col.records, col.gaps)  # written before the synthesizer starts
    question, records, gaps = read_findings(findings)
    report = await run_synthesis(findings)
    problems = verify_report(report, records, gaps) if report else ["synthesizer returned nothing"]
    if problems:  # the model's report dropped something; ship the deterministic one and say why
        RUNS.joinpath(f"report_{tag}.synth_rejected.md").write_text(
            f"Problems: {problems}\n\n{report or ''}")
        report = render_report(question, records, gaps)
    RUNS.joinpath(f"report_{tag}.md").write_text(report)
    RUNS.joinpath(f"transcript_{tag}.txt").write_text("\n".join(col.transcript))
    log = {"mode": mode, "tag": tag, "wall_clock_s": round(wall, 1), "agent_calls": len(col.calls),
           "agent_calls_per_response": col.per_message, "max_concurrent_searches": sources.max_overlap(),
           "records": len(records), "gaps": [g.model_dump() for g in gaps],
           "synthesizer_problems": problems}
    RUNS.joinpath(f"latency_{tag}.json").write_text(json.dumps(log, indent=1))
    return log


async def compare() -> None:
    par = await run_pipeline("parallel")
    seq = await run_pipeline("sequential")
    RUNS.joinpath("latency.md").write_text(
        "| mode | dispatch wall-clock (s) | Agent calls per coordinator response | max concurrent searches |\n"
        "|---|---|---|---|\n" + "\n".join(
            f"| {r['mode']} | {r['wall_clock_s']} | {r['agent_calls_per_response']} | "
            f"{r['max_concurrent_searches']} |" for r in (par, seq)) + "\n")
    print(RUNS.joinpath("latency.md").read_text())


async def counter_demo() -> None:
    """Same searcher, same task. Once with a prompt stripped of context, once with the template."""
    stripped = "Find the numbers on that and report them."
    full = SUBTASK_TEMPLATE.format(question=QUESTION, subtask="Find the share of US paid workdays done from home",
                                   sources="wfh-research-2023, census-pulse-2025", topic="wfh_share")
    for name, sub_prompt in (("stripped", stripped), ("full", full)):
        sources = FakeSources(latency_s=0.5)
        prompt = ("Use the searcher agent exactly once. Give it this prompt verbatim, nothing added "
                  f"or removed:\n---\n{sub_prompt}\n---\nThen reply DONE.")
        opts = options(sources, tools=["Agent"], allowed_tools=["Agent", "Task", SEARCH_TOOL],
                       agents={"searcher": load_agent("searcher")}, max_turns=10)
        col = Collector()
        async for msg in query(prompt=prompt, options=opts):
            col.feed(msg)
            log_message(msg, col.transcript)
        # Collector rejects records that fail corpus checks, so those land in gaps.
        fabricated = [g for g in col.gaps if g.errorCategory == "rejected_unverified"]
        verdict = (f"records accepted: {len(col.records)}; fabricated or altered: {len(fabricated)}; "
                   f"other gaps: {len(col.gaps) - len(fabricated)}; search calls: {len(sources.calls)}")
        RUNS.joinpath(f"counter_demo_{name}.txt").write_text(
            f"PROMPT GIVEN TO SUBAGENT:\n{sub_prompt}\n\nTRANSCRIPT:\n" + "\n".join(col.transcript)
            + f"\n\nVERDICT: {verdict}\n")
        print(f"{name}: {verdict}")


def require_api_key() -> None:
    """Exit before any live run if ANTHROPIC_API_KEY is unset. The bundled CLI would
    otherwise fall back to a local Claude Code login."""
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        sys.exit("ANTHROPIC_API_KEY is not set: copy .env.example to .env and export it.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["parallel", "sequential"], default="parallel")
    ap.add_argument("--inject-timeout", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--counter-demo", action="store_true")
    a = ap.parse_args()
    require_api_key()
    if a.counter_demo:
        asyncio.run(counter_demo())
    elif a.compare:
        asyncio.run(compare())
    else:
        print(json.dumps(asyncio.run(run_pipeline(a.mode, a.inject_timeout)), indent=1))


if __name__ == "__main__":
    main()
