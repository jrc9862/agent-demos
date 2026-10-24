"""Network-free test setup: demo dir and eval/ on sys.path, a temp decision log, clean backend."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

import fake_backend  # noqa: E402
from triage import TriageResult  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    import gate
    monkeypatch.setattr(gate, "LOG_PATH", tmp_path / "decisions.jsonl")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    fake_backend.FAIL_NEXT.clear()
    fake_backend.REFUNDS.clear()
    fake_backend.ESCALATIONS.clear()
    yield tmp_path / "decisions.jsonl"


def make_triage(**overrides) -> TriageResult:
    fields = dict(intent="order_status", intent_confidence=0.9,
                  intent_probabilities={"order_status": 0.9, "other": 0.1}, concern_count=1,
                  concern_probabilities={1: 0.8, 2: 0.1, 3: 0.1}, wants_human=0.02,
                  frustration="calm", frustration_probabilities={"calm": 0.8, "civil": 0.1, "angry": 0.1},
                  needs_llm=0.05, jev_model="test", input_tokens=100, latency_ms=1.0)
    fields.update(overrides)
    return TriageResult(**fields)
