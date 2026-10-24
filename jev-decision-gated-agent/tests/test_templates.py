"""Each template route: no LLM, the right tool calls, the right reply, and the log fields."""

import json

import pytest

import fake_backend
import fast_paths
import gate
import pipeline
from conftest import make_triage
from gate import Route
from jev_client import make_client
from test_pipeline import no_llm, outcomes  # noqa: F401  (no_llm is a fixture)


@pytest.fixture
def run(monkeypatch, no_llm):
    """handle() with triage patched to a chosen result and any LLM call failing the test."""
    def go(message, customer_id="C001", **triage_fields):
        monkeypatch.setattr(pipeline, "triage", lambda *a, **k: make_triage(**triage_fields))
        return pipeline.handle(message, make_client(fake=True), customer_id=customer_id, runner=no_llm)
    return go


def tools(out):
    return [c["tool"] for c in out.tool_calls]


def test_account_change_escalates_directly_with_a_structured_handoff(run):
    out = run("Please change my shipping address to 77 Elm St, Boise ID.", intent="account_change")
    assert out.route is Route.FAST_PATH and out.path == "fast" and out.template == "account_change"
    assert tools(out) == ["escalate_to_human"] and out.llm_calls == 0
    handoff = fake_backend.ESCALATIONS[-1]
    assert handoff["customer_facts"] == {"customer_id": "C001", "requested_change":
                                         "Please change my shipping address to 77 Elm St, Boise ID."}
    assert handoff["headline"].startswith("Account change request")
    assert handoff["ticket_id"] in out.reply


def test_account_change_without_a_customer_id_falls_through(monkeypatch, no_llm):
    monkeypatch.setattr(pipeline, "triage", lambda *a, **k: make_triage(intent="account_change"))
    called = []
    out = pipeline.handle("Change my email.", make_client(fake=True), runner=lambda *a, **k: called.append(1) or
                          pipeline.agent.AgentRun(reply="ok", session_id="s"))
    assert out.route is Route.LLM_PATH and "needs a customer ID" in out.reason and called
    assert fake_backend.ESCALATIONS == []


def test_return_how_is_fixed_text(run):
    out = run("How do I return the socks for a refund?", intent="return_how")
    assert out.template == "return_how" and out.tool_calls == [] and "30 days" in out.reply


def test_login_help_is_fixed_text(run):
    out = run("I can't log in, it says my password is wrong.", intent="login_help")
    assert out.template == "login_help" and out.tool_calls == [] and "Forgot password" in out.reply


def test_invoice_request_names_the_most_recent_order(run):
    out = run("Can I get an invoice for my last purchase?", intent="invoice_request")
    assert tools(out) == ["search_orders"] and out.template == "invoice_request"
    assert "48213" in out.reply and "INV-48213" in out.reply     # C001's latest order


def test_refund_status_reads_the_refund_on_the_order(run):
    out = run("Did my refund for order 49555 go through?", customer_id="C003", intent="refund_status")
    assert tools(out) == ["lookup_order"] and out.template == "refund_status"
    assert "R0912" in out.reply and "$31.00" in out.reply and "2026-09-22" in out.reply
    assert fake_backend.ESCALATIONS == [] and fake_backend.REFUNDS == []


def test_refund_status_without_a_refund_says_so_and_escalates(run):
    out = run("Did my refund for order 48377 go through?", intent="refund_status")
    assert tools(out) == ["lookup_order", "escalate_to_human"]
    assert "don't see a refund on record" in out.reply and "refund request goes to our team" in out.reply
    assert fake_backend.ESCALATIONS[-1]["ticket_id"] in out.reply
    assert fake_backend.ESCALATIONS[-1]["customer_facts"]["order_ids"] == ["48377"]
    assert fake_backend.REFUNDS == []                      # no money moved


def test_refund_status_without_an_order_id_falls_through(monkeypatch):
    monkeypatch.setattr(pipeline, "triage", lambda *a, **k: make_triage(intent="refund_status"))
    out = pipeline.handle("Did my refund go through?", make_client(fake=True), customer_id="C001",
                          runner=lambda *a, **k: pipeline.agent.AgentRun(reply="Which order?", session_id="s"))
    assert out.route is Route.LLM_PATH and "names no order ID" in out.reason


@pytest.mark.parametrize("intent, message", [
    ("refund_status", "Did my refund for order 49555 go through?"),
    ("order_status", "Where is order 49555?"),
])
def test_another_customers_order_is_never_answered_by_a_template(monkeypatch, intent, message):
    monkeypatch.setattr(pipeline, "triage", lambda *a, **k: make_triage(intent=intent))
    out = pipeline.handle(message, make_client(fake=True), customer_id="C001",
                          runner=lambda *a, **k: pipeline.agent.AgentRun(reply="I can.t share a refund, status or tracking for an order that is not on your account.",
                                                                         session_id="s"))
    assert out.route is Route.LLM_PATH and "does not belong" in out.reason
    assert "R0912" not in out.reply and fake_backend.ESCALATIONS == []


@pytest.mark.parametrize("fields", [{"frustration": "angry"}, {"concern_count": 2},
                                    {"needs_llm": 0.99}, {"intent_confidence": 0.1}])
@pytest.mark.parametrize("intent", ["account_change", "return_how", "login_help",
                                    "invoice_request", "refund_status"])
def test_template_routes_need_the_same_conditions_as_order_status(intent, fields):
    assert gate.decide(make_triage(intent=intent, **fields)).route is Route.LLM_PATH


@pytest.mark.parametrize("intent", sorted(gate.FAST_TEMPLATES))
def test_decision_names_the_template(intent):
    d = gate.decide(make_triage(intent=intent))
    assert d.route is Route.FAST_PATH and d.template == intent


def test_log_entries_carry_template_probabilities_and_thresholds(run, isolated):
    run("How do I return the socks for a refund?", intent="return_how")
    route, outcome = outcomes(isolated)
    assert route["kind"] == "route" and route["template"] == "return_how"
    assert route["probabilities"]["intent_probabilities"] and route["probabilities"]["needs_llm"] == 0.05
    assert route["thresholds"]["NEEDS_LLM_FAST_MAX"] == gate.NEEDS_LLM_FAST_MAX
    assert outcome["path"] == "fast" and outcome["template"] == "return_how" and outcome["llm_calls"] == 0


def test_no_template_route_can_move_money():
    import inspect
    assert "process_refund" not in inspect.getsource(fast_paths)


def test_every_order_carries_an_invoice_id_and_a_refunds_list():
    for order in fake_backend.ORDERS.values():
        assert order["invoice_id"] == f"INV-{order['order_id']}" and isinstance(order["refunds"], list)
    assert fake_backend.lookup_order("49555")["invoice_id"] == "INV-49555"
    assert all("invoice_id" in o for o in fake_backend.search_orders("C002"))
