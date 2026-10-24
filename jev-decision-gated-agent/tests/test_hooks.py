import asyncio

import pytest

import agent
import hooks
from hooks import RefundGuard


def call(guard, amount, order="51877", tool_use_id="t1", tool=hooks.REFUND_TOOL):
    data = {"hook_event_name": "PreToolUse", "tool_name": tool,
            "tool_input": {"order_id": order, "amount": amount, "reason": "x"}}
    return asyncio.run(guard(data, tool_use_id, None))


def denied(out):
    return out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def test_750_refund_is_blocked_and_points_at_escalation():
    out = call(RefundGuard(), 750)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "escalate_to_human" in out["permissionDecisionReason"]


@pytest.mark.parametrize("amount, blocked", [(500, False), (500.0, False), (500.01, True),
                                             ("750", True), (None, True), ("lots", True),
                                             (float("nan"), True), (float("inf"), True),
                                             (float("-inf"), True), ("nan", True)])
def test_ceiling_and_fail_closed(amount, blocked):
    assert denied(call(RefundGuard(), amount)) is blocked


def test_missing_amount_is_denied():
    data = {"tool_name": hooks.REFUND_TOOL, "tool_input": {"order_id": "51877"}}
    assert denied(asyncio.run(RefundGuard()(data, "t1", None)))


def test_other_tools_pass_through():
    assert call(RefundGuard(), 10_000, tool="mcp__support__lookup_order") == {}


def test_three_400_refunds_on_one_order_third_is_denied():
    g = RefundGuard()
    assert call(g, 400, tool_use_id="t1") == {}           # 400
    assert denied(call(g, 400, tool_use_id="t2"))         # 800 > 500: cumulative, already blocked
    assert denied(call(g, 400, tool_use_id="t3"))
    assert call(g, 400, order="48377", tool_use_id="t4") == {}   # other orders are separate


def test_cumulative_total_allows_up_to_the_ceiling_then_denies():
    g = RefundGuard()
    assert call(g, 200, tool_use_id="t1") == {} and call(g, 300, tool_use_id="t2") == {}
    assert denied(call(g, 0.01, tool_use_id="t3"))


def test_failed_refund_releases_its_amount_so_retry_is_not_blocked():
    g = RefundGuard()
    assert call(g, 400, tool_use_id="t1") == {}
    assert denied(call(g, 400, tool_use_id="t2"))         # t1 still counts while in flight
    asyncio.run(g.release_on_failure({}, "t1", None))     # t1 timed out
    assert call(g, 400, tool_use_id="t3") == {}


@pytest.mark.parametrize("facts", [None, {"intent": "refund", "intent_confidence": 0.99},
                                   {"refund_approved": True, "ceiling": 10_000, "wants_human": 0.0}])
def test_hook_is_wired_whatever_triage_says(facts):
    """Triage output reaches the prompt, never the hook: the hook's only inputs are the tool call."""
    guard = RefundGuard()
    options = agent.build_options(triage_facts=facts, guard=guard)
    pre, post = options.hooks["PreToolUse"], options.hooks["PostToolUseFailure"]
    assert [m.matcher for m in pre] == [m.matcher for m in post] == [hooks.REFUND_TOOL]
    assert pre[0].hooks == [guard] and post[0].hooks == [guard.release_on_failure]
    assert hooks.REFUND_TOOL == agent.TOOL_PREFIX + "process_refund"
    assert options.model == "claude-opus-5-5"


def test_guard_survives_across_runs_in_one_session_and_resets_between_sessions():
    g = agent.new_session()
    assert agent.build_options().hooks["PreToolUse"][0].hooks == [g]
    assert agent.new_session() is not g
