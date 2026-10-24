"""In-memory customers and orders with injectable failures.

Self-contained in this folder, not imported. Failures are injected with `fail_next(op, kind)` in-process, or with
the FAKE_BACKEND_FAIL env var (e.g. "lookup_order:timeout") for the MCP server subprocess.
"""

import copy
import itertools
import os
from datetime import date


class BackendError(Exception):
    """A backend failure with the fields the MCP layer turns into a structured tool error."""

    def __init__(self, category: str, retryable: bool, message: str):
        super().__init__(message)
        self.category = category  # transient | validation | business | permission
        self.retryable = retryable
        self.message = message


CUSTOMERS = {
    "C001": {"customer_id": "C001", "name": "Dana Ruiz", "email": "dana@example.com",
             "address": "14 Alder St, Portland, OR 97205", "tier": "standard"},
    "C002": {"customer_id": "C002", "name": "Sam Okafor", "email": "sam@example.com",
             "address": "902 Pine Ave, Austin, TX 78701", "tier": "gold"},
    "C003": {"customer_id": "C003", "name": "Lee Park", "email": "lee@example.com",
             "address": "3 Harbor Rd, Salem, MA 01970", "tier": "standard"},
}

ORDERS = {
    "48213": {"order_id": "48213", "invoice_id": "INV-48213", "refunds": [], "customer_id": "C001", "status": "shipped", "total": 89.00,
              "placed": "2026-10-03", "carrier": "UPS", "tracking": "1Z999AA10123456784",
              "eta": "2026-10-12", "items": ["Trail running shoes"]},
    "48377": {"order_id": "48377", "invoice_id": "INV-48377", "refunds": [], "customer_id": "C001", "status": "delivered", "total": 42.50,
              "placed": "2026-09-21", "delivered": "2026-09-25", "items": ["Water bottle", "Socks"]},
    "51877": {"order_id": "51877", "invoice_id": "INV-51877", "refunds": [], "customer_id": "C002", "status": "delivered", "total": 1240.00,
              "placed": "2026-09-28", "delivered": "2026-10-02", "items": ["Laptop, 14-inch"]},
    "52004": {"order_id": "52004", "invoice_id": "INV-52004", "refunds": [], "customer_id": "C002", "status": "processing", "total": 64.00,
              "placed": "2026-10-08", "items": ["USB-C dock"]},
    "53190": {"order_id": "53190", "invoice_id": "INV-53190", "refunds": [], "customer_id": "C003", "status": "cancelled", "total": 19.99,
              "placed": "2026-10-01", "items": ["Phone case"]},
    "50310": {"order_id": "50310", "invoice_id": "INV-50310", "refunds": [
                  {"refund_id": "R0907", "amount": 40.00, "date": "2026-09-24"}],
              "customer_id": "C002", "status": "delivered", "total": 79.00,
              "placed": "2026-09-15", "delivered": "2026-09-19", "items": ["Keyboard"]},
    "49555": {"order_id": "49555", "invoice_id": "INV-49555", "refunds": [
                  {"refund_id": "R0912", "amount": 31.00, "date": "2026-09-22"}],
              "customer_id": "C003", "status": "delivered", "total": 31.00,
              "placed": "2026-09-12", "delivered": "2026-09-16", "items": ["Desk lamp"]},
}

REFUNDS: list[dict] = []
ESCALATIONS: list[dict] = []
_ids = itertools.count(1001)

_FAILURES = {
    "timeout": ("transient", True, "Backend timed out after 5s. The order system may be degraded."),
    "unavailable": ("transient", True, "Backend returned 503 Service Unavailable."),
    "forbidden": ("permission", False, "This agent is not permitted to perform that operation."),
}
FAIL_NEXT: dict[str, list[str]] = {}


def fail_next(op: str, kind: str = "timeout", times: int = 1) -> None:
    """Make the next `times` calls to `op` fail with the named failure kind."""
    FAIL_NEXT.setdefault(op, []).extend([kind] * times)


def _load_env_failures() -> None:
    for spec in filter(None, os.environ.get("FAKE_BACKEND_FAIL", "").split(",")):
        op, _, kind = spec.partition(":")
        fail_next(op.strip(), (kind or "timeout").strip(), times=10)


def _maybe_fail(op: str) -> None:
    queue = FAIL_NEXT.get(op)
    if queue:
        category, retryable, message = _FAILURES[queue.pop(0)]
        raise BackendError(category, retryable, message)


def get_customer(customer_id: str) -> dict:
    _maybe_fail("get_customer")
    if customer_id not in CUSTOMERS:
        raise BackendError("validation", False, f"No customer with ID {customer_id!r}.")
    return dict(CUSTOMERS[customer_id])


def lookup_order(order_id: str) -> dict:
    _maybe_fail("lookup_order")
    if order_id not in ORDERS:
        raise BackendError("validation", False, f"No order with ID {order_id!r}.")
    return copy.deepcopy(ORDERS[order_id])


def search_orders(customer_id: str, status: str | None = None, since: str | None = None) -> list[dict]:
    _maybe_fail("search_orders")
    if customer_id not in CUSTOMERS:
        raise BackendError("validation", False, f"No customer with ID {customer_id!r}.")
    found = [o for o in ORDERS.values() if o["customer_id"] == customer_id]
    if status:
        found = [o for o in found if o["status"] == status]
    if since:
        found = [o for o in found if date.fromisoformat(o["placed"]) >= date.fromisoformat(since)]
    return [copy.deepcopy(o) for o in found]


def process_refund(order_id: str, amount: float, reason: str) -> dict:
    """No ceiling here on purpose: the $500 limit is policy and lives in hooks.py."""
    _maybe_fail("process_refund")
    order = lookup_order(order_id)
    if amount <= 0:
        raise BackendError("validation", False, "Refund amount must be positive.")
    if amount > order["total"]:
        raise BackendError("business", False,
                           f"Refund ${amount:.2f} exceeds order total ${order['total']:.2f}.")
    refund = {"refund_id": f"R{next(_ids)}", "order_id": order_id, "amount": amount,
              "reason": reason, "status": "issued"}
    REFUNDS.append(refund)
    return refund


def create_escalation(handoff: dict) -> dict:
    _maybe_fail("escalate_to_human")
    ticket = {"ticket_id": f"T{next(_ids)}", "queue": "tier2", **handoff}
    ESCALATIONS.append(ticket)
    return ticket


_load_env_failures()
