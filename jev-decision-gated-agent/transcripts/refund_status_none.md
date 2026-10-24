Command: `python pipeline.py --customer C001 "Did my refund for order 48377 go through?"`

```
route: FAST_PATH  path: fast  template: refund_status  (intent refund_status (1.00), needs_llm 0.01 < 0.95, 1 request, frustration calm)
triage [jev-1.14.0, 245 ms]: {"intent": "refund_status", "intent_confidence": 1.0, "intent_probabilities": {"order_status": 0.0, "refund_request": 0.0, "refund_status": 1.0, "return_how": 0.0, "billing_dispute": 0.0, "invoice_request": 0.0, "account_change": 0.0, "login_help": 0.0, "other": 0.0}, "concern_count": 1, "concern_probabilities": {"1": 0.99, "2": 0.01, "3": 0.0}, "wants_human": 0.02, "frustration": "calm", "frustration_probabilities": {"calm": 0.96, "civil": 0.04, "angry": 0.0}, "needs_llm": 0.01}
tool: lookup_order {"order_id": "48377"} error=False
tool: escalate_to_human {"headline": "No refund on record for order 48377", "reason": "customer asked about a refund the system does not show", "attempted_actions": [], "customer_facts": {"customer_id": "C001", "order_ids": ["48377"], "message": "Did my refund for order 48377 go through?"}, "open_uncertainty": "none; handled by a fixed template"} error=False

I don't see a refund on record for order 48377. A refund request goes to our team for review. I've passed this to a member of our support team (ticket T1001). They have the details and will contact you directly.

latency_ms=246 llm_calls=0 llm_cost_usd=0.0000 jev_cost_usd=0.000054  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
