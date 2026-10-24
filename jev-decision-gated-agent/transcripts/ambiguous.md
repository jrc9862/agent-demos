Command: `python pipeline.py --customer C001 "my thing from last week is wrong"`

```
route: LLM_PATH  path: llm+verify  (intent other, needs_llm 0.88, concern_count 1, frustration calm)
triage [jev-1.14.0, 310 ms]: {"intent": "other", "intent_confidence": 0.83, "intent_probabilities": {"order_status": 0.01, "refund_request": 0.13, "refund_status": 0.0, "return_how": 0.0, "billing_dispute": 0.01, "invoice_request": 0.0, "account_change": 0.0, "login_help": 0.0, "other": 0.85}, "concern_count": 1, "concern_probabilities": {"1": 0.99, "2": 0.01, "3": 0.0}, "wants_human": 0.02, "frustration": "calm", "frustration_probabilities": {"calm": 0.8, "civil": 0.2, "angry": 0.0}, "needs_llm": 0.88}
tool: search_orders {"customer_id": "C001", "since": "2026-10-12"} error=False
tool: search_orders {"customer_id": "C001"} error=False
verify #1: {"addresses_all_concerns": 0.74, "promises_unconfirmed": 0.06, "tone_matches_frustration": 0.91} failed=[]

I'm sorry something's wrong. I looked at your account, but I'm not sure yet which order you mean.

You have no orders placed in the last couple of weeks. These are the two most recent:

1. **Order 48213, trail running shoes ($89.00).** Placed October 3 and sent by UPS (tracking 1Z999AA10123456784). It was due October 12, but our system still says "shipped," not "delivered." If it reached you last week, this may be the one.
2. **Order 48377, a water bottle and socks ($42.50).** Placed September 21 and delivered September 25.

To help me fix it, could you tell me:
- **Which order** it is (or whether it's something else, like an order on another account)
- **What's wrong:** for example the wrong item or size, something damaged or missing, or a problem with delivery or tracking

Once I know that, I can look at options like a refund or replacement.

latency_ms=13213 llm_calls=1 llm_cost_usd=0.0204 jev_cost_usd=0.000101  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
