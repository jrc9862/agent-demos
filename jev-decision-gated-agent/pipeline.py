"""Triage -> gate -> (escalate | fast path | LLM path + verify). Also runs the baseline.

    python pipeline.py --fake-jev "Where is order 48213?"
    python pipeline.py --customer C002 "Refund order 51877 and update my address"
    python pipeline.py --baseline --customer C002 "Refund order 51877 and update my address"
"""

import argparse
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from typesafe_sdk import TypeSafeClient, TypeSafeError

import agent
import gate
import mcp_server
import fast_paths
import templates
from gate import Route
from jev_client import jev_cost_usd, make_client
from triage import TriageResult, triage
from verify import verify

ORDER_ID = fast_paths.ORDER_ID
CHECK_MEANING = {
    "addresses_all_concerns": "at least one of the customer's requests is not answered",
    "promises_unconfirmed": "it states or promises an outcome no tool result confirms",
    "tone_matches_frustration": "its tone does not fit how frustrated the customer is",
}


@dataclass
class Outcome:
    message_id: str
    route: Route
    path: str     # fast | llm | llm+verify | llm+verify+revise | llm+unverified | escalate
    reply: str
    reason: str = ""
    triage: TriageResult | None = None
    tool_calls: list[dict] = field(default_factory=list)
    verify_rounds: list[dict] = field(default_factory=list)
    template: str | None = None   # fast path only: which template answered
    ticket_id: str | None = None
    llm_calls: int = 0
    llm_cost_usd: float = 0.0
    jev_input_tokens: int = 0
    latency_ms: float = 0.0


def _with_customer(message: str, customer_id: str | None) -> str:
    return f"Customer ID: {customer_id}\n\n{message}" if customer_id else message


def _customer_record(customer_id: str | None) -> dict | None:
    """The customer record for Jev's state; just the ID if the lookup fails."""
    if not customer_id:
        return None
    res = mcp_server.get_customer(customer_id)
    return {"customer_id": customer_id} if res["isError"] else res["result"]


def _escalate(out: Outcome, message: str, customer_id: str | None, reason: str, uncertainty: str) -> None:
    facts = {"customer_id": customer_id, "order_ids": ORDER_ID.findall(message), "message": message}
    attempted = [f"{c['tool']}({json.dumps(c['input'])})" for c in out.tool_calls]
    res = mcp_server.escalate_to_human(headline=message[:80], reason=reason,
                                       attempted_actions=attempted, customer_facts=facts,
                                       open_uncertainty=uncertainty)
    out.tool_calls.append({"tool": "escalate_to_human", "input": {"reason": reason},
                           "result": res, "is_error": res["isError"]})
    out.path = "escalate"
    out.reply = (templates.escalated(res["result"]["ticket_id"]) if not res["isError"]
                 else "I'm connecting you with our support team now.")


def _llm_path(out: Outcome, message: str, customer_id: str | None, jev: TypeSafeClient | None,
              runner: Callable[..., agent.AgentRun], log_path: Path | None) -> None:
    facts = out.triage.facts() if out.triage else None
    try:
        run = runner(_with_customer(message, customer_id), triage_facts=facts)
    except agent.AgentError as err:       # runtime failure; AgentConfigError propagates
        return _escalate(out, message, customer_id, f"LLM path unavailable: {err}", "unresolved")
    out.llm_calls, out.llm_cost_usd, out.reply, out.path = 1, run.cost_usd, run.reply, "llm"
    out.tool_calls += run.tool_calls
    if jev is None:
        return
    for attempt in (1, 2):
        try:
            v = verify(jev, message, out.tool_calls, out.reply,
                       out.triage.frustration if out.triage else None)
        except TypeSafeError as err:
            # Fail open, but visibly: the reply goes out unchecked and the path says so.
            gate.log_event("verify_error", log_path, message_id=out.message_id, error=str(err))
            out.path = "llm+unverified"
            return
        out.jev_input_tokens += v.input_tokens
        out.verify_rounds.append({"attempt": attempt, "probabilities": v.probabilities, "failed": v.failed})
        gate.log_event("verify", log_path, message_id=out.message_id, attempt=attempt,
                       probabilities=v.probabilities, failed=v.failed)
        if v.passed:
            out.path = "llm+verify" if attempt == 1 else "llm+verify+revise"
            return
        if attempt == 2:
            return _escalate(out, message, customer_id, f"draft failed verification twice: {v.failed}",
                             "the agent could not produce a reply that passed verification")
        if run.session_id is None:    # resume=None would silently start a fresh session
            return _escalate(out, message, customer_id, "revision impossible: the first run "
                             "returned no session_id to resume", "draft failed verification")
        named = "\n".join(f"- {name}: {CHECK_MEANING[name]}" for name in v.failed)
        try:
            run = runner("A reviewer rejected your draft reply. Failed checks:\n" + named +
                         "\nRevise the reply to fix exactly these. Use tools if you need to. "
                         "Reply with the revised customer message only.",
                         triage_facts=facts, resume=run.session_id)
        except agent.AgentError as err:
            return _escalate(out, message, customer_id, f"revision failed: {err}", "unresolved")
        out.llm_calls += 1
        out.llm_cost_usd += run.cost_usd
        out.reply = run.reply
        out.tool_calls += run.tool_calls


def handle(message: str, jev: TypeSafeClient | None, customer_id: str | None = None,
           runner: Callable[..., agent.AgentRun] = agent.run_agent_sync,
           message_id: str | None = None, log_path: Path | None = None) -> Outcome:
    """Gated run. Pass jev=None for the LLM-does-everything baseline."""
    start = time.perf_counter()
    mid = message_id or uuid.uuid4().hex[:8]
    agent.new_session()          # fresh per-order refund totals for this conversation
    t = None
    if jev is not None:
        try:
            t = triage(jev, message, _customer_record(customer_id))
        except TypeSafeError as err:
            gate.log_event("triage_error", log_path, message_id=mid, error=str(err))
    decision = gate.route(t, mid, log_path, message) if jev is not None else gate.Decision(Route.LLM_PATH, "baseline")
    out = Outcome(mid, decision.route, "", "", decision.reason, triage=t,
                  jev_input_tokens=t.input_tokens if t else 0)

    if decision.route is Route.ESCALATE:
        _escalate(out, message, customer_id, f"customer asked for a human ({decision.reason})",
                  "none; no resolution attempted by design")
    elif decision.route is Route.FAST_PATH:
        fallthrough = fast_paths.run(out, decision.template, message, customer_id)
        if fallthrough:
            out.route, out.reason = Route.LLM_PATH, f"fast path fell through: {fallthrough}"
            gate.log_event("fallthrough", log_path, message_id=mid, reason=fallthrough)
    if out.route is Route.LLM_PATH:
        _llm_path(out, message, customer_id, jev, runner, log_path)

    out.latency_ms = (time.perf_counter() - start) * 1000
    gate.log_event("outcome", log_path, message_id=mid, route=out.route.value, path=out.path,
                   template=out.template,
                   latency_ms=round(out.latency_ms, 1), llm_calls=out.llm_calls,
                   llm_cost_usd=round(out.llm_cost_usd, 6), jev_input_tokens=out.jev_input_tokens,
                   jev_cost_usd=round(jev_cost_usd(out.jev_input_tokens), 8),
                   tools=[c["tool"] for c in out.tool_calls])
    return out


def main() -> None:
    import logging
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    for name in ("typesafe_sdk", "httpx2", "httpx"):
        logging.getLogger(name).setLevel(logging.WARNING)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("message")
    p.add_argument("--customer", help="customer ID, e.g. C001")
    p.add_argument("--fake-jev", action="store_true", help="uncalibrated keyword fake, no TypeSafe key")
    p.add_argument("--baseline", action="store_true", help="LLM does everything: no triage, no verify")
    args = p.parse_args()
    try:
        out = handle(args.message, None if args.baseline else make_client(fake=args.fake_jev),
                     args.customer)
    except agent.AgentConfigError as err:
        raise SystemExit(f"error: LLM path cannot run: {err}. No ticket was created.")
    print(f"route: {out.route.value}  path: {out.path}"
          f"{f'  template: {out.template}' if out.template else ''}  ({out.reason})")
    if out.triage:
        print(f"triage [{out.triage.jev_model}, {out.triage.latency_ms:.0f} ms]: "
              f"{json.dumps(out.triage.probabilities(), default=str)}")
    for call in out.tool_calls:
        print(f"tool: {call['tool']} {json.dumps(call['input'])} error={call['is_error']}")
    for v in out.verify_rounds:
        print(f"verify #{v['attempt']}: {json.dumps(v['probabilities'])} failed={v['failed']}")
    print(f"\n{out.reply}\n")
    print(f"latency_ms={out.latency_ms:.0f} llm_calls={out.llm_calls} llm_cost_usd={out.llm_cost_usd:.4f} "
          f"jev_cost_usd={jev_cost_usd(out.jev_input_tokens):.6f}  log: {gate.LOG_PATH}")


if __name__ == "__main__":
    main()
