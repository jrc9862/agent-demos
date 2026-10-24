"""Jev triage vs LLM self-reported confidence, on the same labeled messages.

For each of three questions (intent, wants_human, concern_count) and each classifier: accuracy,
and a calibration table of predicted-confidence bucket vs observed accuracy. A classifier is
well calibrated when, in every bucket, observed accuracy is close to mean confidence.

    python eval/run_eval.py                 # both; needs TYPESAFE_API_KEY and ANTHROPIC_API_KEY
    python eval/run_eval.py --no-llm        # Jev only
    python eval/run_eval.py --no-jev        # LLM only
    python eval/run_eval.py --fake-jev --no-llm   # harness smoke test; prints, writes nothing

"Confidence" here means the probability the classifier assigns to the answer it chose: Jev's
`probabilities[choice]` for intent, max(noul, 1 - noul) for wants_human, and the argmax level's
probability for concern_count; for the LLM, the 0-1 number it reports for each answer. This is
deliberately NOT Jev's Choice/Score `.confidence`, which measures how concentrated the
distribution is, not P(correct); comparing that to accuracy would not be like with like.
Labels: `intent` is what the customer's first request is about; concern_count 3 means "3 or more".
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from jev_client import make_client  # noqa: E402
from triage import INTENT_QUESTION, INTENTS, TriageResult, triage  # noqa: E402
from typesafe_sdk import TypeSafeError  # noqa: E402

LLM_MODEL = "claude-opus-5-5"
QUESTIONS = ("intent", "wants_human", "concern_count")
BUCKET_EDGES = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)

LLM_PROMPT = """Classify this customer support message.

intent: {intent_question} One of:
{intents}
wants_human: true if the customer explicitly asks to talk to a human agent.
concern_count: how many distinct requests the message contains ("1", "2", or "3+").

For each answer, give a confidence from 0 to 1: the probability that your answer is correct.

Message:
{message}"""


class LLMTriage(BaseModel):
    intent: Literal[tuple(INTENTS)]
    intent_confidence: float
    wants_human: bool
    wants_human_confidence: float
    concern_count: Literal["1", "2", "3+"]
    concern_count_confidence: float


Prediction = dict[str, tuple[object, float]]  # question -> (answer, confidence)


def load_messages(path: Path = HERE / "messages.jsonl") -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def jev_prediction(t: TriageResult) -> Prediction:
    return {"intent": (t.intent, t.intent_probabilities[t.intent]),
            "wants_human": (t.wants_human > 0.5, max(t.wants_human, 1 - t.wants_human)),
            "concern_count": (t.concern_count, t.concern_probabilities[t.concern_count])}


def jev_triage(client, message: str) -> TriageResult | None:
    try:
        return triage(client, message)
    except TypeSafeError as err:
        print(f"  Jev error: {err}", file=sys.stderr)
        return None


def llm_predict(client: anthropic.Anthropic, message: str) -> Prediction | None:
    """None when the model refuses or the call fails; the caller counts these."""
    # The same definition and contrast text Jev's Choice criteria carry.
    intents = "\n".join(f"- {k}: {v['definition']} {v['contrast']}" for k, v in INTENTS.items())
    try:
        response = client.messages.parse(
            model=LLM_MODEL, max_tokens=2000, output_format=LLMTriage,
            messages=[{"role": "user", "content": LLM_PROMPT.format(
                intent_question=INTENT_QUESTION, intents=intents, message=message)}])
    except anthropic.AuthenticationError:
        raise
    except anthropic.RateLimitError as err:
        print(f"  rate limited after SDK retries: {err.message}", file=sys.stderr)
        return None
    except anthropic.APIStatusError as err:
        print(f"  API error {err.status_code}: {err.message}", file=sys.stderr)
        return None
    except anthropic.APIConnectionError as err:
        print(f"  connection error: {err}", file=sys.stderr)
        return None
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        print(f"  no classification (stop_reason={response.stop_reason})", file=sys.stderr)
        return None
    p = response.parsed_output
    clamp = lambda x: min(max(x, 0.0), 1.0)  # noqa: E731
    return {"intent": (p.intent, clamp(p.intent_confidence)),
            "wants_human": (p.wants_human, clamp(p.wants_human_confidence)),
            "concern_count": (3 if p.concern_count == "3+" else int(p.concern_count),
                              clamp(p.concern_count_confidence))}


def score(messages: list[dict], predictions: list[Prediction | None]) -> dict[str, list[tuple[float, bool]]]:
    """question -> [(confidence, correct)], skipping failed predictions."""
    records = {q: [] for q in QUESTIONS}
    for msg, pred in zip(messages, predictions):
        if pred is None:
            continue
        for q in QUESTIONS:
            answer, confidence = pred[q]
            records[q].append((confidence, answer == msg[q]))
    return records


def calibration_table(records: list[tuple[float, bool]], edges=BUCKET_EDGES) -> list[dict]:
    """Bucket by confidence; the last bucket is closed on the right so 1.0 lands in it."""
    rows = []
    for i, (lo, hi) in enumerate(zip(edges, edges[1:])):
        last = i == len(edges) - 2
        inside = [(c, ok) for c, ok in records if lo <= c < hi or (last and c == hi)]
        n = len(inside)
        rows.append({"bucket": f"{lo:.1f}-{hi:.1f}", "n": n,
                     "mean_confidence": sum(c for c, _ in inside) / n if n else None,
                     "accuracy": sum(ok for _, ok in inside) / n if n else None})
    return rows


def expected_calibration_error(rows: list[dict]) -> float | None:
    total = sum(r["n"] for r in rows)
    if not total:
        return None
    return sum(r["n"] * abs(r["mean_confidence"] - r["accuracy"]) for r in rows if r["n"]) / total


def render(name: str, records: dict[str, list[tuple[float, bool]]]) -> str:
    out = [f"## {name}\n"]
    for q in QUESTIONS:
        recs = records[q]
        acc = sum(ok for _, ok in recs) / len(recs) if recs else float("nan")
        rows = calibration_table(recs)
        ece = expected_calibration_error(rows)
        out.append(f"### {q}: accuracy {acc:.1%} (n={len(recs)}), ECE "
                   f"{'n/a' if ece is None else f'{ece:.3f}'}\n")
        out.append("| confidence bucket | n | mean confidence | observed accuracy |\n|---|---|---|---|")
        for r in rows:
            fmt = lambda x: "-" if x is None else f"{x:.2f}"  # noqa: E731
            out.append(f"| {r['bucket']} | {r['n']} | {fmt(r['mean_confidence'])} | {fmt(r['accuracy'])} |")
        out.append("")
    return "\n".join(out)


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-jev", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--fake-jev", action="store_true", help="uncalibrated fake; output is not saved")
    ap.add_argument("--limit", type=int, help="first N messages only")
    args = ap.parse_args()
    messages = load_messages()[: args.limit]
    sections, meta = [], {"date": datetime.now(timezone.utc).isoformat(), "n_messages": len(messages)}

    if not args.no_jev:
        jev = make_client(fake=args.fake_jev)
        results = [jev_triage(jev, m["text"]) for m in messages]
        preds = [jev_prediction(t) if t else None for t in results]
        meta["jev_model"] = next((t.jev_model for t in results if t), "unknown")
        meta["jev_failures"] = sum(t is None for t in results)
        label = "FAKE Jev (keyword heuristic, NOT calibration data)" if args.fake_jev else "Jev"
        sections.append(render(f"{label} ({meta['jev_model']})", score(messages, preds)))
    if not args.no_llm:
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            raise SystemExit("ANTHROPIC_API_KEY is not set (or pass --no-llm).")
        client = anthropic.Anthropic()
        preds = [llm_predict(client, m["text"]) for m in messages]
        meta["llm_model"], meta["llm_failures"] = LLM_MODEL, sum(p is None for p in preds)
        sections.append(render(f"LLM self-reported confidence ({LLM_MODEL})", score(messages, preds)))

    report = f"# Calibration: Jev vs LLM self-report\n\n```\n{json.dumps(meta, indent=2)}\n```\n\n" + \
             "\n".join(sections)
    print(report)
    if args.fake_jev:
        print("\n[fake Jev: nothing written to eval/results/]")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = HERE / "results" / f"calibration_{stamp}.md"
    path.write_text(report)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
