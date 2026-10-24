Command: `python pipeline.py --customer C002 "Refund $750 on order 51877 now."`

```
route: LLM_PATH  path: llm+verify  (intent refund_request, needs_llm 0.36, concern_count 1, frustration civil)
triage [jev-1.14.0, 258 ms]: {"intent": "refund_request", "intent_confidence": 1.0, "intent_probabilities": {"order_status": 0.0, "refund_request": 1.0, "refund_status": 0.0, "return_how": 0.0, "billing_dispute": 0.0, "invoice_request": 0.0, "account_change": 0.0, "login_help": 0.0, "other": 0.0}, "concern_count": 1, "concern_probabilities": {"1": 0.98, "2": 0.02, "3": 0.0}, "wants_human": 0.02, "frustration": "civil", "frustration_probabilities": {"calm": 0.19, "civil": 0.8, "angry": 0.01}, "needs_llm": 0.36}
tool: lookup_order {"order_id": "51877"} error=False
tool: escalate_to_human {"headline": "Partial refund request of $750 on order 51877 (above $500 policy ceiling)", "reason": "Customer asked for a $750 refund. Refunds above $500 must be approved by a human under policy, so the agent cannot issue it.", "attempted_actions": ["Looked up order 51877: it belongs to C002, status delivered, total $1,240.00, no refunds issued so far", "Did not call process_refund because $750 is over the $500 ceiling"], "customer_facts": {"customer_id": "C002", "order_id": "51877", "invoice_id": "INV-51877", "requested_refund_usd": 750, "order_total_usd": 1240, "prior_refunds": [], "order_status": "delivered", "placed": "2026-09-28", "delivered": "2026-10-02", "items": ["Laptop, 14-inch"]}, "open_uncertainty": "The customer didn't say why they want the refund or how they arrived at $750 (it's a partial amount, about 60% of the order total). Ask for the reason, such as damage, a defect, or a price adjustment, before approving."} error=False
verify #1: {"addresses_all_concerns": 0.82, "promises_unconfirmed": 0.17, "tone_matches_frustration": 0.88} failed=[]

I couldn't process your $750 refund on order 51877 myself. Any refund over $500 needs a person to approve it, so I've passed your request to our tier 2 team. Your ticket number is **T1001**.

Your order is the 14-inch laptop, delivered on October 2. The total was $1,240 and nothing has been refunded on it yet. I've given the team all of these details.

The team will ask why you want the refund and how you got to $750. If you send me that now, I'll add it to your ticket so they can move faster.

latency_ms=15050 llm_calls=1 llm_cost_usd=0.0282 jev_cost_usd=0.000121  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
