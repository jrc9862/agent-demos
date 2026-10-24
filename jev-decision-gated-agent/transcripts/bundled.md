Command: `python pipeline.py --customer C001 "I want a refund for order 48377 and please also update my shipping address to 9 Oak Ln."`

```
route: LLM_PATH  path: llm+verify  (intent refund_request, needs_llm 0.38, concern_count 2, frustration calm)
triage [jev-1.14.0, 300 ms]: {"intent": "refund_request", "intent_confidence": 1.0, "intent_probabilities": {"order_status": 0.0, "refund_request": 1.0, "refund_status": 0.0, "return_how": 0.0, "billing_dispute": 0.0, "invoice_request": 0.0, "account_change": 0.0, "login_help": 0.0, "other": 0.0}, "concern_count": 2, "concern_probabilities": {"1": 0.0, "2": 1.0, "3": 0.0}, "wants_human": 0.02, "frustration": "calm", "frustration_probabilities": {"calm": 0.97, "civil": 0.03, "angry": 0.0}, "needs_llm": 0.38}
tool: lookup_order {"order_id": "48377"} error=False
tool: get_customer {"customer_id": "C001"} error=False
tool: process_refund {"order_id": "48377", "amount": 42.5, "reason": "Customer requested refund for delivered order"} error=False
tool: escalate_to_human {"headline": "Shipping address update request for C001 (Dana Ruiz): no address-update tool available", "reason": "Customer asked to change their shipping address. The support agent has no tool that can edit a customer profile, so a human needs to make the change.", "attempted_actions": ["Fetched customer profile C001 to confirm the current address", "Refunded order 48377 in full ($42.50, refund R1001, status issued). This was the customer's other request and is finished", "No address change made: no tool exists for it"], "customer_facts": {"customer_id": "C001", "name": "Dana Ruiz", "email": "dana@example.com", "current_address": "14 Alder St, Portland, OR 97205", "requested_new_address": "9 Oak Ln", "related_order": "48377 (delivered 2026-09-25, refunded $42.50, refund R1001)"}, "open_uncertainty": "The customer only gave '9 Oak Ln', with no city, state or ZIP. It may be in Portland, OR 97205, but that hasn't been confirmed. Check the full address with the customer before saving it."} error=False
verify #1: {"addresses_all_concerns": 0.97, "promises_unconfirmed": 0.18, "tone_matches_frustration": 0.92} failed=[]

Hi Dana, I've refunded your order, but I couldn't change your address myself, so a team member will handle it.

**1. Refund for order 48377: done**
I've refunded the full $42.50 for the water bottle and socks. The refund ID is **R1001** and its status is "issued." It should reach your original payment method soon. Your bank decides exactly when it shows up.

**2. Shipping address change: passed to a team member**
I don't have a way to edit addresses, so I opened ticket **T1002** with our tier 2 team. I haven't changed anything yet, so your saved address is still 14 Alder St, Portland, OR 97205.

One thing would help: you gave "9 Oak Ln" but didn't include the city, state or ZIP. If you reply with the full address, the team can update it without having to contact you first.

latency_ms=23938 llm_calls=1 llm_cost_usd=0.0497 jev_cost_usd=0.000132  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
