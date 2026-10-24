from types import SimpleNamespace

from pathlib import Path

from batch import Outcome, collect, max_submit_interval_hours, reconcile, select_paths, triage
from helpers import INVOICE_TEXT, invoice, tool_message


def entry(custom_id, result):
    return SimpleNamespace(custom_id=custom_id, result=result)


def test_collect_matches_by_custom_id_regardless_of_order():
    results = [
        entry("inv-3", SimpleNamespace(type="succeeded", message=tool_message(invoice(vendor="C")))),
        entry("inv-1", SimpleNamespace(type="succeeded", message=tool_message(invoice(vendor="A")))),
        entry("inv-2", SimpleNamespace(type="errored", error=SimpleNamespace(type="overloaded_error"))),
        entry("inv-4", SimpleNamespace(type="expired")),
        entry("inv-5", SimpleNamespace(type="succeeded", message=tool_message({}, stop_reason="refusal"))),
    ]
    client = SimpleNamespace(messages=SimpleNamespace(batches=SimpleNamespace(results=lambda _id: iter(results))))
    out = collect(client, "batch_x")
    assert out["inv-1"].data["vendor"] == "A" and out["inv-3"].data["vendor"] == "C"
    assert out["inv-2"].kind == "errored" and out["inv-2"].retryable_api_error
    assert out["inv-4"].kind == "expired"
    assert out["inv-5"].kind == "errored" and not out["inv-5"].retryable_api_error


def test_reconcile_reports_orphans_and_strangers():
    outcomes = {"a": Outcome("succeeded"), "z": Outcome("succeeded")}
    assert reconcile({"a", "b"}, outcomes) == ({"b"}, {"z"})


def test_triage_sends_fixable_failures_to_round_two():
    corpus = {i: ("invoice", INVOICE_TEXT) for i in ["ok", "arith", "absent", "expired", "refused"]}
    outcomes = {"ok": Outcome("succeeded", invoice()),
                "arith": Outcome("succeeded", invoice(stated_total=118.0)),
                "absent": Outcome("succeeded", invoice(warranty_date="2028-01-01")),
                "expired": Outcome("expired"),
                "refused": Outcome("errored", error="Refused", retryable_api_error=False)}
    final, resubmit = triage(corpus, outcomes)
    assert set(final) == {"ok", "absent", "refused"} and set(resubmit) == {"arith", "expired"}
    assert final["absent"]["status"] == "unresolvable"
    assert "stated_total 118.00" in resubmit["arith"]
    assert set(final) | set(resubmit) == set(corpus)  # no orphans


def test_sla_arithmetic():
    assert max_submit_interval_hours(72) == 24     # 24h wait + 24h batch + 24h resubmit round
    assert max_submit_interval_hours(48) == 0      # no slack at all
    assert max_submit_interval_hours(24) < 0       # batch cannot meet a 24h SLA


def _paths():
    names = [f"{p}-{n:03d}" for p, c in (("abs", 30), ("con", 30), ("inv", 40)) for n in range(1, c + 1)]
    return [Path(f"{n}.txt") for n in sorted(names)]


def test_select_paths_stratifies_round_robin():
    from collections import Counter
    for limit, want in ((30, (10, 10, 10)), (10, (4, 3, 3))):
        got = select_paths(_paths(), limit)
        c = Counter(p.stem[:3] for p in got)
        assert (c["inv"], c["abs"], c["con"]) == want
    ten = {p.stem for p in select_paths(_paths(), 10)}
    assert {"inv-001", "inv-004", "abs-001", "abs-003", "con-001", "con-003"} <= ten
    assert "inv-005" not in ten


def test_select_paths_without_limit_returns_all():
    assert len(select_paths(_paths(), None)) == 100
