Command: `python pipeline.py "This is ridiculous!! Where is order 48213?"`

```
route: LLM_PATH  path: llm+verify  (intent order_status, needs_llm 0.06, concern_count 1, frustration angry)
triage [jev-1.14.0, 295 ms]: {"intent": "order_status", "intent_confidence": 1.0, "intent_probabilities": {"order_status": 1.0, "refund_request": 0.0, "refund_status": 0.0, "return_how": 0.0, "billing_dispute": 0.0, "invoice_request": 0.0, "account_change": 0.0, "login_help": 0.0, "other": 0.0}, "concern_count": 1, "concern_probabilities": {"1": 0.99, "2": 0.01, "3": 0.0}, "wants_human": 0.02, "frustration": "angry", "frustration_probabilities": {"calm": 0.0, "civil": 0.21, "angry": 0.79}, "needs_llm": 0.06}
tool: lookup_order {"order_id": "48213"} error=False
verify #1: {"addresses_all_concerns": 0.93, "promises_unconfirmed": 0.15, "tone_matches_frustration": 0.9} failed=[]

I'm sorry about this. You have every reason to be frustrated. Your order should have reached you by October 12, and it's now 11 days late.

**Order 48213: Trail running shoes ($89.00)**
- **Ordered:** October 3, 2026
- **Status:** Shipped with UPS
- **Tracking number:** 1Z999AA10123456784
- **Expected delivery:** October 12, 2026

Our system still shows the order as shipped, not delivered. That means UPS hasn't marked it as delivered. I can't see UPS's own updates from here, so please put the tracking number into ups.com to check where the package was last scanned.

Here's what I can do next:
1. **Pass this to a team member** who can open an investigation with UPS about the late package.
2. **Look at a refund** if the package turns out to be lost.

Which would you like? Or, if UPS's tracking says it was delivered but you never got it, tell me and I'll take it from there.

latency_ms=16485 llm_calls=1 llm_cost_usd=0.0162 jev_cost_usd=0.000091  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
