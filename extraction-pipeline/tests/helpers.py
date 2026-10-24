"""Fakes for the Anthropic client. No network."""
from types import SimpleNamespace

from schema import FIELDS

INVOICE_TEXT = "Invoice INV-1 from Acme, 2026-03-01. Subtotal 100.00, tax 8.00, total 108.00."


def invoice(**over) -> dict:
    d = {"invoice_number": "INV-1", "vendor": "Acme", "invoice_date": "2026-03-01", "category": "software",
         "other_detail": None, "subtotal": 100.0, "tax": 8.0, "stated_total": 108.0, "calculated_total": 108.0,
         "warranty_date": None}
    d.update(over)
    d["confidence"] = d.get("confidence") or {k: 0.95 for k in FIELDS["invoice"]}
    return d


def tool_message(data: dict, stop_reason: str = "tool_use"):
    block = SimpleNamespace(type="tool_use", name="extract", input=data)
    return SimpleNamespace(stop_reason=stop_reason, content=[block], stop_details=None)


class FakeClient:
    """messages.create pops queued responses (messages or exceptions) and records each request."""

    def __init__(self, *responses):
        self.queue = list(responses)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        nxt = self.queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt
