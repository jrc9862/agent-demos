Command: `python pipeline.py --customer C001 "How do I return the socks for a refund?"`

```
route: FAST_PATH  path: fast  template: return_how  (intent return_how (0.99), needs_llm 0.03 < 0.95, 1 request, frustration calm)
triage [jev-1.14.0, 236 ms]: {"intent": "return_how", "intent_confidence": 0.99, "intent_probabilities": {"order_status": 0.0, "refund_request": 0.01, "refund_status": 0.0, "return_how": 0.99, "billing_dispute": 0.0, "invoice_request": 0.0, "account_change": 0.0, "login_help": 0.0, "other": 0.0}, "concern_count": 1, "concern_probabilities": {"1": 0.98, "2": 0.02, "3": 0.0}, "wants_human": 0.02, "frustration": "calm", "frustration_probabilities": {"calm": 1.0, "civil": 0.0, "angry": 0.0}, "needs_llm": 0.03}

You can return most items within 30 days of delivery. To start a return, open Account > Orders, choose the order, and select Return items. We email a prepaid return label to the address on your account; print it, pack the item, and drop it off with the carrier named on the label. Your refund is issued after the item arrives at our warehouse.

latency_ms=236 llm_calls=0 llm_cost_usd=0.0000 jev_cost_usd=0.000053  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
