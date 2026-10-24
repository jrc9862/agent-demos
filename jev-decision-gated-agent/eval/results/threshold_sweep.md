# Threshold sweep

60 labeled messages, 1800 combinations (full grid: `threshold_sweep_full.csv`). `wrong fast`: fast path taken when the label intent differs from the template taken, is multi-concern, wants a human, or is labeled `template_ok: false`. `wrong esc`: escalated when the label wants no human. `missed esc`: label wants a human, route is not ESCALATE. 720 combinations have zero wrong fast paths and zero wrong escalations.

## Chosen constants

- `INTENT_CONFIDENCE_MIN` = 0.80
- `NEEDS_LLM_FAST_MAX` = 0.40
- `WANTS_HUMAN_ESCALATE` = 0.50

Routing: fast 23.3%, escalate 13.3%, LLM 63.3%; templates {'account_change': 5, 'invoice_request': 1, 'login_help': 2, 'order_status': 5, 'return_how': 1}; wrong fast 0, wrong escalations 0, missed escalations 0.

## Pareto front (top 20)

Combinations with margin below 0.05 rank last; the rest by non-LLM share, fewest missed escalations, then margin.

| intent_min | fast_max | esc_min | fast | escalate | llm | non-LLM | wrong fast | wrong esc | missed esc | margin |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.80 | 0.40 | 0.50 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.85 | 0.40 | 0.50 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.75 | 0.40 | 0.50 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.80 | 0.40 | 0.55 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.85 | 0.40 | 0.55 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.90 | 0.40 | 0.50 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.80 | 0.40 | 0.60 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.85 | 0.40 | 0.60 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.95 | 0.40 | 0.50 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.75 | 0.40 | 0.55 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.90 | 0.40 | 0.55 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.75 | 0.40 | 0.60 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.80 | 0.40 | 0.65 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.85 | 0.40 | 0.65 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.90 | 0.40 | 0.60 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.95 | 0.40 | 0.55 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.80 | 0.40 | 0.70 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.85 | 0.40 | 0.70 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.95 | 0.40 | 0.60 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |
| 0.75 | 0.40 | 0.65 | 23.3% | 13.3% | 63.3% | 36.7% | 0 | 0 | 0 | 0.040 |

## Nearest messages to each threshold

| threshold | value | message | probability | distance | route | label |
|---|---|---|---|---|---|---|
| INTENT_CONFIDENCE_MIN | 0.80 | m25 | 0.810 | 0.010 | LLM_PATH | other, 1 request(s), wants_human=False |
| INTENT_CONFIDENCE_MIN | 0.80 | m34 | 0.820 | 0.020 | LLM_PATH | other, 1 request(s), wants_human=False |
| INTENT_CONFIDENCE_MIN | 0.80 | m51 | 0.780 | 0.020 | LLM_PATH | billing_dispute, 2 request(s), wants_human=False |
| INTENT_CONFIDENCE_MIN | 0.80 | m24 | 0.870 | 0.070 | LLM_PATH | billing_dispute, 1 request(s), wants_human=False |
| NEEDS_LLM_FAST_MAX | 0.40 | m14 | 0.400 | 0.000 | LLM_PATH | refund_request, 1 request(s), wants_human=False |
| NEEDS_LLM_FAST_MAX | 0.40 | m18 | 0.410 | 0.010 | LLM_PATH | refund_request, 1 request(s), wants_human=False |
| NEEDS_LLM_FAST_MAX | 0.40 | m46 | 0.380 | 0.020 | LLM_PATH | refund_request, 2 request(s), wants_human=False |
| NEEDS_LLM_FAST_MAX | 0.40 | m27 | 0.360 | 0.040 | FAST_PATH | account_change, 1 request(s), wants_human=False |
| WANTS_HUMAN_ESCALATE | 0.50 | m42 | 0.880 | 0.380 | ESCALATE | order_status, 1 request(s), wants_human=True |
| WANTS_HUMAN_ESCALATE | 0.50 | m39 | 0.910 | 0.410 | ESCALATE | refund_request, 1 request(s), wants_human=True |
| WANTS_HUMAN_ESCALATE | 0.50 | m56 | 0.950 | 0.450 | ESCALATE | order_status, 3 request(s), wants_human=True |
| WANTS_HUMAN_ESCALATE | 0.50 | m35 | 0.040 | 0.460 | LLM_PATH | other, 1 request(s), wants_human=False |
