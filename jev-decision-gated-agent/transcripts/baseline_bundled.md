Command: `python pipeline.py --baseline --customer C001 I want a refund for order 48377 and please also update my shipping address to 9 Oak Ln.`

```
route: LLM_PATH  path: llm  (baseline)
tool: lookup_order {"order_id": "48377"} error=False
tool: get_customer {"customer_id": "C001"} error=False
tool: process_refund {"order_id": "48377", "amount": 42.5, "reason": "Customer requested refund for delivered order (Water bottle, Socks)"} error=False
tool: escalate_to_human {"headline": "Shipping address update request for C001 (Dana Ruiz)", "reason": "Customer asked to change their shipping address. The support tools can't edit customer profiles, so a human needs to make the change.", "attempted_actions": ["Looked up customer profile C001 to confirm the current address", "No address-update tool is available, so the change was not made"], "customer_facts": {"customer_id": "C001", "name": "Dana Ruiz", "email": "dana@example.com", "current_address": "14 Alder St, Portland, OR 97205", "requested_new_address": "9 Oak Ln", "related_request": "Refund requested on order 48377 ($42.50), handled separately"}, "open_uncertainty": "The customer only gave '9 Oak Ln'. City, state and ZIP weren't given, so we don't know whether it's still Portland, OR 97205. Please confirm the full address with the customer before updating."} error=False

Hi Dana, I've handled the refund, and your address change has gone to a teammate.

**1. Refund for order 48377: done**
I refunded the full $42.50 for your water bottle and socks. Your refund ID is **R1001** if you need to refer to it.

**2. Shipping address: passed to a teammate**
I can't edit account details myself, so I opened ticket **T1002** for a support agent to update it. **Your address on file is still 14 Alder St, Portland, OR 97205.**

You gave "9 Oak Ln" without a city, state or ZIP code. Please reply with the full address, or tell me if it's still Portland, OR 97205. That way the agent can update it correctly.

latency_ms=19058 llm_calls=1 llm_cost_usd=0.0385 jev_cost_usd=0.000000  log: /home/james/Coding Projects/agent-demos/jev-decision-gated-agent/logs/decisions.jsonl
```
