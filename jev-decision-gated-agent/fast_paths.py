"""Fast-path handlers: a tool call (or none) plus a template. No LLM, and none moves money.

`out` is the pipeline's Outcome. Each handler returns a fallthrough reason when it cannot
answer, so the pipeline hands the message to the LLM path instead.
"""

import mcp_server
import templates
from gate import ORDER_ID


def _call_tool(out, tool: str, **args) -> dict:
    res = getattr(mcp_server, tool)(**args)
    out.tool_calls.append({"tool": tool, "input": args, "result": res, "is_error": res["isError"]})
    return res


def _owned_order(out, order_id: str, customer_id: str | None) -> tuple[dict | None, str | None]:
    """lookup_order plus the ownership check. Returns (order, None), or (None, reason) when the
    fast path must give way; a transient backend error sets the reply and returns (None, None)."""
    res = _call_tool(out, "lookup_order", order_id=order_id)
    if not res["isError"] and customer_id and res["result"]["customer_id"] != customer_id:
        out.tool_calls.pop()      # the lookup is not reported as an answer; the LLM path redoes it
        return None, f"order {order_id} does not belong to customer {customer_id}"
    if res["isError"] and res["errorCategory"] == "transient":
        out.reply = templates.backend_unavailable()
        return None, None
    if res["isError"]:
        return None, f"lookup_order failed: {res['message']}"
    return res["result"], None


def _search(out, customer_id: str) -> tuple[list | None, str | None]:
    """search_orders. (orders, None); (None, reason) to fall through; (None, None) after a
    transient error, which sets the reply."""
    res = _call_tool(out, "search_orders", customer_id=customer_id)
    if res["isError"] and res["errorCategory"] == "transient":
        out.reply = templates.backend_unavailable()
    elif res["isError"]:
        return None, f"search_orders failed: {res['message']}"
    return (None if res["isError"] else res["result"]), None


def _fast_order_status(out, message: str, customer_id: str | None) -> str | None:
    match = ORDER_ID.search(message)
    if not match:
        return "fast path needs an order ID"  # gate routes ID-less messages to the LLM
    order, reason = _owned_order(out, match.group(1), customer_id)
    if order:
        out.reply = templates.order_status(order)
    return reason


def _handoff(out, headline: str, reason: str, facts: dict) -> bool:
    """Structured escalate_to_human call from a template route. False if the ticket failed."""
    res = _call_tool(out, "escalate_to_human", headline=headline, reason=reason,
                     attempted_actions=[], customer_facts=facts,
                     open_uncertainty="none; handled by a fixed template")
    if not res["isError"]:
        out.ticket_id = res["result"]["ticket_id"]
    return not res["isError"]


def _fast_account_change(out, message: str, customer_id: str | None) -> str | None:
    if not customer_id:
        return "account_change handoff needs a customer ID"
    if not _handoff(out, f"Account change request: {message[:60]}", "account change requested",
                    {"customer_id": customer_id, "requested_change": message}):
        return "escalate_to_human failed"
    out.reply = templates.account_change() + " " + templates.escalated(out.ticket_id)
    return None


def _fast_invoice(out, message: str, customer_id: str | None) -> str | None:
    if not customer_id:
        return "invoice_request needs a customer ID"
    orders, reason = _search(out, customer_id)
    if orders is not None and not orders:
        return "no orders on the account"
    if orders:
        out.reply = templates.invoice(max(orders, key=lambda o: o["placed"]))
    return reason


def _fast_refund_status(out, message: str, customer_id: str | None) -> str | None:
    match = ORDER_ID.search(message)
    if not match:
        return "refund_status needs an order ID"
    order, reason = _owned_order(out, match.group(1), customer_id)
    if not order:
        return reason
    out.reply = templates.refund_status(order) or ""
    if out.reply:
        return None
    # No refund on record: say so, and hand the request to the team.
    if not _handoff(out, f"No refund on record for order {order['order_id']}",
                    "customer asked about a refund the system does not show",
                    {"customer_id": customer_id or order["customer_id"],
                     "order_ids": [order["order_id"]], "message": message}):
        return "escalate_to_human failed"
    out.reply = templates.refund_not_on_record(order["order_id"]) + " " + \
        templates.escalated(out.ticket_id)
    return None


FAST_HANDLERS = {
    "order_status": _fast_order_status,
    "account_change": _fast_account_change,
    "return_how": lambda out, message, customer_id: setattr(out, "reply", templates.return_how()),
    "login_help": lambda out, message, customer_id: setattr(out, "reply", templates.login_help()),
    "invoice_request": _fast_invoice,
    "refund_status": _fast_refund_status,
}


def run(out, template: str, message: str, customer_id: str | None) -> str | None:
    """Tool call + template. Returns a fallthrough reason if the fast path cannot answer."""
    reason = FAST_HANDLERS[template](out, message, customer_id)
    if reason:
        return reason
    out.path, out.template = "fast", template
    return None
