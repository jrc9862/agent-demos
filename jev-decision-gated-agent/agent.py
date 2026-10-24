"""LLM path: Claude Agent SDK loop over the MCP support tools, refund hook wired in.

The support agent's loop, plus `triage_facts`: an optional dict appended to the system
prompt, so the LLM does not re-derive intent,
concern count, or frustration. With `triage_facts=None` this is the LLM-does-everything baseline
(`python pipeline.py --baseline ...`).

The loop ends on the SDK's result message (the model's end_turn), not on a sentinel string.
`max_turns` is a runaway guard, not the stop condition.
"""

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKError, CLIConnectionError,
                              CLINotFoundError, ProcessError, ResultMessage, TextBlock, ToolResultBlock,
                              ToolUseBlock, UserMessage, query)

from hooks import RefundGuard, build_hooks

MODEL = "claude-opus-5-5"
HERE = Path(__file__).parent
TOOL_PREFIX = "mcp__support__"

SYSTEM_PROMPT = """You are a customer support agent for an online store. Use the support tools.

- If the customer asks for a human, call escalate_to_human immediately with a complete handoff.
  Do not attempt any resolution first.
- Use lookup_order only with an exact order ID. Without one, or if it is not found, use
  search_orders with the customer ID.
- A tool error with errorCategory "transient" means the system is unreachable. Tell the customer
  that. Never report it as "no orders found".
- Refunds above $500 need a human: call escalate_to_human.
- Never say an action happened unless a tool result confirms it.
- A message may contain several requests. Handle each, then reply once, covering all of them."""


class AgentError(Exception):
    """The LLM path failed at runtime (process failure, refusal, API error)."""


class AgentConfigError(Exception):
    """The LLM path cannot run because of configuration (no API key, no CLI). Not an AgentError:
    the pipeline must fail hard on it, not escalate a customer for an operator's mistake."""


# One guard per conversation, so the per-order total survives the revision run. The pipeline
# calls new_session() at the start of each message.
_guard = RefundGuard()


def new_session() -> RefundGuard:
    global _guard
    _guard = RefundGuard()
    return _guard


@dataclass
class AgentRun:
    reply: str
    tool_calls: list[dict] = field(default_factory=list)
    session_id: str | None = None
    cost_usd: float = 0.0
    usage: dict = field(default_factory=dict)
    latency_ms: float = 0.0


def build_options(triage_facts: dict | None = None, resume: str | None = None,
                  guard: RefundGuard | None = None) -> ClaudeAgentOptions:
    system = SYSTEM_PROMPT
    if triage_facts:
        system += ("\n\nTriage facts, decided upstream by a classifier. Treat them as given; do "
                   "not re-derive them:\n" + json.dumps(triage_facts, indent=2))
    return ClaudeAgentOptions(
        model=MODEL,
        system_prompt=system,
        mcp_servers={"support": {"type": "stdio", "command": sys.executable,
                                 "args": [str(HERE / "mcp_server.py")]}},
        tools=[],                         # no built-in Claude Code tools; MCP tools only
        allowed_tools=[TOOL_PREFIX + "*"],
        hooks=build_hooks(guard or _guard),  # always present, whatever triage said
        setting_sources=[],
        max_turns=20,
        resume=resume,
        cwd=str(HERE),
    )


def _parse_result(content) -> object:
    text = content if isinstance(content, str) else "".join(
        c.get("text", "") for c in content or [] if isinstance(c, dict))
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


async def run_agent(prompt: str, triage_facts: dict | None = None,
                    resume: str | None = None) -> AgentRun:
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        # The bundled CLI would otherwise fall back to any local Claude login. Be explicit.
        raise AgentConfigError("ANTHROPIC_API_KEY is not set")
    run, pending = AgentRun(reply=""), {}
    start = time.perf_counter()
    try:
        async for msg in query(prompt=prompt, options=build_options(triage_facts, resume)):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        pending[block.id] = {"tool": block.name.removeprefix(TOOL_PREFIX),
                                             "input": block.input}
                    elif isinstance(block, TextBlock):
                        run.reply = block.text
            elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, ToolResultBlock) and block.tool_use_id in pending:
                        call = pending.pop(block.tool_use_id)
                        call.update(result=_parse_result(block.content), is_error=bool(block.is_error))
                        run.tool_calls.append(call)
            elif isinstance(msg, ResultMessage):
                if msg.stop_reason == "refusal":
                    raise AgentError("model refused the request")
                if msg.is_error:
                    raise AgentError(f"agent run failed: {msg.subtype} {msg.errors or ''}")
                run.reply = msg.result or run.reply
                run.session_id, run.usage = msg.session_id, msg.usage or {}
                run.cost_usd = msg.total_cost_usd or 0.0
    except CLINotFoundError as err:
        raise AgentConfigError(f"Claude Code CLI not found: {err}") from err
    except CLIConnectionError as err:
        raise AgentError(f"could not connect to Claude Code CLI: {err}") from err
    except ProcessError as err:
        raise AgentError(f"agent process failed (exit {err.exit_code}): {err}") from err
    except ClaudeSDKError as err:
        raise AgentError(f"agent SDK error: {err}") from err
    run.latency_ms = (time.perf_counter() - start) * 1000
    return run


def run_agent_sync(prompt: str, triage_facts: dict | None = None, resume: str | None = None) -> AgentRun:
    return asyncio.run(run_agent(prompt, triage_facts, resume))
