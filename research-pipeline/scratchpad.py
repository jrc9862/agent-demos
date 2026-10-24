"""runs/findings.md: the only thing the synthesizer sees. Human-readable, machine-readable."""
import json
from pathlib import Path

from pydantic import BaseModel

from records import Finding

DATA_OPEN = "<!-- data:"
DATA_CLOSE = ":data -->"


class Gap(BaseModel):
    what: str  # the source or subtask not retrieved
    errorCategory: str
    message: str


def write_findings(path: Path, question: str, records: list[Finding], gaps: list[Gap]) -> None:
    lines = [f"# Findings\n\nQuestion: {question}\n", "## Records\n"]
    for r in sorted(records, key=lambda r: (r.topic, r.publication_date)):
        lines.append(f"- [{r.topic}] {r.claim} (value: {r.value or 'n/a'})\n"
                     f"  - source: {r.source_url}\n  - published: {r.publication_date}\n"
                     f"  - excerpt: \"{r.evidence_excerpt}\"")
    lines.append("\n## Not retrieved\n")
    lines += [f"- {g.what}: {g.errorCategory}, {g.message}" for g in gaps] or ["- none"]
    payload = json.dumps({"question": question,
                          "records": [r.model_dump(mode="json") for r in records],
                          "gaps": [g.model_dump() for g in gaps]}, indent=1)
    lines.append(f"\n{DATA_OPEN}\n{payload}\n{DATA_CLOSE}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def read_findings(path: Path) -> tuple[str, list[Finding], list[Gap]]:
    text = path.read_text()
    raw = text.split(DATA_OPEN, 1)[1].rsplit(DATA_CLOSE, 1)[0]
    data = json.loads(raw)
    return (data["question"], [Finding.model_validate(r) for r in data["records"]],
            [Gap.model_validate(g) for g in data["gaps"]])
