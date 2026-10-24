Command: `python pipeline.py --customer C003 "Did my refund for order 49555 go through?"`

```
route: FAST_PATH  path: fast  template: refund_status  (intent refund_status (1.00), needs_llm 0.01 < 0.95, 1 request, frustration calm)
triage [jev-1.14.0, 540 ms]: {"intent": "refund_status", "intent_confidence": 1.0, "intent_probabilities": {"order_status": 0.0, "refund_request": 0.0, "refund_status": 1.0, "return_how": 0.0, "billing_dispute": 0.0, "invoice_request": 0.0, "account_change": 0.0, "login_help": 0.0, "other": 0.0}, "concern_count": 1, "concern_probabilities": {"1": 0.99, "2": 0.01, "3": 0.0}, "wants_human": 0.02, "frustration": "calm", "frustration_probabilities": {"calm": 0.97, "civil": 0.03, "angry": 0.0}, "needs_llm": 0.01}
tool: lookup_order {"order_id": "49555"} error=False

For order 49555, a refund of $31.00 (refund R0912) was issued on 2026-09-22. It can take 5 to 10 business days to appear on your statement.

latency_ms=541 llm_calls=0 llm_cost_usd=0.0000 jev_cost_usd=0.000053  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
