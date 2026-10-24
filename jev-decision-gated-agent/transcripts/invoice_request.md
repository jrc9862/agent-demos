Command: `python pipeline.py --customer C001 "Can I get an invoice for my last purchase for my expense report?"`

```
route: FAST_PATH  path: fast  template: invoice_request  (intent invoice_request (1.00), needs_llm 0.19 < 0.95, 1 request, frustration calm)
triage [jev-1.14.0, 781 ms]: {"intent": "invoice_request", "intent_confidence": 1.0, "intent_probabilities": {"order_status": 0.0, "refund_request": 0.0, "refund_status": 0.0, "return_how": 0.0, "billing_dispute": 0.0, "invoice_request": 1.0, "account_change": 0.0, "login_help": 0.0, "other": 0.0}, "concern_count": 1, "concern_probabilities": {"1": 0.99, "2": 0.01, "3": 0.0}, "wants_human": 0.02, "frustration": "calm", "frustration_probabilities": {"calm": 1.0, "civil": 0.0, "angry": 0.0}, "needs_llm": 0.19}
tool: search_orders {"customer_id": "C001"} error=False

Your most recent order is 48213 (Trail running shoes), placed 2026-10-03. Its invoice ID is INV-48213; you can download it from Account > Orders > Invoices.

latency_ms=782 llm_calls=0 llm_cost_usd=0.0000 jev_cost_usd=0.000054  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
