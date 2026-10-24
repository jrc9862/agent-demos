"""Confidence routing and the per-type, per-field accuracy report.

Usage: python review_router.py [results/extractions.json] [--threshold 0.8] [--gap 0.05]

Any field with confidence below the threshold goes to results/review_queue.jsonl, as does every
document that did not reach an accepted state. The report is stratified by document type because
the aggregate is dominated by the easy types.
"""
import argparse
import json
from pathlib import Path

from schema import FIELDS

HERE = Path(__file__).parent
OK_STATUSES = {"accepted", "succeeded", "resolved"}


def _norm(v):
    if isinstance(v, str):
        return v.strip().casefold()
    if isinstance(v, list):
        return sorted(_norm(x) for x in v)
    return v


def field_correct(pred, truth) -> bool:
    if isinstance(truth, (int, float)) and not isinstance(truth, bool) and isinstance(pred, (int, float)):
        return abs(pred - truth) < 0.01
    return _norm(pred) == _norm(truth)


def route(extractions: dict, threshold: float = 0.8) -> list[dict]:
    queue = []
    for doc_id, rec in extractions.items():
        data = rec.get("data") or {}
        if rec["status"] not in OK_STATUSES:
            queue.append({"doc_id": doc_id, "field": "*", "reason": f"{rec['status']}: {rec.get('reason', '')}"})
        for name in FIELDS[rec["doc_type"]]:
            conf = (data.get("confidence") or {}).get(name)
            if data and (not isinstance(conf, (int, float)) or conf < threshold):
                queue.append({"doc_id": doc_id, "field": name, "value": data.get(name), "confidence": conf,
                              "reason": f"confidence below {threshold}"})
    return queue


def accuracy_report(extractions: dict, truth: dict) -> dict:
    """Return {"cells": {type: {field: [correct, total]}}, "wrong": [(doc_id, field)]}."""
    cells: dict = {}
    wrong = []
    for doc_id, rec in extractions.items():
        doc_type, expected = truth[doc_id]["doc_type"], truth[doc_id]["fields"]
        data = rec.get("data") or {}
        for name, want in expected.items():
            cell = cells.setdefault(doc_type, {}).setdefault(name, [0, 0])
            cell[1] += 1
            if name in data and field_correct(data[name], want):
                cell[0] += 1
            else:
                wrong.append((doc_id, name))
    return {"cells": cells, "wrong": wrong}


def _ratio(pairs) -> tuple[int, int]:
    return sum(p[0] for p in pairs), sum(p[1] for p in pairs)


def format_report(report: dict, queue: list[dict], gap: float = 0.05) -> str:
    cells = report["cells"]
    all_cells = [c for t in cells.values() for c in t.values()]
    agg_c, agg_t = _ratio(all_cells)
    agg = agg_c / agg_t if agg_t else 0.0
    lines = [f"aggregate field accuracy: {agg:.1%} ({agg_c}/{agg_t})", "", "| type | accuracy | note |", "|---|---|---|"]
    for doc_type, fields in sorted(cells.items()):
        c, t = _ratio(fields.values())
        acc = c / t
        note = f"{(agg - acc) * 100:.1f} points below aggregate" if agg - acc >= gap else ""
        lines.append(f"| {doc_type} | {acc:.1%} ({c}/{t}) | {note} |")
    lines += ["", "| type | field | accuracy |", "|---|---|---|"]
    for doc_type, fields in sorted(cells.items()):
        for name, (c, t) in fields.items():
            lines.append(f"| {doc_type} | {name} | {c / t:.0%} ({c}/{t}) |")
    routed = {(q["doc_id"], q["field"]) for q in queue}
    routed_docs = {q["doc_id"] for q in queue if q["field"] == "*"}
    wrong = report["wrong"]
    caught = sum(1 for d, f in wrong if (d, f) in routed or d in routed_docs)
    lines += ["", f"review queue: {len(queue)} entries; {caught}/{len(wrong)} wrong fields were routed to review"]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("extractions", nargs="?", default=str(HERE / "results" / "extractions.json"))
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--gap", type=float, default=0.05)
    args = ap.parse_args()
    extractions = json.loads(Path(args.extractions).read_text())
    truth = json.loads((HERE / "docs" / "truth.json").read_text())
    queue = route(extractions, args.threshold)
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / "review_queue.jsonl").write_text("".join(json.dumps(q) + "\n" for q in queue))
    text = format_report(accuracy_report(extractions, truth), queue, args.gap)
    (out / "accuracy_report.md").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
