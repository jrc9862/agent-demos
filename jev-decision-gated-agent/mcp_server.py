"""Five support tools over MCP (stdio), with structured errors.

The plain functions
(`lookup_order`, `search_orders`, ...) are what the MCP tools wrap; the fast path in pipeline.py
calls them in-process so it can answer without starting an LLM.

Every failure returns {"isError": true, "errorCategory", "isRetryable", "message"}. A timeout is
never an empty success.
"""

import json
from typing import Any, Callable

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

import fake_backend as backend

TRANSIENT_ATTEMPTS = 2  # enough to show recovery, not enough to hide a real outage


def _call(op: Callable[..., Any], *args: Any) -> dict:
    """Run a backend op; retry `transient` failures locally, return a structured result."""
    last: backend.BackendError | None = None
    for _ in range(TRANSIENT_ATTEMPTS):
        try:
            return {"isError": False, "result": op(*args)}
        except backend.BackendError as err:
            last = err
            if err.category != "transient":
                break
    return {"isError": True, "errorCategory": last.category, "isRetryable": last.retryable,
            "message": last.message, "attempts": TRANSIENT_ATTEMPTS if last.retryable else 1}


def get_customer(customer_id: str) -> dict:
    return _call(backend.get_customer, customer_id)


def lookup_order(order_id: str) -> dict:
    return _call(backend.lookup_order, order_id)


def search_orders(customer_id: str, status: str | None = None, since: str | None = None) -> dict:
    return _call(backend.search_orders, customer_id, status, since)


def process_refund(order_id: str, amount: float, reason: str) -> dict:
    return _call(backend.process_refund, order_id, amount, reason)


def escalate_to_human(headline: str, reason: str, attempted_actions: list[str],
                      customer_facts: dict, open_uncertainty: str) -> dict:
    missing = [k for k, v in {"headline": headline, "reason": reason}.items() if not v]
    if missing:
        return {"isError": True, "errorCategory": "validation", "isRetryable": False,
                "message": f"Handoff incomplete, missing: {', '.join(missing)}."}
    handoff = {"headline": headline, "reason": reason, "attempted_actions": attempted_actions,
               "customer_facts": customer_facts, "open_uncertainty": open_uncertainty}
    return _call(backend.create_escalation, handoff)


def _to_mcp(result: dict) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(result))],
                          is_error=result["isError"])


server = MCPServer("support")


@server.tool(name="get_customer", description=(
    "Fetch one customer's profile (name, email, shipping address, tier) by exact customer ID, "
    "e.g. 'C001'. Use when you need contact or address details. Does not return orders."))
def get_customer_tool(customer_id: str) -> CallToolResult:
    return _to_mcp(get_customer(customer_id))


@server.tool(name="lookup_order", description=(
    "Fetch ONE order by its exact order ID (a 5-digit number such as '48213'). Use only when the "
    "customer gave an order ID. Do NOT use to find orders by customer, date, or status; if the "
    "ID is unknown or returns a validation error, use search_orders instead."))
def lookup_order_tool(order_id: str) -> CallToolResult:
    return _to_mcp(lookup_order(order_id))


@server.tool(name="search_orders", description=(
    "List a customer's orders by customer ID, optionally filtered by status "
    "(processing|shipped|delivered|cancelled) and/or placed-on-or-after date 'YYYY-MM-DD'. Use "
    "when the customer did not give an order ID, or gave one that does not exist. An empty list "
    "means no matching orders; an error means the search did not run."))
def search_orders_tool(customer_id: str, status: str | None = None,
                       since: str | None = None) -> CallToolResult:
    return _to_mcp(search_orders(customer_id, status, since))


@server.tool(name="process_refund", description=(
    "Issue a refund against one order. Requires order_id, amount in USD, and a short reason. "
    "Refunds above the policy ceiling are blocked before this tool runs; escalate instead."))
def process_refund_tool(order_id: str, amount: float, reason: str) -> CallToolResult:
    return _to_mcp(process_refund(order_id, amount, reason))


@server.tool(name="escalate_to_human", description=(
    "Hand the case to a human agent. Use immediately when the customer asks for a person, or "
    "when policy blocks the resolution. Requires a complete handoff: headline, reason, "
    "attempted_actions (list), customer_facts (IDs, amounts, dates), open_uncertainty."))
def escalate_to_human_tool(headline: str, reason: str, attempted_actions: list[str],
                           customer_facts: dict, open_uncertainty: str) -> CallToolResult:
    return _to_mcp(escalate_to_human(headline, reason, attempted_actions, customer_facts,
                                     open_uncertainty))


if __name__ == "__main__":
    server.run("stdio")
