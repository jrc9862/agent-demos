"""MCP server (stdio) exposing five support tools over fake_backend.

Run directly by the agent as a subprocess: `python mcp_server.py`.
Every failure is a CallToolResult with isError=True and a JSON body of
{errorCategory, isRetryable, message}. A timeout is never an empty success.
"""
from __future__ import annotations

import asyncio
import json

import jsonschema
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from fake_backend import Backend, BackendError, BackendTimeout, FaultPlan

MAX_ATTEMPTS = 2  # retry policy: 2 attempts on `transient`, none otherwise

ORDER_ID = {"type": "string", "pattern": "^ORD-[0-9]{4}$"}

TOOLS: list[types.Tool] = [
    types.Tool(
        name="get_customer",
        description=(
            "Look up a customer record by email or customer_id. Use this first to turn what the "
            "user told you (usually an email) into a customer_id, which every other tool needs. "
            "Requires at least one of email or customer_id. Returns name, tier, customer_id. "
            "Do not use it to find orders."),
        input_schema={"type": "object", "properties": {
            "email": {"type": "string"}, "customer_id": {"type": "string"}}},
    ),
    types.Tool(
        name="lookup_order",
        description=(
            "Fetch ONE order by its exact order ID (format ORD-1234). Use only when the user "
            "has given you a specific order ID. Returns the order with status, total, and amount "
            "already refunded. Do not use it to browse or guess IDs, and do not use it when the "
            "user describes an order ('the desk I ordered last week'): use search_orders. If it "
            "returns not-found, the ID is wrong; fall back to search_orders."),
        input_schema={"type": "object", "required": ["order_id"],
                     "properties": {"order_id": ORDER_ID}},
    ),
    types.Tool(
        name="search_orders",
        description=(
            "List a customer's orders, optionally filtered by status "
            "(processing/shipped/delivered) and an inclusive date range (YYYY-MM-DD). Requires "
            "customer_id from get_customer. Use when the user has no order ID, describes an "
            "order, or when you need to compare several orders (for example a suspected duplicate "
            "charge). An empty list means the customer has no matching orders. Do not use it when "
            "you already have an exact order ID: use lookup_order."),
        input_schema={"type": "object", "required": ["customer_id"], "properties": {
            "customer_id": {"type": "string"},
            "status": {"type": "string", "enum": ["processing", "shipped", "delivered"]},
            "date_from": {"type": "string"}, "date_to": {"type": "string"}}},
    ),
    types.Tool(
        name="process_refund",
        description=(
            "Refund an amount in USD against a delivered order. Requires customer_id, order_id, "
            "amount, and a one-sentence reason. Partial refunds are allowed up to the order "
            "total. Only for orders with status 'delivered' that belong to the customer. Do not "
            "use it for shipped or processing orders, and do not use it to resolve anything that "
            "is not a refund."),
        input_schema={"type": "object", "required": ["customer_id", "order_id", "amount", "reason"],
                     "properties": {"customer_id": {"type": "string"}, "order_id": ORDER_ID,
                                    "amount": {"type": "number"}, "reason": {"type": "string"}}},
    ),
    types.Tool(
        name="escalate_to_human",
        description=(
            "Hand the case to a human agent. Use when the user asks for a human, when a request "
            "is outside what the other tools can do (account changes, policy exceptions), or "
            "when a refund is blocked. The human sees ONLY this handoff, not the conversation, "
            "so it must stand alone: headline, reason, what you already tried, customer facts "
            "(IDs, amounts, dates), and what is still uncertain."),
        input_schema={"type": "object", "required": [
            "headline", "reason", "attempted_actions", "customer_facts", "open_uncertainty"],
            "properties": {
                "headline": {"type": "string", "minLength": 1},
                "reason": {"type": "string", "minLength": 1},
                "attempted_actions": {"type": "array", "items": {"type": "string"}},
                "customer_facts": {"type": "object", "properties": {
                    "customer_id": {"type": "string"},
                    "order_ids": {"type": "array", "items": {"type": "string"}},
                    "amounts": {"type": "array", "items": {"type": "number"}},
                    "dates": {"type": "array", "items": {"type": "string"}}}},
                "open_uncertainty": {"type": "string"}}},
    ),
]
_SCHEMAS = {t.name: t.input_schema for t in TOOLS}


def error_result(category: str, message: str, retryable: bool) -> types.CallToolResult:
    body = {"errorCategory": category, "isRetryable": retryable, "message": message}
    return types.CallToolResult(is_error=True, structured_content=body,
                                content=[types.TextContent(type="text", text=json.dumps(body))])


def ok_result(body: dict) -> types.CallToolResult:
    return types.CallToolResult(is_error=False, structured_content=body,
                                content=[types.TextContent(type="text", text=json.dumps(body))])


class Dispatcher:
    """Validates input, calls the backend, shapes results, tracks the retry budget."""

    def __init__(self, backend: Backend):
        self.backend = backend
        self.failures: dict[str, int] = {}

    def _call(self, name: str, args: dict) -> dict:
        b = self.backend
        if name == "escalate_to_human":
            return b.escalate_to_human(args)
        return getattr(b, name)(**args)

    def call(self, name: str, args: dict | None) -> types.CallToolResult:
        args = args or {}
        if name not in _SCHEMAS:
            return error_result("validation", f"unknown tool {name!r}", False)
        try:
            jsonschema.validate(args, _SCHEMAS[name])
        except jsonschema.ValidationError as e:
            return error_result("validation", f"invalid input: {e.message}", False)
        key = name + json.dumps(args, sort_keys=True)
        try:
            result = self._call(name, args)
        except BackendTimeout as e:
            n = self.failures[key] = self.failures.get(key, 0) + 1
            if n >= MAX_ATTEMPTS:
                return error_result(
                    "transient",
                    f"{e} (attempt {n} of {MAX_ATTEMPTS}). Retry budget spent: do not call "
                    f"{name} again with these inputs. Tell the user the system is unreachable.",
                    False)
            return error_result("transient", f"{e} (attempt {n} of {MAX_ATTEMPTS})", True)
        except BackendError as e:
            return error_result(e.category, str(e), e.retryable)
        self.failures.pop(key, None)
        return ok_result(result)


def build_server(dispatcher: Dispatcher) -> Server:
    # 2.x registers handlers as constructor callbacks, not decorators. The low-level Server
    # (not MCPServer) keeps the hand-written schemas and lets Dispatcher own validation, so bad
    # input gets an errorCategory instead of a protocol error.
    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=TOOLS)

    async def on_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        return dispatcher.call(params.name, params.arguments)

    return Server("support", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def main() -> None:
    dispatcher = Dispatcher(Backend(FaultPlan.from_env()))
    server = build_server(dispatcher)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
