Command: `python pipeline.py --customer C001 "Please change my shipping address to 77 Elm St, Boise ID."`

```
route: FAST_PATH  path: fast  template: account_change  (intent account_change (1.00), needs_llm 0.18 < 0.95, 1 request, frustration calm)
triage [jev-1.14.0, 254 ms]: {"intent": "account_change", "intent_confidence": 1.0, "intent_probabilities": {"order_status": 0.0, "refund_request": 0.0, "refund_status": 0.0, "return_how": 0.0, "billing_dispute": 0.0, "invoice_request": 0.0, "account_change": 1.0, "login_help": 0.0, "other": 0.0}, "concern_count": 1, "concern_probabilities": {"1": 1.0, "2": 0.0, "3": 0.0}, "wants_human": 0.01, "frustration": "calm", "frustration_probabilities": {"calm": 1.0, "civil": 0.0, "angry": 0.0}, "needs_llm": 0.18}
tool: escalate_to_human {"headline": "Account change request: Please change my shipping address to 77 Elm St, Boise ID.", "reason": "account change requested", "attempted_actions": [], "customer_facts": {"customer_id": "C001", "requested_change": "Please change my shipping address to 77 Elm St, Boise ID."}, "open_uncertainty": "none; handled by a fixed template"} error=False

Changes to your address, email, saved card, or subscription are made by our support team, not in chat. I've passed this to a member of our support team (ticket T1001). They have the details and will contact you directly.

latency_ms=255 llm_calls=0 llm_cost_usd=0.0000 jev_cost_usd=0.000054  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
