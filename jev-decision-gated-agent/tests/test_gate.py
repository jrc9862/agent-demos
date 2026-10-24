import json

import pytest

import gate
from conftest import make_triage
from gate import Route


EPS = 1e-4
ESC, CONF, FAST = gate.WANTS_HUMAN_ESCALATE, gate.INTENT_CONFIDENCE_MIN, gate.NEEDS_LLM_FAST_MAX


@pytest.mark.parametrize("overrides, expected", [
    ({"wants_human": ESC}, Route.FAST_PATH),                   # at threshold: not above it
    ({"wants_human": ESC + EPS}, Route.ESCALATE),
    ({"wants_human": 0.99, "intent_confidence": 0.1}, Route.ESCALATE),  # escalation checked first
    ({"intent_confidence": CONF - EPS}, Route.LLM_PATH),       # low confidence falls through
    ({"intent_confidence": CONF}, Route.FAST_PATH),            # at threshold: confident enough
    ({"needs_llm": FAST - EPS}, Route.FAST_PATH),
    ({"needs_llm": FAST}, Route.LLM_PATH),                     # at threshold: not below it
    ({"intent": "refund_request", "needs_llm": 0.01}, Route.LLM_PATH),  # no template for it
    ({"intent": "billing_dispute", "needs_llm": 0.01}, Route.LLM_PATH),
    ({"intent": "other", "intent_confidence": 0.99, "needs_llm": 0.01}, Route.LLM_PATH),
    ({"frustration": "civil"}, Route.FAST_PATH),
    ({"frustration": "angry"}, Route.LLM_PATH),                # angry order-status: not a template
    ({"concern_count": 2}, Route.LLM_PATH),                    # two concerns: not a template
    ({"concern_count": 3}, Route.LLM_PATH),
])
def test_threshold_boundaries(overrides, expected):
    assert gate.decide(make_triage(**overrides)).route is expected


def test_no_triage_means_llm_path():
    assert gate.decide(None).route is Route.LLM_PATH


@pytest.mark.parametrize("overrides", [{}, {"wants_human": 0.97}, {"intent_confidence": 0.3}])
def test_every_route_logs_its_probabilities(isolated, overrides):
    t = make_triage(**overrides)
    decision = gate.route(t, "msg-1")
    entry = json.loads(isolated.read_text().splitlines()[-1])
    assert entry["kind"] == "route" and entry["route"] == decision.route.value
    assert entry["message_id"] == "msg-1"
    p = entry["probabilities"]
    assert p["wants_human"] == t.wants_human and p["needs_llm"] == t.needs_llm
    assert p["intent_confidence"] == t.intent_confidence
    assert p["intent_probabilities"] == t.intent_probabilities
    assert entry["thresholds"]["INTENT_CONFIDENCE_MIN"] == gate.INTENT_CONFIDENCE_MIN


def test_verify_check_boundaries():
    ok = {"addresses_all_concerns": 0.5, "promises_unconfirmed": 0.4999, "tone_matches_frustration": 0.5}
    assert gate.failed_checks(ok) == []
    bad = {"addresses_all_concerns": 0.49, "promises_unconfirmed": 0.5, "tone_matches_frustration": 0.1}
    assert gate.failed_checks(bad) == ["addresses_all_concerns", "promises_unconfirmed",
                                       "tone_matches_frustration"]


@pytest.mark.parametrize("intent", ["order_status", "refund_status"])
def test_order_fact_templates_need_an_order_id_in_the_message(intent):
    t = make_triage(intent=intent)
    assert gate.decide(t, "When will my shoes arrive?").route is Route.LLM_PATH
    assert "names no order ID" in gate.decide(t, "When will my shoes arrive?").reason
    assert gate.decide(t, "Status of order 48213?").route is Route.FAST_PATH


def test_templates_without_order_facts_need_no_order_id():
    assert gate.decide(make_triage(intent="return_how"), "How do I send it back?").route is Route.FAST_PATH
