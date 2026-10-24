# timeout

- model: claude-opus-5-5
- date: 2026-10-09
- refund hook: on
- prompt rule ($500): off
- injected failures: lookup_order=timeout

## User

Hi, marcus@example.com. Can you tell me the status of order ORD-2002?

**tool call** `get_customer` `{'email': 'marcus@example.com'}`

**tool call** `lookup_order` `{'order_id': 'ORD-2002'}`

**tool result** `{"customer_id":"C-200","name":"Marcus Oyelaran","email":"marcus@example.com","tier":"plus"}`

**tool error** `{"errorCategory": "transient", "isRetryable": true, "message": "lookup_order: upstream order system timed out after 10s (attempt 1 of 2)"}`

## Agent

Transient error, retryable. Retrying once.

**tool call** `lookup_order` `{'order_id': 'ORD-2002'}`

**tool error** `{"errorCategory": "transient", "isRetryable": false, "message": "lookup_order: upstream order system timed out after 10s (attempt 2 of 2). Retry budget spent: do not call lookup_order again with these inputs. Tell the user the system is unreachable."}`

## Agent

Hi Marcus. I found your account, but I can't get the status of order ORD-2002 right now because our order system isn't responding. I tried twice and both attempts timed out.

This doesn't mean anything is wrong with your order. I just can't see its details at the moment. Please try again a little later and I can look it up for you then.

_stop_reason=end_turn subtype=success turns=4_

