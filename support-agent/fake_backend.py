"""In-memory customers and orders with injectable failures.

Failures are deterministic. Two ways to inject them:

  * code:  backend.fail("lookup_order", times=1)      # next call only
  * env:   SUPPORT_FAILURES="lookup_order=timeout"    # every call (a real outage)
           SUPPORT_FAILURES="lookup_order=timeout:1"  # first call only (a blip)

The env form exists because the MCP server runs as a subprocess of the agent.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

TODAY = "2026-10-09"  # fixed so "last week" means the same thing on every run

CUSTOMERS = {
    "C-100": {"customer_id": "C-100", "name": "Dana Whitfield", "email": "dana@example.com",
              "tier": "standard"},
    "C-200": {"customer_id": "C-200", "name": "Marcus Oyelaran", "email": "marcus@example.com",
              "tier": "plus"},
    "C-300": {"customer_id": "C-300", "name": "Priya Raman", "email": "priya@example.com",
              "tier": "standard"},
}

ORDERS = {
    "ORD-1042": {"order_id": "ORD-1042", "customer_id": "C-100", "item": "27in monitor",
                 "total": 289.00, "status": "delivered", "date": "2026-09-28"},
    # ORD-1043 and ORD-1044 are the same stand charged twice a minute apart.
    "ORD-1043": {"order_id": "ORD-1043", "customer_id": "C-100", "item": "monitor stand",
                 "total": 49.00, "status": "delivered", "date": "2026-09-28"},
    "ORD-1044": {"order_id": "ORD-1044", "customer_id": "C-100", "item": "monitor stand",
                 "total": 49.00, "status": "delivered", "date": "2026-09-28"},
    "ORD-2001": {"order_id": "ORD-2001", "customer_id": "C-200", "item": "15in laptop",
                 "total": 750.00, "status": "delivered", "date": "2026-09-20"},
    "ORD-2002": {"order_id": "ORD-2002", "customer_id": "C-200", "item": "standing desk",
                 "total": 420.00, "status": "shipped", "date": "2026-10-01"},
    "ORD-3001": {"order_id": "ORD-3001", "customer_id": "C-300", "item": "espresso machine",
                 "total": 499.00, "status": "delivered", "date": "2026-10-02"},
    "ORD-3002": {"order_id": "ORD-3002", "customer_id": "C-300", "item": "descaler kit",
                 "total": 18.00, "status": "processing", "date": "2026-10-08"},
}

ORDER_ID_RE = re.compile(r"^ORD-\d{4}$")


class BackendError(Exception):
    """Base class. `category` and `retryable` flow straight into the MCP error."""
    category = "business"
    retryable = False


class BackendTimeout(BackendError):
    category = "transient"
    retryable = True


class NotFound(BackendError):
    category = "business"


class BusinessRule(BackendError):
    category = "business"


class PermissionDenied(BackendError):
    category = "permission"


class BadInput(BackendError):
    category = "validation"


@dataclass
class FaultPlan:
    """tool name -> remaining failures (None = fail forever)."""
    pending: dict[str, int | None] = field(default_factory=dict)

    @classmethod
    def from_env(cls, raw: str | None = None) -> "FaultPlan":
        raw = os.environ.get("SUPPORT_FAILURES", "") if raw is None else raw
        plan = cls()
        for item in filter(None, (p.strip() for p in raw.split(","))):
            tool, _, spec = item.partition("=")
            _, _, count = spec.partition(":")
            plan.pending[tool] = int(count) if count else None
        return plan

    def trip(self, tool: str) -> bool:
        if tool not in self.pending:
            return False
        left = self.pending[tool]
        if left is None:
            return True
        if left <= 1:
            del self.pending[tool]
        else:
            self.pending[tool] = left - 1
        return True


class Backend:
    def __init__(self, faults: FaultPlan | None = None):
        self.faults = faults or FaultPlan()
        self.refunded: dict[str, float] = {}   # order_id -> amount already refunded
        self.escalations: list[dict] = []

    def fail(self, tool: str, times: int | None = 1) -> None:
        self.faults.pending[tool] = times

    def _gate(self, tool: str) -> None:
        if self.faults.trip(tool):
            raise BackendTimeout(f"{tool}: upstream order system timed out after 10s")

    def get_customer(self, email: str | None = None, customer_id: str | None = None) -> dict:
        self._gate("get_customer")
        if not email and not customer_id:
            raise BadInput("provide email or customer_id")
        for c in CUSTOMERS.values():
            if (customer_id and c["customer_id"] == customer_id) or \
               (email and c["email"].lower() == email.lower()):
                return dict(c)
        raise NotFound("no customer matches that email or customer_id")

    def lookup_order(self, order_id: str) -> dict:
        self._gate("lookup_order")
        if not ORDER_ID_RE.match(order_id):
            raise BadInput(f"order_id must look like ORD-1234, got {order_id!r}")
        if order_id not in ORDERS:
            raise NotFound(f"no order with id {order_id}; use search_orders to find it by customer")
        return {**ORDERS[order_id], "refunded": self.refunded.get(order_id, 0.0)}

    def search_orders(self, customer_id: str, status: str | None = None,
                      date_from: str | None = None, date_to: str | None = None) -> dict:
        self._gate("search_orders")
        if customer_id not in CUSTOMERS:
            raise NotFound(f"no customer {customer_id}")
        hits = [o for o in ORDERS.values() if o["customer_id"] == customer_id
                and (not status or o["status"] == status)
                and (not date_from or o["date"] >= date_from)
                and (not date_to or o["date"] <= date_to)]
        # An empty list is a real answer: the system is up and nothing matched.
        return {"orders": sorted(hits, key=lambda o: o["date"]), "count": len(hits)}

    def process_refund(self, customer_id: str, order_id: str, amount: float, reason: str) -> dict:
        self._gate("process_refund")
        order = ORDERS.get(order_id)
        if order is None:
            raise NotFound(f"no order with id {order_id}")
        if order["customer_id"] != customer_id:
            raise PermissionDenied(f"{order_id} does not belong to {customer_id}")
        if order["status"] != "delivered":
            raise BusinessRule(f"{order_id} is {order['status']}; only delivered orders can be refunded")
        if amount <= 0:
            raise BadInput("amount must be positive")
        already = self.refunded.get(order_id, 0.0)
        if already + amount > order["total"] + 1e-9:
            raise BusinessRule(f"refund would exceed order total {order['total']:.2f} "
                               f"(already refunded {already:.2f})")
        self.refunded[order_id] = already + amount
        return {"refund_id": f"RF-{len(self.refunded):04d}", "order_id": order_id,
                "amount": amount, "reason": reason}

    def escalate_to_human(self, handoff: dict) -> dict:
        self._gate("escalate_to_human")
        self.escalations.append(handoff)
        return {"ticket_id": f"ESC-{len(self.escalations):04d}", "queue": "tier2",
                "message": "A human agent will follow up with the customer."}
