# extraction-pipeline

Schema-constrained extraction guarantees the JSON has the right shape, not that it is true. This
demo adds a semantic validator, retries that carry the specific error, nullable fields for
information the document does not contain, a Batches path for bulk work, and an accuracy report
stratified by document type.

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # Python 3.11+
pip install -r requirements.txt
cp .env.example .env && set -a && . ./.env && set +a    # sets ANTHROPIC_API_KEY
python -m pytest -q                                     # offline, mocked client, no key needed
```

Model: `claude-opus-5-5`. `anthropic>=1.13,<2`. No thinking parameter, no prefill.

## Corpus

`python generate_docs.py` rewrites `docs/` (100 synthetic text documents, fixed seed) and
`docs/truth.json` (ground truth).

| Type | Count | Formats | Notes |
|------|-------|---------|-------|
| invoice | 40 | narrative, table, email | email is held out of the few-shot examples. 5 invoices print a total that disagrees with their own line items. About 25% have a warranty date; the rest have none. 12 use a category outside the enum. |
| abstract | 30 | inline citations, bibliography, sources | sources is held out. `sample_size` is sometimes absent. |
| contract | 30 | numbered clauses, letter | The hard type. Terms are spelled out in words, and amendments override earlier clauses, so the correct value is the amended one. No few-shot examples. |

Field descriptions in `schema.py` pin the output form where more than one is plausible, for
example `governing_law` is the bare jurisdiction name (`"Oregon"`, not `"State of Oregon"`).

## Single document

```bash
python extract.py docs/inv-002.txt   # no warranty in the document -> warranty_date: null
python extract.py docs/inv-004.txt   # category outside the enum  -> category: "other", other_detail: "..."
python extract.py docs/inv-008.txt   # printed total is wrong     -> retry, then unresolvable with a reason
```

- inv-002: `"warranty_date": null`, 1 call, status `accepted`.
- inv-004: `"category": "other"` with `other_detail` naming the category, 1 call, `accepted`.
- inv-008: status `unresolvable`. The message is
  `stated_total 6297.76 != subtotal 5791.00 + tax 477.76 = 6268.76.` The model returns the same
  extraction on retry, which ends the loop.

Flow: `build_params` -> `messages.create` -> `parse_response` -> `validate` -> retry, which sends the
document, the failed JSON, and each failing check. Outcomes: `accepted`, `resolved`,
`unresolvable`, `refused`, `error`. A value for a field whose keyword is absent from the source is
not retried; an identical output on retry ends the loop.

### tool_choice

The tool is defined with `strict: true` and called with `tool_choice: auto`. `claude-opus-5-5`
returns 400 for forced `tool_choice` (`any` and `{"type":"tool"}`). `strict: true` guarantees the
call matches the schema, and the system prompt says to call `extract` exactly once. If the model
answers in prose anyway, `parse_response` raises `NoToolCall` and the loop retries.

## Bulk (Message Batches)

```bash
python batch.py run              # all 100 docs; --limit N takes N docs round-robin across types
python review_router.py          # accuracy report + review queue from results/extractions.json
```

`custom_id` is the document id; results are matched by it, never by position. Round 1 submits
everything. Round 2 resubmits errored/expired documents and those with retryable validation
errors (error text attached, since Batches has no multi-turn). `invalid_request` errors and
refusals are not resubmitted. `results/batch_ledger.json` records `round1` as `succeeded`,
`errored`, or `resubmitted` for every id, plus a `final` status. `run` asserts zero orphans.

**SLA arithmetic.** Worst case per round is `submit interval + 24h`. With one resubmit round,
`interval = SLA - 48h`: a 72-hour SLA needs a submission every 24 hours, 48 hours leaves no slack,
24 hours cannot be met. Request-path work stays on `extract.py`. The saving is 50% of token cost.

## Counter-demo

```bash
python extract.py --counter-demo   # writes results/counter_demo_transcript.json
```

Three invoices with no warranty date (inv-002, inv-003, inv-006), each run three ways:

1. Naive: schema without nullable fields, validator without the absent-from-source check.
2. Naive plus the check, retrying on every error, 5 retries.
3. This pipeline: nullable schema, stop on absent information.

The committed transcript shows the naive variants (1 and 2) returning the string `"null"` on
all 6 attempts per invoice. The output never changes, so variant 2 spends every retry on it. The
pipeline returns JSON `null` in 1 call with status `accepted`. A non-nullable schema turns an
absent value into a guaranteed validation failure that no retry can fix, because the correct
answer is not expressible.

## Accuracy

`python batch.py run --limit 30` (stratified, 10 per type), then `python review_router.py`.
29 documents succeed in round 1; inv-008 is resubmitted and ends `unresolvable`. Zero orphans.

Aggregate field accuracy: 99.6% (239/240).

| type | accuracy |
|---|---|
| abstract | 100.0% (70/70) |
| contract | 98.6% (69/70) |
| invoice | 100.0% (100/100) |

The one wrong field is `auto_renew` on con-007 (`null` returned, `true` expected), routed to the
review queue at confidence 0.5. The queue holds 4 entries: `auto_renew` on con-007 and con-010,
and inv-008 (unresolvable, `stated_total`).

## Why stratify

The aggregate is dominated by the easy types and hides gaps in the hard one. Report by type and
field, and sample by type when monitoring.
