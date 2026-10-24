"""Set the gate thresholds from labeled data.

    python eval/sweep_thresholds.py            # sweep from the cached probabilities
    python eval/sweep_thresholds.py --refresh  # call Jev once per message (60 calls), then sweep

Raw triage results are cached in eval/results/triage_probs.json, so the sweep is offline and
re-runnable. The grid is INTENT_CONFIDENCE_MIN 0.50-0.95, NEEDS_LLM_FAST_MAX 0.10-0.95 and
WANTS_HUMAN_ESCALATE 0.50-0.95, all step 0.05. Every combination is scored by calling
`gate.decide` itself with the constants patched; the routing logic is not reimplemented.
The full grid goes to eval/results/threshold_sweep_full.csv; the chosen constants, the Pareto
front (top 20) and the near-boundary messages go to eval/results/threshold_sweep.md and stdout.

Label mapping (eval/messages.jsonl carries intent, wants_human, concern_count):
- right fast path: the label intent equals the template taken, concern_count is 1, and
  wants_human is false, and template_ok is true (the template's fixed facts fully answer the
  message). Order-fact templates also require an order ID in the text (`gate.decide`). A fast route failing any of these counts as a wrong fast path.
- wrong escalation: route ESCALATE while the label wants_human is false.
- missed escalation: label wants_human is true and the route is not ESCALATE.
- There is no frustration label. The gate's `angry` block reads Jev's own frustration answer, so
  it is not scored against a label. There is also no needs_llm label; the intent and
  concern_count labels are the closest available proxy for "the template is enough".

Margin (used only to break ties): for each threshold, the distance to the nearest message
probability whose route would change if the threshold crossed it. Combinations with a margin under
MIN_MARGIN (0.05) rank below all others; ties rank by the smallest of the three distances, then
by their sum.
"""

import argparse
import dataclasses
import itertools
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

import gate  # noqa: E402
from gate import Route  # noqa: E402
from run_eval import load_messages  # noqa: E402
from triage import TriageResult  # noqa: E402

CACHE = HERE / "results" / "triage_probs.json"
REPORT = HERE / "results" / "threshold_sweep.md"
MIN_MARGIN = 0.05
FULL = HERE / "results" / "threshold_sweep_full.csv"


def frange(lo: float, hi: float) -> list[float]:
    return [round(lo + 0.05 * i, 2) for i in range(round((hi - lo) / 0.05) + 1)]


GRID = {"INTENT_CONFIDENCE_MIN": frange(0.50, 0.95),
        "NEEDS_LLM_FAST_MAX": frange(0.10, 0.95),
        "WANTS_HUMAN_ESCALATE": frange(0.50, 0.95)}
# Which TriageResult field each threshold is compared with.
FIELD = {"INTENT_CONFIDENCE_MIN": "intent_confidence", "NEEDS_LLM_FAST_MAX": "needs_llm",
         "WANTS_HUMAN_ESCALATE": "wants_human"}


def fetch(messages: list[dict]) -> list[TriageResult]:
    from jev_client import make_client
    from triage import triage
    client = make_client()
    results = [triage(client, m["text"]) for m in messages]
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text("{\n" + ",\n".join(
        f"{json.dumps(m['id'])}: {json.dumps(dataclasses.asdict(r))}"
        for m, r in zip(messages, results)) + "\n}\n")
    return results


def load_cache(messages: list[dict]) -> list[TriageResult]:
    raw = json.loads(CACHE.read_text())
    out = []
    for m in messages:
        d = raw[m["id"]]
        d["concern_probabilities"] = {int(k): v for k, v in d["concern_probabilities"].items()}
        out.append(TriageResult(**d))
    return out


def decisions(triages: list[TriageResult], messages: list[dict], **thresholds) -> list[gate.Decision]:
    saved = {k: getattr(gate, k) for k in GRID}
    try:
        for k in GRID:
            setattr(gate, k, thresholds.get(k, saved[k]))
        return [gate.decide(t, m["text"]) for t, m in zip(triages, messages)]
    finally:
        for k, v in saved.items():
            setattr(gate, k, v)


def routes(triages: list[TriageResult], messages: list[dict], **thresholds) -> list[Route]:
    return [d.route for d in decisions(triages, messages, **thresholds)]


def margins(triages: list[TriageResult], messages: list[dict], combo: dict) -> list[float]:
    """Per-threshold distance to the nearest message probability that would flip."""
    base = routes(triages, messages, **combo)
    out = []
    for name, field in FIELD.items():
        best = 1.0
        for i, t in enumerate(triages):
            v = getattr(t, field)
            crossed = v - 1e-9 if combo[name] > v else v + 1e-9
            if routes([t], [messages[i]], **{**combo, name: crossed})[0] != base[i]:
                best = min(best, abs(combo[name] - v))
        out.append(best)
    return out


def score(messages, triages, combo) -> dict:
    ds = decisions(triages, messages, **combo)
    rs = [d.route for d in ds]
    n = len(messages)
    row = {**combo, "fast": sum(r is Route.FAST_PATH for r in rs) / n,
           "escalate": sum(r is Route.ESCALATE for r in rs) / n,
           "llm": sum(r is Route.LLM_PATH for r in rs) / n,
           "wrong_fast": 0, "wrong_esc": 0, "missed_esc": 0}
    row["templates"] = Counter(d.template for d in ds if d.route is Route.FAST_PATH)
    for m, d in zip(messages, ds):
        r = d.route
        if r is Route.FAST_PATH and not (m["intent"] == d.template and m["concern_count"] == 1
                                         and not m["wants_human"] and m["template_ok"]):
            row["wrong_fast"] += 1
        if r is Route.ESCALATE and not m["wants_human"]:
            row["wrong_esc"] += 1
        if m["wants_human"] and r is not Route.ESCALATE:
            row["missed_esc"] += 1
    row["non_llm"] = row["fast"] + row["escalate"]
    return row


def table(rows: list[dict], with_margin: bool = False) -> str:
    head = ["intent_min", "fast_max", "esc_min", "fast", "escalate", "llm", "non-LLM",
            "wrong fast", "wrong esc", "missed esc"] + (["margin"] if with_margin else [])
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        cells = [f"{r['INTENT_CONFIDENCE_MIN']:.2f}", f"{r['NEEDS_LLM_FAST_MAX']:.2f}",
                 f"{r['WANTS_HUMAN_ESCALATE']:.2f}", f"{r['fast']:.1%}", f"{r['escalate']:.1%}",
                 f"{r['llm']:.1%}", f"{r['non_llm']:.1%}", str(r["wrong_fast"]),
                 str(r["wrong_esc"]), str(r["missed_esc"])]
        if with_margin:
            cells.append(f"{r['margin']:.3f}")
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="re-call Jev and rewrite the cache")
    args = ap.parse_args()
    messages = load_messages()
    triages = fetch(messages) if args.refresh or not CACHE.exists() else load_cache(messages)

    rows = [score(messages, triages, dict(zip(GRID, vals)))
            for vals in itertools.product(*GRID.values())]
    rows.sort(key=lambda r: (-r["non_llm"], r["missed_esc"], r["wrong_fast"] + r["wrong_esc"]))
    pareto = [r for r in rows if r["wrong_fast"] == 0 and r["wrong_esc"] == 0]
    for r in pareto:
        m = margins(triages, messages, {k: r[k] for k in GRID})
        r["margin"] = min(m)
        r["margin_sum"] = sum(m)
    # A combination whose cutoff sits within MIN_MARGIN of a message that would flip is not
    # trusted: the labeled set is too small to say the neighbouring probability is safe.
    pareto.sort(key=lambda r: (r["margin"] < MIN_MARGIN, -r["non_llm"], r["missed_esc"],
                               -r["margin"], -r["margin_sum"]))

    cols = ["INTENT_CONFIDENCE_MIN", "NEEDS_LLM_FAST_MAX", "WANTS_HUMAN_ESCALATE", "fast", "escalate",
            "llm", "non_llm", "wrong_fast", "wrong_esc", "missed_esc"]
    FULL.write_text(",".join(cols) + "\n" + "".join(
        ",".join(str(round(r[c], 4)) if isinstance(r[c], float) else str(r[c]) for c in cols) + "\n"
        for r in rows))

    out = [f"# Threshold sweep\n\n{len(messages)} labeled messages, {len(rows)} combinations "
           f"(full grid: `{FULL.name}`). `wrong fast`: fast path taken when the label intent "
           f"differs from the template taken, is multi-concern, wants a human, or is labeled `template_ok: false`. `wrong esc`: escalated when the "
           f"label wants no human. `missed esc`: label wants a human, route is not ESCALATE. "
           f"{len(pareto)} combinations have zero wrong fast paths and zero wrong escalations."]
    if pareto:
        top = pareto[0]
        combo = {k: top[k] for k in GRID}
        out.append("## Chosen constants\n\n" + "\n".join(f"- `{k}` = {v:.2f}" for k, v in combo.items())
                   + f"\n\nRouting: fast {top['fast']:.1%}, escalate {top['escalate']:.1%}, "
                   f"LLM {top['llm']:.1%}; templates {dict(sorted(top['templates'].items()))}; wrong fast 0, wrong escalations 0, missed escalations "
                   f"{top['missed_esc']}.")
        out.append("## Pareto front (top 20)\n\nCombinations with margin below "
                   f"{MIN_MARGIN} rank last; the rest by non-LLM share, fewest missed "
                   "escalations, then margin.\n\n" + table(pareto[:20], with_margin=True))
        t_rs = routes(triages, messages, **combo)
        near = ["| threshold | value | message | probability | distance | route | label |",
                "|---|---|---|---|---|---|---|"]
        for k, field in FIELD.items():
            ranked = sorted(((abs(getattr(t, field) - combo[k]), m, t, r)
                             for m, t, r in zip(messages, triages, t_rs)),
                            key=lambda x: (x[0], x[1]["id"]))[:4]
            for d, m, t, r in ranked:
                near.append(f"| {k} | {combo[k]:.2f} | {m['id']} | {getattr(t, field):.3f} | "
                            f"{d:.3f} | {r.value} | {m['intent']}, {m['concern_count']} request(s), "
                            f"wants_human={m['wants_human']} |")
        out.append("## Nearest messages to each threshold\n\n" + "\n".join(near))
    REPORT.write_text("\n\n".join(out) + "\n")
    print(f"{len(pareto)} of {len(rows)} combinations have zero wrong fast paths and zero wrong "
          f"escalations. Pareto front (top 15):\n")
    print(table(pareto[:15], with_margin=True))
    print(f"\nReport: {REPORT}\nFull grid: {FULL}")

if __name__ == "__main__":
    main()
