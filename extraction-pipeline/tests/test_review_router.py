from review_router import accuracy_report, format_report, route
from schema import FIELDS

TRUTH = {
    "inv-1": {"doc_type": "invoice", "fields": {"vendor": "Acme", "tax": 8.0}},
    "inv-2": {"doc_type": "invoice", "fields": {"vendor": "Beta", "tax": 1.0}},
    "con-1": {"doc_type": "contract", "fields": {"term_months": 24, "payment_due_days": 30}},
    "con-2": {"doc_type": "contract", "fields": {"term_months": 12, "payment_due_days": 45}},
}


def rec(status, doc_type, data):
    return {"status": status, "doc_type": doc_type, "data": data}


def conf(**kw):
    return {k: kw.get(k, 0.95) for k in FIELDS["invoice"]}


def test_low_confidence_field_routes_to_review():
    ex = {"inv-1": rec("accepted", "invoice", {"vendor": "Acme", "confidence": conf(vendor=0.5, tax=0.79)})}
    q = route(ex, threshold=0.8)
    assert {(e["doc_id"], e["field"]) for e in q if e["field"] in ("vendor", "tax")} == {("inv-1", "vendor"), ("inv-1", "tax")}
    assert not any(e["field"] == "subtotal" for e in q)  # 0.95 passes


def test_missing_confidence_and_unaccepted_docs_route():
    ex = {"inv-1": rec("accepted", "invoice", {"confidence": {}}),
          "inv-2": rec("unresolvable", "invoice", None)}
    q = route(ex)
    assert any(e["doc_id"] == "inv-1" and e["field"] == "vendor" for e in q)
    assert any(e["doc_id"] == "inv-2" and e["field"] == "*" for e in q)


def test_report_stratifies_by_type_and_exposes_the_hard_type():
    ex = {"inv-1": rec("accepted", "invoice", {"vendor": "acme ", "tax": 8.0}),
          "inv-2": rec("accepted", "invoice", {"vendor": "Beta", "tax": 1.0}),
          "con-1": rec("accepted", "contract", {"term_months": 24, "payment_due_days": 30}),
          "con-2": rec("accepted", "contract", {"term_months": 24, "payment_due_days": 30})}  # amendments missed
    report = accuracy_report(ex, TRUTH)
    assert report["cells"]["invoice"]["vendor"] == [2, 2]
    assert report["cells"]["contract"]["term_months"] == [1, 2]
    assert sorted(report["wrong"]) == [("con-2", "payment_due_days"), ("con-2", "term_months")]
    text = format_report(report, [], gap=0.05)
    assert "aggregate field accuracy: 75.0%" in text
    assert "| invoice | 100.0% (4/4) |" in text
    assert "| contract | 50.0% (2/4) | 25.0 points below aggregate |" in text
    assert "| contract | term_months | 50% (1/2) |" in text


def test_report_counts_wrong_fields_that_reached_review():
    ex = {"con-2": rec("accepted", "contract", {"term_months": 24, "payment_due_days": 45})}
    report = accuracy_report(ex, {"con-2": TRUTH["con-2"]})
    queue = [{"doc_id": "con-2", "field": "term_months"}]
    assert "1/1 wrong fields were routed to review" in format_report(report, queue)
