"""Refund ceiling, enforced in code before the tool runs.

The cumulative guard follows `support-agent/hooks.py`. It is plain `if`s over the tool call and the guard's own running totals.
Nothing from triage, verification, or the conversation is an input, so no model output can move
the line.

The ceiling applies per order across the session: three $400 refunds on one order are blocked on
the second. An allowed call counts at once; if the tool then fails (PostToolUseFailure) the
amount is released, so a retry after a timeout is not double-counted. Tradeoff: a timeout where
the refund actually went through upstream is released too. A real backend needs idempotency keys.
"""

import math
from typing import Any

from claude_agent_sdk import HookMatcher

REFUND_CEILING_USD = 500.00
REFUND_TOOL = "mcp__support__process_refund"


def _deny(reason: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


class RefundGuard:
    def __init__(self, ceiling: float = REFUND_CEILING_USD):
        self.ceiling = ceiling
        self.approved: dict[str, float] = {}               # order_id -> total let through so far
        self.blocked: list[dict[str, Any]] = []
        self._inflight: dict[str, tuple[str, float]] = {}  # tool_use_id -> (order_id, amount)

    async def __call__(self, input_data: dict, tool_use_id: str | None, context: Any) -> dict:
        if input_data.get("tool_name") != REFUND_TOOL:
            return {}
        args = input_data.get("tool_input") or {}
        order_id = str(args.get("order_id", ""))
        try:
            amount = float(args["amount"])
            if not math.isfinite(amount):      # NaN compares false against everything
                raise ValueError(amount)
        except (KeyError, TypeError, ValueError):
            return self._block(args, order_id, "the amount is missing or not a finite number")
        total = self.approved.get(order_id, 0.0) + amount
        if total > self.ceiling + 1e-9:
            return self._block(args, order_id,
                               f"refund of ${amount:,.2f} (${total:,.2f} on order {order_id} this "
                               f"session) is above the ${self.ceiling:,.0f} ceiling")
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
        return _deny(f"Refund blocked: {why}. Do not retry or split the refund. Call "
                     "escalate_to_human instead, with a complete handoff that includes the order "
                     "ID and requested amount.")


def build_hooks(guard: RefundGuard | None = None) -> dict[str, list[HookMatcher]]:
    guard = guard or RefundGuard()
    return {"PreToolUse": [HookMatcher(matcher=REFUND_TOOL, hooks=[guard])],
            "PostToolUseFailure": [HookMatcher(matcher=REFUND_TOOL, hooks=[guard.release_on_failure])]}
