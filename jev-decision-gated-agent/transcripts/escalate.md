Command: `python pipeline.py --customer C001 "I want to talk to a person"`

```
route: ESCALATE  path: escalate  (wants_human 0.96 > 0.5)
triage [jev-1.14.0, 248 ms]: {"intent": "other", "intent_confidence": 1.0, "intent_probabilities": {"order_status": 0.0, "refund_request": 0.0, "refund_status": 0.0, "return_how": 0.0, "billing_dispute": 0.0, "invoice_request": 0.0, "account_change": 0.0, "login_help": 0.0, "other": 1.0}, "concern_count": 1, "concern_probabilities": {"1": 0.99, "2": 0.01, "3": 0.0}, "wants_human": 0.96, "frustration": "calm", "frustration_probabilities": {"calm": 0.92, "civil": 0.08, "angry": 0.0}, "needs_llm": 0.88}
tool: escalate_to_human {"reason": "customer asked for a human (wants_human 0.96 > 0.5)"} error=False

I've passed this to a member of our support team (ticket T1001). They have the details and will contact you directly.

latency_ms=249 llm_calls=0 llm_cost_usd=0.0000 jev_cost_usd=0.000053  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
