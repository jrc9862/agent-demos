"""Support agent: Claude Agent SDK, MCP tools over stdio, refund ceiling in a hook.

    python agent.py --scenario refund-750                      # hook on
    python agent.py --scenario refund-750 --model claude-haiku-5-5
    python agent.py --scenario argue-750 --no-hook --prompt-rule   # counter-demo
    python agent.py --scenario timeout --fail lookup_order     # injected outage
    python agent.py --message "Hi, dana@example.com ..."       # free text

The agentic loop is the SDK's. It sends, runs tools, and continues until the API
returns a stop_reason other than tool_use. This file never inspects text to decide
when to stop. It reads the final stop_reason from ResultMessage and reports it.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, CLIConnectionError,
    CLIJSONDecodeError, CLINotFoundError, ProcessError, ResultMessage, TextBlock,
    ToolResultBlock, ToolUseBlock, UserMessage,
)
from dotenv import load_dotenv

from hooks import RefundGuard, build_hooks

HERE = Path(__file__).parent
DEFAULT_MODEL = "claude-opus-5-5"
SAFETY_MAX_TURNS = 25  # backstop against a runaway session, not the stop condition

SYSTEM_PROMPT = """\
You are a customer support agent for an online electronics store. You resolve returns,
billing questions, and account issues using the support tools. Today is 2026-10-09.

Tool selection:
- Identify the customer first with get_customer (email is usually in the message).
- Use lookup_order only when the customer gave an exact order ID. If it returns not-found,
  or the customer gave no ID, use search_orders with their customer_id.
- Escalate with escalate_to_human for anything no tool can do (account or contact changes).

Tool errors are JSON with errorCategory, isRetryable, message:
- transient and isRetryable true: call the same tool once more.
- transient and isRetryable false: stop. Tell the customer the system is unreachable and to
  try again later. Never describe an outage as "no orders found" and never guess a result.
- business, validation, permission: do not retry. Explain it to the customer plainly.

A message may bundle several concerns. Handle every one, then send a single reply covering
all of them. If the customer asks for a human, call escalate_to_human immediately with no
other resolution attempts. Handoffs must stand alone: the human sees only the handoff.
State only facts that tool results returned.
"""

PROMPT_RULE = """
Refund policy: never issue a refund above $500. Refunds above $500 must go to a human.
"""


class AgentConfigError(Exception):
    """A live run cannot start because of configuration (no API key)."""


def require_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        # The bundled CLI would otherwise fall back to any local Claude Code login.
        raise AgentConfigError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and set it.")


def load_scenarios() -> dict[str, list[str]]:
    """demo_messages.md: `## id` sections, each with one or more ```turn blocks."""
    text = (HERE / "demo_messages.md").read_text()
    out: dict[str, list[str]] = {}
    for m in re.finditer(r"^## (\S+)\n(.*?)(?=^## |\Z)", text, re.S | re.M):
        turns = re.findall(r"```turn\n(.*?)```", m.group(2), re.S)
        if turns:
            out[m.group(1)] = [" ".join(t.split()) for t in turns]
    return out


def failure_env(specs: list[str]) -> str:
    """`lookup_order` -> always times out; `lookup_order:1` -> first call only."""
    parts = []
    for s in specs:
        tool, _, n = s.partition(":")
        parts.append(f"{tool}=timeout" + (f":{n}" if n else ""))
    return ",".join(parts)


def build_options(hook: bool, prompt_rule: bool, fail: list[str], guard: RefundGuard,
                  model: str = DEFAULT_MODEL) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=model,
        system_prompt=SYSTEM_PROMPT + (PROMPT_RULE if prompt_rule else ""),
        mcp_servers={"support": {
            "command": sys.executable,
            "args": [str(HERE / "mcp_server.py")],
            "env": {"SUPPORT_FAILURES": failure_env(fail)},
        }},
        strict_mcp_config=True,
        allowed_tools=["mcp__support__*"],
        tools=[],                # no built-in tools: the five MCP tools are the whole menu
        setting_sources=[],      # ignore user/project settings and their hooks
        hooks=build_hooks(guard) if hook else None,
        max_turns=SAFETY_MAX_TURNS,
    )


class Transcript:
    def __init__(self, title: str, meta: dict[str, str]):
        self.lines = [f"# {title}", ""] + [f"- {k}: {v}" for k, v in meta.items()] + [""]

    def add(self, text: str = "") -> None:
        self.lines.append(text)
        print(text)

    def render(self) -> str:
        return "\n".join(self.lines) + "\n"


def short(content) -> str:
    if isinstance(content, list):
        content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return str(content)


async def run_turn(client: ClaudeSDKClient, user_text: str, tr: Transcript) -> ResultMessage | None:
    tr.add(f"## User\n\n{user_text}\n")
    await client.query(user_text)
    result = None
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock) and b.text.strip():
                    tr.add(f"## Agent\n\n{b.text.strip()}\n")
                elif isinstance(b, ToolUseBlock):
                    tr.add(f"**tool call** `{b.name.removeprefix('mcp__support__')}` `{b.input}`\n")
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for b in msg.content:
                if isinstance(b, ToolResultBlock):
                    tag = "tool error" if b.is_error else "tool result"
                    tr.add(f"**{tag}** `{short(b.content)}`\n")
        elif isinstance(msg, ResultMessage):
            result = msg
    return result


async def run(turns: list[str], opts: ClaudeAgentOptions, tr: Transcript, guard: RefundGuard) -> None:
    async with ClaudeSDKClient(options=opts) as client:
        for text in turns:
            result = await run_turn(client, text, tr)
            if result is None:
                tr.add("**no result message received**")
                return
            tr.add(f"_stop_reason={result.stop_reason} subtype={result.subtype} "
                   f"turns={result.num_turns}_\n")
            if result.stop_reason == "refusal":
                tr.add("**model refused; ending session**")
                return
            if result.is_error or result.subtype != "success":
                tr.add(f"**session ended abnormally** terminal_reason={result.terminal_reason} "
                       f"errors={result.errors}")
                return
    if guard.blocked:
        tr.add("## Hook log\n")
        for b in guard.blocked:
            tr.add(f"- blocked `{b['order_id']}`: {b['why']}")
        tr.add("")


def main() -> int:
    load_dotenv(HERE / ".env")
    load_dotenv(HERE.parent / ".env")
    scenarios = load_scenarios()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", choices=sorted(scenarios))
    ap.add_argument("--message", help="free-text single-turn message instead of a scenario")
    ap.add_argument("--no-hook", action="store_true", help="disable the refund hook (counter-demo)")
    ap.add_argument("--prompt-rule", action="store_true", help="add the $500 rule to the system prompt")
    ap.add_argument("--fail", action="append", default=[], metavar="TOOL[:N]",
                    help="inject timeouts: every call, or the first N calls")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="model id (default: %(default)s)")
    ap.add_argument("--save", metavar="NAME", help="write transcripts/NAME.md")
    args = ap.parse_args()
    if bool(args.scenario) == bool(args.message):
        ap.error("give exactly one of --scenario or --message")

    try:
        require_api_key()
    except AgentConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    guard = RefundGuard()
    opts = build_options(not args.no_hook, args.prompt_rule, args.fail, guard, args.model)
    turns = scenarios[args.scenario] if args.scenario else [args.message]
    tr = Transcript(args.scenario or "free-text", {
        "model": args.model, "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "refund hook": "off" if args.no_hook else "on",
        "prompt rule ($500)": "on" if args.prompt_rule else "off",
        "injected failures": failure_env(args.fail) or "none",
    })
    try:
        asyncio.run(run(turns, opts, tr, guard))
    except CLINotFoundError:
        print("Claude Code CLI not found. It ships with claude-agent-sdk; reinstall requirements.", file=sys.stderr)
        return 2
    except CLIConnectionError as e:
        print(f"Could not start or reach the Claude Code process: {e}", file=sys.stderr)
        return 2
    except ProcessError as e:
        print(f"Claude Code process failed (exit {e.exit_code}): {e}", file=sys.stderr)
        return 2
    except CLIJSONDecodeError as e:
        print(f"Malformed output from the Claude Code process: {e}", file=sys.stderr)
        return 2
    if args.save:  # only reached after a completed run, so no half-transcripts on failure
        out = HERE / "transcripts" / f"{args.save}.md"
        out.write_text(tr.render())
        print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
