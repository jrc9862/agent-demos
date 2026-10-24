"""Grouping, a deterministic report renderer, and a check on the synthesizer's report.

The LLM writes the prose. This module decides what must survive in it.
"""
from collections import defaultdict

from records import Finding
from scratchpad import Gap


def _norm(f: Finding) -> str:
    return (f.value or f.claim).strip().lower()


def classify(records: list[Finding]):
    """-> (established, contested, single_source), each a dict topic -> records."""
    by_topic: dict[str, list[Finding]] = defaultdict(list)
    for r in records:
        by_topic[r.topic].append(r)
    established, contested, single = {}, {}, {}
    for topic, recs in by_topic.items():
        if len({r.source_url for r in recs}) < 2:
            single[topic] = recs
        elif len({_norm(r) for r in recs}) > 1:
            contested[topic] = recs
        else:
            established[topic] = recs
    return established, contested, single


def _line(r: Finding) -> str:
    v = f"{r.value}: " if r.value else ""
    return f"- {v}{r.claim} ({r.source_url}, published {r.publication_date})\n  > {r.evidence_excerpt}"


def render_report(question: str, records: list[Finding], gaps: list[Gap]) -> str:
    est, con, single = classify(records)
    out = [f"# {question}\n", "## Established (two or more sources agree)\n"]
    for topic, recs in est.items():
        out += [f"**{topic}**"] + [_line(r) for r in sorted(recs, key=lambda r: r.publication_date)]
    out.append("\n## Contested (sources disagree; no value chosen)\n")
    for topic, recs in con.items():
        out += [f"**{topic}**"] + [_line(r) for r in sorted(recs, key=lambda r: r.publication_date)]
    out.append("\n## Single source\n")
    for recs in single.values():
        out += [_line(r) for r in recs]
    out.append("\n## Coverage gaps\n")
    out += [f"- Not retrieved: {g.what} ({g.errorCategory}: {g.message})" for g in gaps] or ["- none"]
    return "\n".join(out) + "\n"


def verify_report(report: str, records: list[Finding], gaps: list[Gap]) -> list[str]:
    """Return problems. Empty list means every record and gap survived into the report."""
    problems = []
    for r in records:
        if r.source_url not in report:
            problems.append(f"missing source_url {r.source_url}")
        if str(r.publication_date) not in report:
            problems.append(f"missing date {r.publication_date} for {r.source_url}")
        if r.value and r.value not in report:
            problems.append(f"missing value {r.value} for {r.source_url}")
    _, con, _ = classify(records)
    if con and "contested" not in report.lower():
        problems.append("conflicting records exist but report has no 'contested' section")
    if "coverage gaps" not in report.lower():
        problems.append("report has no 'coverage gaps' section")
    for g in gaps:
        if g.what not in report:
            problems.append(f"gap not named: {g.what}")
    return problems
