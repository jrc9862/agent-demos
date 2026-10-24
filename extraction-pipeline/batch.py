"""Bulk path: ~100 documents through the Message Batches API.

Round 1 submits every document. Round 2 resubmits documents that errored, expired, or failed a
retryable validation check, with the validation errors attached. Batches has no multi-turn tool
use, so a "retry" is a second, independent request carrying the failed JSON in its prompt.

Every custom_id is the document id. Results arrive in any order and are matched by custom_id.

Usage: python batch.py run [--limit N]     # submits, polls, reconciles, writes results/extractions.json
"""
import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from extract import (ExtractionError, build_params, initial_prompt, parse_response, retry_prompt)
from validate import validate

HERE = Path(__file__).parent
RESULTS = HERE / "results"
BATCH_WINDOW_HOURS = 24
PREFIX = {"inv": "invoice", "abs": "abstract", "con": "contract"}


def max_submit_interval_hours(sla_hours: float, resubmit_rounds: int = 1) -> float:
    """Longest gap between batch submissions that still meets an end-to-end SLA.

    A document can arrive just after a submission (waits one full interval), then spends up to
    24h in its batch, and again in each resubmission round. Negative or zero means batch cannot
    meet the SLA at all.
    """
    return sla_hours - BATCH_WINDOW_HOURS * (1 + resubmit_rounds)


@dataclass
class Outcome:
    kind: str                    # succeeded | errored | canceled | expired
    data: dict | None = None
    error: str = ""
    retryable_api_error: bool = True


def select_paths(paths: list[Path], limit: int | None) -> list[Path]:
    """Take `limit` paths round-robin across document types, in filename order within each type.

    Sorting alone would take the first N of one type (abstracts sort first), hiding the per-type
    comparison. limit=10 over three types gives 4/3/3; None returns everything.
    """
    if limit is None:
        return paths
    by_type: dict[str, list[Path]] = {}
    for p in paths:
        by_type.setdefault(PREFIX[p.stem[:3]], []).append(p)
    queues = [by_type[t] for t in ("invoice", "abstract", "contract") if t in by_type]
    picked: list[Path] = []
    for rank in range(max((len(q) for q in queues), default=0)):
        for q in queues:
            if rank < len(q) and len(picked) < limit:
                picked.append(q[rank])
    return sorted(picked)


def load_corpus(limit: int | None = None) -> dict[str, tuple[str, str]]:
    paths = select_paths(sorted((HERE / "docs").glob("*.txt")), limit)
    return {p.stem: (PREFIX[p.stem[:3]], p.read_text()) for p in paths}


def build_requests(corpus: dict, prompts: dict[str, str]) -> list[Request]:
    return [Request(custom_id=i, params=MessageCreateParamsNonStreaming(**build_params(corpus[i][0], prompts[i])))
            for i in prompts]


def wait(client, batch_id: str, poll_seconds: int = 60):
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return batch
        print(f"  {batch_id}: {batch.request_counts.processing} processing")
        time.sleep(poll_seconds)


def collect(client, batch_id: str) -> dict[str, Outcome]:
    out: dict[str, Outcome] = {}
    for entry in client.messages.batches.results(batch_id):
        r = entry.result
        if r.type == "succeeded":
            try:
                out[entry.custom_id] = Outcome("succeeded", data=parse_response(r.message))
            except ExtractionError as e:  # refusal, truncation, or prose instead of a tool call
                out[entry.custom_id] = Outcome("errored", error=f"{type(e).__name__}: {e}", retryable_api_error=False)
        elif r.type == "errored":
            # invalid_request will fail identically on resubmit; everything else is transient.
            out[entry.custom_id] = Outcome("errored", error=r.error.type,
                                           retryable_api_error=r.error.type != "invalid_request")
        else:  # canceled | expired
            out[entry.custom_id] = Outcome(r.type)
    return out


def reconcile(expected: set[str], outcomes: dict[str, Outcome]) -> tuple[set[str], set[str]]:
    """Return (orphans, strangers): ids submitted with no result, ids returned that we never sent."""
    return expected - outcomes.keys(), outcomes.keys() - expected


def triage(corpus: dict, outcomes: dict[str, Outcome]) -> tuple[dict, dict]:
    """Split round-1 outcomes into final records and prompts for round 2."""
    final, resubmit = {}, {}
    for i, o in outcomes.items():
        doc_type, text = corpus[i]
        if o.kind == "succeeded":
            issues = validate(doc_type, o.data, text)
            if not issues:
                final[i] = {"status": "succeeded", "data": o.data}
            elif all(x.retryable for x in issues):
                resubmit[i] = retry_prompt(text, o.data, issues)
            else:
                final[i] = {"status": "unresolvable", "data": o.data,
                            "reason": "; ".join(x.message for x in issues if not x.retryable)}
        elif o.retryable_api_error:
            resubmit[i] = initial_prompt(text)
        else:
            final[i] = {"status": "errored", "reason": o.error}
    return final, resubmit


def run(client, limit: int | None) -> dict:
    RESULTS.mkdir(exist_ok=True)
    corpus = load_corpus(limit)
    ledger = {i: {"doc_type": corpus[i][0], "round1": None, "final": None} for i in corpus}

    b1 = client.messages.batches.create(requests=build_requests(corpus, {i: initial_prompt(t) for i, (_, t) in corpus.items()}))
    (RESULTS / "batch_state.json").write_text(json.dumps({"round1": b1.id}))
    print(f"round 1: {b1.id} ({len(corpus)} requests)")
    wait(client, b1.id)
    outcomes = collect(client, b1.id)
    orphans, strangers = reconcile(set(corpus), outcomes)
    if strangers:
        raise RuntimeError(f"results for ids we never sent: {sorted(strangers)}")
    for i in orphans:  # no result at all: treat like expired
        outcomes[i] = Outcome("expired")
    final, resubmit = triage(corpus, outcomes)
    for i in corpus:
        status = final[i]["status"] if i in final else None
        ledger[i]["round1"] = "resubmitted" if i in resubmit else "errored" if status == "errored" else "succeeded"
    results = dict(final)

    if resubmit:
        b2 = client.messages.batches.create(requests=build_requests(corpus, resubmit))
        print(f"round 2: {b2.id} ({len(resubmit)} resubmitted)")
        wait(client, b2.id)
        out2 = collect(client, b2.id)
        for i in resubmit:
            o = out2.get(i, Outcome("expired"))
            if o.kind != "succeeded":
                results[i] = {"status": "errored", "reason": o.error or o.kind}
                continue
            issues = validate(corpus[i][0], o.data, corpus[i][1])
            results[i] = ({"status": "resolved", "data": o.data} if not issues else
                          {"status": "unresolvable", "data": o.data, "reason": "; ".join(x.message for x in issues)})
    for i, rec in results.items():
        ledger[i]["final"] = rec["status"]
        rec["doc_type"] = corpus[i][0]
    assert all(v["round1"] and v["final"] for v in ledger.values()), "orphan custom_id"
    (RESULTS / "extractions.json").write_text(json.dumps(results, indent=1) + "\n")
    (RESULTS / "batch_ledger.json").write_text(json.dumps(ledger, indent=1) + "\n")
    return ledger


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["run"])
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    try:
        ledger = run(anthropic.Anthropic(), args.limit)
    except anthropic.AuthenticationError:
        raise SystemExit("ANTHROPIC_API_KEY missing or invalid")
    except anthropic.RateLimitError as e:
        raise SystemExit(f"rate limited: {e}")
    except anthropic.APIStatusError as e:
        raise SystemExit(f"API error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError as e:
        raise SystemExit(f"connection error: {e}")
    counts: dict = {}
    for v in ledger.values():
        key = (v["round1"], v["final"])
        counts[key] = counts.get(key, 0) + 1
    print("round1 -> final:", counts, "| orphans: 0")


if __name__ == "__main__":
    main()
