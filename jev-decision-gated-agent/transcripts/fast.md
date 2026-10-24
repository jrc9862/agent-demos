Command: `python pipeline.py "Where is order 48213?"`

```
route: FAST_PATH  path: fast  template: order_status  (intent order_status (1.00), needs_llm 0.05 < 0.95, 1 request, frustration calm)
triage [jev-1.14.0, 227 ms]: {"intent": "order_status", "intent_confidence": 1.0, "intent_probabilities": {"order_status": 1.0, "refund_request": 0.0, "refund_status": 0.0, "return_how": 0.0, "billing_dispute": 0.0, "invoice_request": 0.0, "account_change": 0.0, "login_help": 0.0, "other": 0.0}, "concern_count": 1, "concern_probabilities": {"1": 1.0, "2": 0.0, "3": 0.0}, "wants_human": 0.02, "frustration": "calm", "frustration_probabilities": {"calm": 0.94, "civil": 0.06, "angry": 0.0}, "needs_llm": 0.05}
tool: lookup_order {"order_id": "48213"} error=False

Order 48213 shipped with UPS (tracking 1Z999AA10123456784) and is expected to arrive 2026-10-12.

latency_ms=229 llm_calls=0 llm_cost_usd=0.0000 jev_cost_usd=0.000051  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
