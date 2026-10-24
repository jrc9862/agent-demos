Command: `python pipeline.py --customer C001 "I can't log in, it says my password is wrong."`

```
route: FAST_PATH  path: fast  template: login_help  (intent login_help (1.00), needs_llm 0.03 < 0.95, 1 request, frustration calm)
triage [jev-1.14.0, 761 ms]: {"intent": "login_help", "intent_confidence": 1.0, "intent_probabilities": {"order_status": 0.0, "refund_request": 0.0, "refund_status": 0.0, "return_how": 0.0, "billing_dispute": 0.0, "invoice_request": 0.0, "account_change": 0.0, "login_help": 1.0, "other": 0.0}, "concern_count": 1, "concern_probabilities": {"1": 0.99, "2": 0.01, "3": 0.0}, "wants_human": 0.02, "frustration": "calm", "frustration_probabilities": {"calm": 0.86, "civil": 0.14, "angry": 0.0}, "needs_llm": 0.03}

To reset your password, choose Forgot password on the sign-in page and enter the email on your account. We send a reset link that is valid for one hour. If nothing arrives in ten minutes, check your spam folder, then request a new link.

latency_ms=762 llm_calls=0 llm_cost_usd=0.0000 jev_cost_usd=0.000054  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
