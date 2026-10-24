"""Offline tests: fake backend, MCP error shapes, hook enforcement. No API key needed."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import agent
from fake_backend import Backend, FaultPlan
from hooks import REFUND_CEILING, RefundGuard
from mcp_server import MAX_ATTEMPTS, TOOLS, Dispatcher

HERE = Path(__file__).parent
REFUND = "mcp__support__process_refund"


def body(result):
    return json.loads(result.content[0].text)


def hook(guard, tool, **tool_input):
    data = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    return asyncio.run(guard(data, "toolu_1", None))


def refund(guard, amount, order="ORD-2001"):
    return hook(guard, REFUND, customer_id="C-200", order_id=order, amount=amount, reason="x")


def denied(out):
    return out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


# --- hook: the ceiling ------------------------------------------------------

def test_hook_blocks_750_and_points_at_escalation():
    g = RefundGuard()
    out = refund(g, 750)
    assert denied(out)
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "escalate_to_human" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert g.blocked[0]["order_id"] == "ORD-2001"


def test_hook_passes_499():
    assert refund(RefundGuard(), 499) == {}


def test_hook_boundary():
    assert refund(RefundGuard(), 500) == {}            # "above $500" is the rule
    assert denied(refund(RefundGuard(), 500.01))


def test_hook_blocks_split_refunds_on_one_order():
    g = RefundGuard()
    assert refund(g, 375) == {}
    assert denied(refund(g, 375))                       # 750 total on the same order
    assert refund(g, 100, order="ORD-3001") == {}       # other orders are separate


def test_failed_refund_releases_its_amount_so_retry_is_not_blocked():
    g = RefundGuard()
    data = {"hook_event_name": "PreToolUse", "tool_name": REFUND,
            "tool_input": {"order_id": "ORD-3001", "amount": 499}}
    assert asyncio.run(g(data, "t1", None)) == {}
    assert denied(asyncio.run(g(data, "t2", None)))        # still counted while in flight
    asyncio.run(g.release_on_failure({}, "t1", None))      # t1 timed out
    assert asyncio.run(g(data, "t3", None)) == {}          # retry allowed


def test_hook_fails_closed_on_unreadable_amount():
    for bad in ("lots", None, float("nan"), float("inf")):
        assert denied(refund(RefundGuard(), bad))
    assert denied(hook(RefundGuard(), REFUND, order_id="ORD-2001"))  # amount missing


def test_hook_accepts_numeric_string_and_ignores_other_tools():
    assert denied(refund(RefundGuard(), "750"))
    assert hook(RefundGuard(), "mcp__support__lookup_order", order_id="ORD-2001") == {}


def test_hook_is_registered_for_refund_tool_only():
    h = agent.build_hooks(RefundGuard())
    assert h["PreToolUse"][0].matcher == REFUND
    assert h["PostToolUseFailure"][0].matcher == REFUND


def test_no_hook_flag_removes_hook_and_prompt_rule_is_independent():
    g = RefundGuard()
    off = agent.build_options(False, True, [], g)
    on = agent.build_options(True, False, [], g)
    assert off.hooks is None and "never issue a refund above $500" in off.system_prompt
    assert on.hooks and "$500" not in on.system_prompt
    assert on.model == "claude-opus-5-5"


# --- MCP tool errors --------------------------------------------------------

def make(**kw):
    b = Backend()
    return b, Dispatcher(b)


def test_five_tools():
    assert [t.name for t in TOOLS] == [
        "get_customer", "lookup_order", "search_orders", "process_refund", "escalate_to_human"]


def test_error_shapes_by_category():
    _, d = make()
    cases = [
        (("lookup_order", {"order_id": "ORD-9999"}), "business", False),
        (("lookup_order", {"order_id": "bogus"}), "validation", False),
        (("process_refund", {"customer_id": "C-100", "order_id": "ORD-2001",
                             "amount": 10, "reason": "x"}), "permission", False),
        (("process_refund", {"customer_id": "C-200", "order_id": "ORD-2002",
                             "amount": 10, "reason": "x"}), "business", False),
        (("get_customer", {}), "validation", False),  # neither email nor id: backend validation
        (("nope", {}), "validation", False),
    ]
    for (name, args), cat, retry in cases:
        r = d.call(name, args)
        assert r.is_error, name
        assert set(body(r)) == {"errorCategory", "isRetryable", "message"}
        assert (body(r)["errorCategory"], body(r)["isRetryable"]) == (cat, retry), (name, body(r))


def test_timeout_is_error_not_empty_success_and_budget_is_two_attempts():
    b, d = make()
    b.fail("lookup_order", times=None)
    args = {"order_id": "ORD-2002"}
    first = d.call("lookup_order", args)
    assert first.is_error and body(first)["isRetryable"] is True
    assert body(first)["errorCategory"] == "transient"
    second = d.call("lookup_order", args)
    assert second.is_error and body(second)["isRetryable"] is False
    assert f"attempt {MAX_ATTEMPTS} of {MAX_ATTEMPTS}" in body(second)["message"]


def test_one_blip_then_success_clears_the_budget():
    b, d = make()
    b.fail("lookup_order", times=1)
    assert d.call("lookup_order", {"order_id": "ORD-2002"}).is_error
    ok = d.call("lookup_order", {"order_id": "ORD-2002"})
    assert not ok.is_error and body(ok)["status"] == "shipped"


def test_empty_search_is_success_and_distinct_from_outage():
    b, d = make()
    empty = d.call("search_orders", {"customer_id": "C-100", "status": "shipped"})
    assert not empty.is_error and body(empty) == {"orders": [], "count": 0}
    b.fail("search_orders", times=None)
    assert d.call("search_orders", {"customer_id": "C-100"}).is_error


def test_refund_succeeds_and_cannot_exceed_total():
    _, d = make()
    ok = d.call("process_refund", {"customer_id": "C-300", "order_id": "ORD-3001",
                                   "amount": 499, "reason": "defect"})
    assert not ok.is_error and body(ok)["amount"] == 499
    again = d.call("process_refund", {"customer_id": "C-300", "order_id": "ORD-3001",
                                      "amount": 10, "reason": "defect"})
    assert body(again)["errorCategory"] == "business"


def test_escalation_requires_complete_handoff():
    b, d = make()
    r = d.call("escalate_to_human", {"headline": "h", "reason": "r"})
    assert r.is_error and body(r)["errorCategory"] == "validation"
    full = {"headline": "Refund over limit", "reason": "750 > 500",
            "attempted_actions": ["get_customer", "process_refund blocked"],
            "customer_facts": {"customer_id": "C-200", "order_ids": ["ORD-2001"],
                               "amounts": [750], "dates": ["2026-09-20"]},
            "open_uncertainty": "none"}
    ok = d.call("escalate_to_human", full)
    assert not ok.is_error and b.escalations == [full]


def test_fault_plan_env_parsing():
    p = FaultPlan.from_env("lookup_order=timeout,process_refund=timeout:1")
    assert p.pending == {"lookup_order": None, "process_refund": 1}
    assert agent.failure_env(["lookup_order", "process_refund:1"]) == \
        "lookup_order=timeout,process_refund=timeout:1"
    assert p.trip("process_refund") and not p.trip("process_refund")


# --- real stdio MCP round trip ----------------------------------------------

def test_stdio_server_round_trip_with_injected_outage():
    async def go():
        params = StdioServerParameters(
            command=sys.executable, args=[str(HERE / "mcp_server.py")],
            env={"SUPPORT_FAILURES": "lookup_order=timeout"})
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            a = await s.call_tool("lookup_order", {"order_id": "ORD-2002"})
            b = await s.call_tool("lookup_order", {"order_id": "ORD-2002"})
            c = await s.call_tool("search_orders", {"customer_id": "C-200"})
            return tools, a, b, c

    tools, a, b, c = asyncio.run(go())
    assert len(tools) == 5
    assert a.is_error and json.loads(a.content[0].text)["isRetryable"] is True
    assert b.is_error and json.loads(b.content[0].text)["isRetryable"] is False
    assert not c.is_error and json.loads(c.content[0].text)["count"] == 2


# --- scenarios --------------------------------------------------------------

def test_scenarios_parse():
    s = agent.load_scenarios()
    assert {"multi-1", "multi-2", "multi-3", "unknown-order", "timeout",
            "refund-750", "argue-750", "human"} <= set(s)
    assert len(s["argue-750"]) == 3 and len(s["multi-1"]) == 1
    assert "750" in s["refund-750"][0]


def test_ceiling_constant():
    assert REFUND_CEILING == 500.00


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


def test_live_run_refuses_without_api_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(agent, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["agent.py", "--scenario", "human"])
    assert agent.main() == 2
    assert ".env.example" in capsys.readouterr().err
    with pytest.raises(agent.AgentConfigError):
        agent.require_api_key()


def test_model_flag_reaches_options():
    opts = agent.build_options(True, False, [], RefundGuard(), "claude-haiku-5-5")
    assert opts.model == "claude-haiku-5-5"
