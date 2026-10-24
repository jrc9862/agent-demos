"""Structured subagent output. Provenance is a field, not a sentence."""
import json
from datetime import date

from pydantic import BaseModel, Field, ValidationError, field_validator

from fake_sources import CORPUS


class Finding(BaseModel):
    topic: str = Field(min_length=1, description="snake_case key shared by findings on one statistic")
    claim: str = Field(min_length=1)
    value: str | None = Field(default=None, description="the number as written, e.g. '28%'")
    evidence_excerpt: str = Field(min_length=1)
    source_url: str
    publication_date: date

    @field_validator("source_url")
    @classmethod
    def _http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("source_url must be an http(s) URL")
        return v


class SourceError(BaseModel):
    source_id: str
    errorCategory: str
    message: str


class Envelope(BaseModel):
    """What a searcher returns: records plus any per-source errors."""

    records: list[Finding] = []
    errors: list[SourceError] = []


def parse_envelope(text: str) -> Envelope:
    """Parse a subagent's final message. Raises ValueError on prose."""
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in subagent output")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return Envelope.model_validate(obj)
    except (json.JSONDecodeError, ValidationError) as e:
        raise ValueError(f"subagent output is not a valid envelope: {e}") from e


def corpus_problems(f: Finding) -> list[str]:
    """Check a record against the corpus. Catches fabricated sources and excerpts."""
    src = next((s for s in CORPUS.values() if s.url == f.source_url), None)
    if src is None:
        return [f"source_url not in corpus: {f.source_url}"]
    problems = []
    if f.publication_date.isoformat() != src.publication_date:
        problems.append(f"date {f.publication_date} != corpus {src.publication_date}")
    if not any(f.evidence_excerpt.strip() in p for p in src.passages):
        problems.append("evidence_excerpt is not verbatim from the source")
    return problems
