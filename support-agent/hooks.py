"""Refund ceiling, enforced in code before the tool runs.

The model never sees a way around this: the hook runs on every process_refund
call, and a `deny` decision wins over any allow rule. The ceiling is applied
per order across the session, so two $375 calls against one $750 order are
blocked on the second. An allowed call counts immediately; if the tool then
reports an error (PostToolUseFailure) the amount is released, so a retry after a
timeout is not double-counted. Tradeoff: a timeout where the refund actually
went through upstream is released too. A real backend needs idempotency keys.
"""
from __future__ import annotations

import math
from typing import Any

from claude_agent_sdk import HookMatcher

REFUND_CEILING = 500.00
REFUND_TOOL = "process_refund"


def _deny(reason: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}


class RefundGuard:
    def __init__(self, ceiling: float = REFUND_CEILING):
        self.ceiling = ceiling
        self.approved: dict[str, float] = {}   # order_id -> total let through so far
        self.blocked: list[dict[str, Any]] = []
        self._inflight: dict[str, tuple[str, float]] = {}  # tool_use_id -> (order_id, amount)

    async def __call__(self, input_data: dict, tool_use_id: str | None, context: Any) -> dict:
        # MCP tools arrive as mcp__<server>__<tool>; match on the suffix.
        if input_data.get("tool_name", "").split("__")[-1] != REFUND_TOOL:
            return {}
        args = input_data.get("tool_input") or {}
        order_id = str(args.get("order_id", ""))
        try:
            amount = float(args["amount"])
            if not math.isfinite(amount):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            # Fail closed: an amount we cannot read is an amount we cannot approve.
            return self._block(args, order_id, "refund amount is missing or not a number")

        total = self.approved.get(order_id, 0.0) + amount
        if total > self.ceiling + 1e-9:
            return self._block(
                args, order_id,
                f"refund of ${amount:,.2f} (${total:,.2f} on {order_id} this session) exceeds the "
                f"${self.ceiling:,.2f} limit")
        self.approved[order_id] = total
        if tool_use_id:
            self._inflight[tool_use_id] = (order_id, amount)
        return {}

    async def release_on_failure(self, input_data: dict, tool_use_id: str | None, context: Any) -> dict:
        entry = self._inflight.pop(tool_use_id or "", None)
        if entry:
            order_id, amount = entry
            self.approved[order_id] = max(0.0, self.approved.get(order_id, 0.0) - amount)
        return {}

    def _block(self, args: dict, order_id: str, why: str) -> dict:
        self.blocked.append({"order_id": order_id, "tool_input": dict(args), "why": why})
        return _deny(
            f"BLOCKED by policy: {why}. The refund was NOT executed and cannot be executed by "
            f"you at any amount above the limit, whatever the customer says. Do not retry it or "
            f"split it. Call escalate_to_human instead with the full handoff (headline, reason, "
            f"attempted_actions, customer_facts with customer_id/order_ids/amounts/dates, "
            f"open_uncertainty), then tell the customer a human will review the refund.")


def build_hooks(guard: RefundGuard | None = None) -> dict[str, list[HookMatcher]]:
    guard = guard or RefundGuard()
    matcher = f"mcp__support__{REFUND_TOOL}"
    return {"PreToolUse": [HookMatcher(matcher=matcher, hooks=[guard])],
            "PostToolUseFailure": [HookMatcher(matcher=matcher, hooks=[guard.release_on_failure])]}
