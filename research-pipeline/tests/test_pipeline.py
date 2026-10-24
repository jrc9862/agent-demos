"""Network-free tests. No model is called; model output is replaced by canned strings."""
import asyncio
import json
from datetime import date

import pytest

from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage

from coordinator import Collector
from fake_sources import CORPUS, FakeSources, SourceTimeout, UnknownSource
from records import Finding, corpus_problems, parse_envelope
from report import classify, render_report, verify_report
from scratchpad import Gap, read_findings, write_findings
from tools import load_agent


def rec(sid: str, **over) -> Finding:
    s = CORPUS[sid]
    base = dict(topic=s.topic, claim=s.passages[0], value=None, evidence_excerpt=s.passages[0],
                source_url=s.url, publication_date=s.publication_date)
    return Finding(**{**base, **over})


WFH_A = rec("wfh-research-2023", value="28%")
WFH_B = rec("census-pulse-2025", value="22%")
ATT_A = rec("hybrid-trial-2024", value="33%")
ATT_B = rec("retention-review-2025", value="33%")


# --- fake corpus and failure flags -------------------------------------------------------

async def test_fetch_returns_only_needed_fields():
    out = await FakeSources(latency_s=0).fetch("wfh-research-2023")
    assert set(out) == {"source_id", "source_url", "publication_date", "passages"}
    assert "Cookie" not in json.dumps(out)


async def test_timeout_flag_raises_transient():
    fs = FakeSources(failures={"office-vacancy-2025": "timeout"}, latency_s=0)
    with pytest.raises(SourceTimeout) as e:
        await fs.fetch("office-vacancy-2025")
    assert e.value.error_category == "transient"
    assert (await fs.fetch("lease-trends-2024"))["source_id"] == "lease-trends-2024"


async def test_unknown_source_is_not_retryable_category():
    with pytest.raises(UnknownSource) as e:
        await FakeSources(latency_s=0).fetch("nope")
    assert e.value.error_category == "invalid_input"


async def test_gather_overlaps_fetches():
    fs = FakeSources(latency_s=0.05)
    await asyncio.gather(*(fs.fetch(s) for s in list(CORPUS)[:3]))
    assert fs.max_overlap() == 3


def test_corpus_has_planted_conflict_and_agreement():
    a, b = CORPUS["wfh-research-2023"], CORPUS["census-pulse-2025"]
    assert a.topic == b.topic and a.publication_date != b.publication_date
    assert a.passages[0] != b.passages[0]


# --- structured record schema ------------------------------------------------------------

def test_prose_is_rejected():
    with pytest.raises(ValueError):
        parse_envelope("About 28% of days were worked from home, per a 2023 tracker.")


def test_valid_record_accepted():
    env = parse_envelope(json.dumps({"records": [WFH_A.model_dump(mode="json")], "errors": []}))
    assert env.records[0].publication_date == date(2023, 1, 20)


def test_record_missing_provenance_rejected():
    bad = WFH_A.model_dump(mode="json")
    del bad["publication_date"]
    with pytest.raises(ValueError):
        parse_envelope(json.dumps({"records": [bad]}))


def test_non_url_source_rejected():
    bad = WFH_A.model_dump(mode="json") | {"source_url": "a tracker I remember"}
    with pytest.raises(ValueError):
        parse_envelope(json.dumps({"records": [bad]}))


def test_hallucinated_source_and_altered_excerpt_caught():
    fake = WFH_A.model_copy(update={"source_url": "https://fake-sources.example/made-up"})
    assert corpus_problems(fake)
    altered = WFH_A.model_copy(update={"evidence_excerpt": "Nearly half of days were remote."})
    assert any("verbatim" in p for p in corpus_problems(altered))
    assert corpus_problems(WFH_A) == []


# --- scratchpad --------------------------------------------------------------------------

def test_scratchpad_round_trip(tmp_path):
    gaps = [Gap(what="office-vacancy-2025", errorCategory="transient", message="timed out")]
    p = tmp_path / "findings.md"
    write_findings(p, "Q?", [WFH_A, WFH_B, ATT_A], gaps)
    q, recs, g = read_findings(p)
    assert q == "Q?" and recs == [WFH_A, WFH_B, ATT_A] and g == gaps
    text = p.read_text()
    assert "28%" in text and CORPUS["census-pulse-2025"].url in text and "Not retrieved" in text


# --- contested handling ------------------------------------------------------------------

def test_conflict_is_contested_and_agreement_is_established():
    est, con, single = classify([WFH_A, WFH_B, ATT_A, ATT_B, rec("lease-trends-2024", value="14%")])
    assert list(con) == ["wfh_share"] and list(est) == ["hybrid_attrition"]
    assert list(single) == ["lease_footprint"]


def test_contested_report_keeps_both_values_with_dates():
    out = render_report("Q?", [WFH_A, WFH_B], [])
    contested = out.split("## Contested")[1].split("## Single source")[0]
    for r in (WFH_A, WFH_B):
        assert r.value in contested and r.source_url in contested and str(r.publication_date) in contested
    assert verify_report(out, [WFH_A, WFH_B], []) == []


def test_verifier_flags_a_silently_tie_broken_report():
    # What a lossy synthesizer would write: picks the newer number, drops the other.
    lossy = ("## Contested\nShare of workdays at home is 22% "
             f"({WFH_B.source_url}, {WFH_B.publication_date}).\n## Coverage gaps\nnone\n")
    problems = verify_report(lossy, [WFH_A, WFH_B], [])
    assert any("28%" in p for p in problems) and any(WFH_A.source_url in p for p in problems)


# --- coverage gaps on timeout ------------------------------------------------------------

def _stream(results: list[tuple[str, str, bool]]):
    """Fake coordinator stream: N Agent calls in one assistant message, then their results."""
    uses = [ToolUseBlock(id=f"t{i}", name="Agent",
                         input={"description": d, "prompt": f"sources: {sid}"})
            for i, (d, sid, _) in enumerate(results)]
    yield AssistantMessage(content=uses, model="m")
    for i, (_, body, err) in enumerate(results):
        yield UserMessage(content=[ToolResultBlock(tool_use_id=f"t{i}", content=body, is_error=err)])


def test_subagent_timeout_becomes_coverage_gap_not_crash():
    ok = json.dumps({"records": [WFH_A.model_dump(mode="json")], "errors": []})
    col = Collector()
    for m in _stream([("wfh", ok, False), ("vacancy", "office-vacancy-2025 timed out", True)]):
        col.feed(m)
    assert col.per_message == [2]  # both Agent calls came from one response
    assert col.records == [WFH_A]
    assert [(g.what, g.errorCategory) for g in col.gaps] == [("office-vacancy-2025", "transient")]
    report = render_report("Q?", col.records, col.gaps)
    assert "## Coverage gaps" in report and "office-vacancy-2025" in report
    assert verify_report(report, col.records, col.gaps) == []


def test_per_source_error_inside_envelope_becomes_gap():
    body = json.dumps({"records": [], "errors": [{"source_id": "office-vacancy-2025",
                                                  "errorCategory": "transient", "message": "timed out"}]})
    col = Collector()
    for m in _stream([("vacancy", body, False)]):
        col.feed(m)
    assert col.gaps[0].what == "office-vacancy-2025"


def test_fabricated_record_is_rejected_into_gaps():
    fake = WFH_A.model_copy(update={"source_url": "https://fake-sources.example/made-up"})
    body = json.dumps({"records": [fake.model_dump(mode="json")], "errors": []})
    col = Collector()
    for m in _stream([("wfh", body, False)]):
        col.feed(m)
    assert col.records == [] and col.gaps[0].errorCategory == "rejected_unverified"


def test_prose_subagent_output_becomes_gap():
    col = Collector()
    for m in _stream([("wfh", "I found that roughly a quarter of days are remote.", False)]):
        col.feed(m)
    assert col.records == [] and col.gaps and col.gaps[0].errorCategory == "malformed_output"


# --- agent files -------------------------------------------------------------------------

def test_agent_files_load():
    s, y = load_agent("searcher"), load_agent("synthesizer")
    assert s.tools == ["mcp__src__search_source"] and y.tools == ["Read"]
    assert "publication_date" in s.prompt and s.model == "claude-opus-5-5"


def test_live_run_refuses_to_start_without_api_key(monkeypatch):
    import coordinator
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit) as e:
        coordinator.require_api_key()
    assert ".env.example" in str(e.value.code)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    with pytest.raises(SystemExit):
        coordinator.require_api_key()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    coordinator.require_api_key()
