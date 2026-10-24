"""Few-shot examples, rendered into the system prompt.

Two format pairs, per P2.5:
  abstract: inline citations vs numbered bibliography   (reference_count must come from either)
  invoice:  narrative prose vs table
The held-out formats (invoice "email", abstract "sources") are never shown here. Contracts get no
examples: they are the deliberately hard type.
"""
import json
import random

import generate_docs as gd

_SHOWN = {"abstract": ["inline", "bibliography"], "invoice": ["narrative", "table"]}
_NULL_KEY = {"abstract": "sample_size", "invoice": "warranty_date"}


def _example(doc_type: str, fmt: str, want_null: bool) -> tuple[str, dict]:
    rng = random.Random(99)  # separate stream from the corpus, so no example is a corpus document
    fn = gd.abstract if doc_type == "abstract" else gd.invoice
    for i in range(1, 500):
        text, fields, _ = fn(rng, fmt, i)
        if (fields[_NULL_KEY[doc_type]] is None) == want_null and fields.get("category") != "other":
            return text, fields
    raise RuntimeError("no example found")


def examples_block(doc_type: str) -> str:
    if doc_type not in _SHOWN:
        return ""
    parts = ["Worked examples (formats vary; absent fields are null):"]
    for n, fmt in enumerate(_SHOWN[doc_type], 1):
        text, fields = _example(doc_type, fmt, want_null=(n == 1))
        answer = dict(fields, confidence={k: 0.95 for k in fields})
        parts.append(f"--- Example {n} ({fmt}) ---\nDOCUMENT:\n{text}\nEXTRACT CALL INPUT:\n{json.dumps(answer)}")
    return "\n".join(parts)
