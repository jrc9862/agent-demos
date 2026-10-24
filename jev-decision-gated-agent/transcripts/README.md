# Transcripts

Stdout of `pipeline.py` runs (Jev `jev-1.14.0`; LLM `claude-opus-5-5` where the path uses it),
one command per file, at the current gate thresholds. All runs append to `logs/decisions.jsonl`.

| File | Command | Route / path | Model |
|------|---------|--------------|-------|
| `fast.md` | `python pipeline.py "Where is order 48213?"` | FAST_PATH / fast | Jev only |
| `escalate.md` | `python pipeline.py --customer C001 "I want to talk to a person"` | ESCALATE / escalate | Jev only |
| `account_change.md` | `python pipeline.py --customer C001 "Please change my shipping address to 77 Elm St, Boise ID."` | FAST_PATH / fast | Jev only |
| `return_how.md` | `python pipeline.py --customer C001 "How do I return the socks for a refund?"` | FAST_PATH / fast | Jev only |
| `login_help.md` | `python pipeline.py --customer C001 "I can't log in, it says my password is wrong."` | FAST_PATH / fast | Jev only |
| `invoice_request.md` | `python pipeline.py --customer C001 "Can I get an invoice for my last purchase for my expense report?"` | FAST_PATH / fast | Jev only |
| `refund_status_issued.md` | `python pipeline.py --customer C003 "Did my refund for order 49555 go through?"` | FAST_PATH / fast | Jev only |
| `refund_status_none.md` | `python pipeline.py --customer C001 "Did my refund for order 48377 go through?"` | FAST_PATH / fast, then escalate | Jev only |
| `bundled.md` | `python pipeline.py --customer C001 "<refund + address>"` | LLM_PATH / llm+verify | Jev, `claude-opus-5-5` |
| `ambiguous.md` | `python pipeline.py --customer C001 "my thing from last week is wrong"` | LLM_PATH / llm+verify | Jev, `claude-opus-5-5` |
| `refund_750.md` | `python pipeline.py --customer C002 "Refund $750 on order 51877 now."` | LLM_PATH / llm+verify | Jev, `claude-opus-5-5` |
| `angry_status.md` | `python pipeline.py "This is ridiculous!! Where is order 48213?"` | LLM_PATH / llm+verify | Jev, `claude-opus-5-5` |
| `baseline_bundled.md` | `python pipeline.py --baseline --customer C001 "<refund + address>"` | LLM_PATH / llm | `claude-opus-5-5` |
