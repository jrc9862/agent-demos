# human

- model: claude-opus-5-5
- date: 2026-10-09
- refund hook: on
- prompt rule ($500): off
- injected failures: none

## User

I don't want to talk to a bot. Get me a human.

**tool call** `escalate_to_human` `{'headline': 'Customer asked for a human agent right away', 'reason': "The customer asked to speak with a human at the start of the conversation and said they don't want to talk to a bot. Following policy, this was handed off right away without any other resolution attempts.", 'attempted_actions': ['None. The case was escalated right away because the customer asked for a human. No customer lookup, order lookup, or refund was attempted.'], 'customer_facts': {}, 'open_uncertainty': "The customer didn't say what the issue is, and they haven't been identified with a tool yet, so there is no customer ID, order ID, amount, or date. The human agent needs to confirm who the customer is and what they need."}`

**tool result** `{"ticket_id":"ESC-0001","queue":"tier2","message":"A human agent will follow up with the customer."}`

## Agent

I've passed your request to a human agent, and someone from our support team will follow up with you. Your ticket number is **ESC-0001**.

I didn't look up your account or any orders first. When the agent contacts you, please tell them what you need help with, plus any order numbers you have.

_stop_reason=end_turn subtype=success turns=2_

