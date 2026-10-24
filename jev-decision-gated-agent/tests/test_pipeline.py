"""End-to-end routing with the FAKE Jev transport and a scripted stand-in for the LLM agent."""

import json

import httpx2
import pytest
from typesafe_sdk import RetryPolicy, TypeSafeClient, TypeSafeError

import agent
import fake_backend
import gate
import pipeline
from gate import Route
from jev_client import make_client


@pytest.fixture
def jev():
    return make_client(fake=True)


@pytest.fixture
def no_llm(monkeypatch):
    """Any attempt to reach an LLM fails the test."""
    def boom(*a, **k):
        raise AssertionError("LLM was called")
    monkeypatch.setattr(agent, "query", boom)
    monkeypatch.setattr(agent, "run_agent_sync", boom)
    monkeypatch.setattr("anthropic.Anthropic", boom)
    return boom


class ScriptedAgent:
    """Stands in for agent.run_agent_sync; returns queued AgentRuns and records each call."""

    def __init__(self, *runs):
        self.runs, self.calls = list(runs), []

    def __call__(self, prompt, triage_facts=None, resume=None):
        self.calls.append({"prompt": prompt, "triage_facts": triage_facts, "resume": resume})
        return self.runs.pop(0)


def refund_call(ok=True):
    result = {"isError": False, "result": {"refund_id": "R1", "status": "issued"}} if ok else \
        {"isError": True, "errorCategory": "business", "isRetryable": False, "message": "no"}
    return {"tool": "process_refund", "input": {"order_id": "48377", "amount": 42.5},
            "result": result, "is_error": not ok}


def outcomes(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_order_status_fast_path_never_touches_an_llm(jev, no_llm, isolated):
    out = pipeline.handle("Where is order 48213?", jev, runner=no_llm)
    assert out.route is Route.FAST_PATH and out.path == "fast"
    assert [c["tool"] for c in out.tool_calls] == ["lookup_order"]
    assert out.llm_calls == 0 and out.llm_cost_usd == 0.0
    assert "UPS" in out.reply and "48213" in out.reply
    final = outcomes(isolated)[-1]
    assert final["path"] == "fast" and final["llm_calls"] == 0 and "latency_ms" in final


def test_fast_path_transient_failure_is_reported_not_hidden(jev, no_llm):
    fake_backend.fail_next("lookup_order", "timeout", times=2)
    out = pipeline.handle("Where is order 48213?", jev, runner=no_llm)
    assert out.path == "fast" and "isn't responding" in out.reply
    assert out.tool_calls[0]["result"]["errorCategory"] == "transient"


def test_human_request_escalates_before_any_tool_or_llm(jev, no_llm):
    out = pipeline.handle("I want to talk to a person", jev, customer_id="C001", runner=no_llm)
    assert out.route is Route.ESCALATE
    assert [c["tool"] for c in out.tool_calls] == ["escalate_to_human"]
    handoff = fake_backend.ESCALATIONS[-1]
    assert set(handoff) >= {"headline", "reason", "attempted_actions", "customer_facts", "open_uncertainty"}
    assert handoff["attempted_actions"] == [] and handoff["customer_facts"]["customer_id"] == "C001"


def test_ambiguous_message_falls_through_to_llm(jev):
    scripted = ScriptedAgent(agent.AgentRun(reply="Could you tell me which order?", session_id="s1"))
    out = pipeline.handle("my thing from last week is wrong", jev, runner=scripted)
    assert out.route is Route.LLM_PATH and "intent confidence" in out.reason
    assert scripted.calls[0]["triage_facts"]["intent_confidence"] < 0.6


def test_bundled_message_gets_concern_count_and_passes_verify(jev):
    draft = ("I've refunded $42.50 for order 48377. I can't change your shipping address from "
             "chat; you can update it to 9 Oak Ln under Account > Addresses.")
    scripted = ScriptedAgent(agent.AgentRun(reply=draft, tool_calls=[refund_call()], session_id="s1",
                                            cost_usd=0.05))
    out = pipeline.handle("I want a refund for order 48377 and please also update my shipping "
                          "address to 9 Oak Ln.", jev, customer_id="C001", runner=scripted)
    assert out.route is Route.LLM_PATH
    assert scripted.calls[0]["triage_facts"]["concern_count"] == 2
    assert "Customer ID: C001" in scripted.calls[0]["prompt"]
    assert out.path == "llm+verify" and out.verify_rounds[0]["failed"] == []


def test_unconfirmed_promise_triggers_exactly_one_revision(jev):
    msg = "I want a refund for order 48377, the bottle leaks."
    scripted = ScriptedAgent(
        agent.AgentRun(reply="Your refund has been processed!", tool_calls=[refund_call(ok=False)],
                       session_id="s1"),
        agent.AgentRun(reply="I couldn't issue the refund automatically; I've asked a colleague to "
                             "review it.", session_id="s1"))
    out = pipeline.handle(msg, jev, runner=scripted)
    assert out.verify_rounds[0]["failed"] == ["promises_unconfirmed"]
    assert len(scripted.calls) == 2
    assert scripted.calls[1]["resume"] == "s1" and "promises_unconfirmed" in scripted.calls[1]["prompt"]
    assert out.path == "llm+verify+revise" and "processed" not in out.reply


def test_second_verify_failure_escalates(jev):
    bad = agent.AgentRun(reply="Your refund has been processed!", session_id="s1")
    scripted = ScriptedAgent(bad, bad)
    out = pipeline.handle("Refund order 48377 please, it leaks.", jev, runner=scripted)
    assert len(scripted.calls) == 2 and out.path == "escalate"
    assert "promises_unconfirmed" in fake_backend.ESCALATIONS[-1]["reason"]


def test_jev_outage_falls_back_to_llm_path_and_logs_it(isolated):
    down = TypeSafeClient(api_key="k", retry=RetryPolicy(max_retries=0),
                          transport=httpx2.MockTransport(lambda r: httpx2.Response(503)))
    scripted = ScriptedAgent(agent.AgentRun(reply="ok", session_id="s1"))
    out = pipeline.handle("Where is order 48213?", down, runner=scripted)
    assert out.route is Route.LLM_PATH and scripted.calls[0]["triage_facts"] is None
    kinds = [e["kind"] for e in outcomes(isolated)]
    assert kinds[:2] == ["triage_error", "route"]


def test_agent_refuses_to_run_without_api_key(monkeypatch):
    monkeypatch.setattr(agent, "query", lambda **k: (_ for _ in ()).throw(AssertionError("spawned")))
    with pytest.raises(agent.AgentConfigError, match="ANTHROPIC_API_KEY"):
        agent.run_agent_sync("hi")


def test_missing_api_key_is_a_hard_failure_not_an_escalation(jev, monkeypatch):
    """conftest unsets ANTHROPIC_API_KEY, so the real runner raises AgentConfigError."""
    with pytest.raises(agent.AgentConfigError):
        pipeline.handle("my thing from last week is wrong", jev)
    assert fake_backend.ESCALATIONS == []
    import sys
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)   # keep the real .env out
    with pytest.raises(SystemExit) as exc:
        sys.argv = ["pipeline.py", "--fake-jev", "my thing from last week is wrong"]
        pipeline.main()
    assert "ANTHROPIC_API_KEY" in str(exc.value) and exc.value.code != 0
    assert fake_backend.ESCALATIONS == []


def test_runtime_llm_failure_still_escalates(jev):
    def broken(prompt, triage_facts=None, resume=None):
        raise agent.AgentError("agent process failed")
    out = pipeline.handle("my thing from last week is wrong", jev, runner=broken)
    assert out.path == "escalate" and "LLM path unavailable" in fake_backend.ESCALATIONS[-1]["reason"]


def test_verify_outage_sends_unverified_reply_and_logs_it(jev, isolated, monkeypatch):
    def down(*a, **k):
        raise TypeSafeError("verify down")
    monkeypatch.setattr(pipeline, "verify", down)
    scripted = ScriptedAgent(agent.AgentRun(reply="Please tell me the order number.", session_id="s1"))
    out = pipeline.handle("my thing from last week is wrong", jev, runner=scripted)
    assert out.path == "llm+unverified" and out.reply == "Please tell me the order number."
    assert fake_backend.ESCALATIONS == [] and len(scripted.calls) == 1
    entries = outcomes(isolated)
    assert [e for e in entries if e["kind"] == "verify_error"]
    assert entries[-1]["kind"] == "outcome" and entries[-1]["path"] == "llm+unverified"


def test_missing_session_id_on_revision_escalates_instead_of_starting_fresh(jev):
    bad = agent.AgentRun(reply="Your refund has been processed!", session_id=None)
    scripted = ScriptedAgent(bad)
    out = pipeline.handle("Refund order 48377 please, it leaks.", jev, runner=scripted)
    assert len(scripted.calls) == 1 and out.path == "escalate"
    assert "session_id" in fake_backend.ESCALATIONS[-1]["reason"]


def test_fast_path_rejects_an_order_owned_by_another_customer(jev):
    scripted = ScriptedAgent(agent.AgentRun(reply="I can't see a status for that order on your account.",
                                            session_id="s1"))
    out = pipeline.handle("Where is order 48213?", jev, customer_id="C002", runner=scripted)
    assert out.route is Route.LLM_PATH and "does not belong" in out.reason
    assert "UPS" not in out.reply and len(scripted.calls) == 1


def test_fast_path_accepts_the_customers_own_order(jev, no_llm):
    out = pipeline.handle("Where is order 48213?", jev, customer_id="C001", runner=no_llm)
    assert out.path == "fast" and "UPS" in out.reply


@pytest.mark.parametrize("message", ["This is ridiculous!! Where is order 48213?",
                                     "Where is order 48213, and also I need a refund for 48377?"])
def test_angry_or_multi_concern_order_status_skips_the_fast_path(jev, message):
    scripted = ScriptedAgent(agent.AgentRun(reply="Sorry for the trouble. Order 48213 shipped (tracking sent); your refund request for 48377 is with us.",
                                            session_id="s1"))
    out = pipeline.handle(message, jev, runner=scripted)
    assert out.route is Route.LLM_PATH and out.path != "fast" and len(scripted.calls) == 1


def test_triage_state_carries_customer_record_and_template_scope(jev, monkeypatch):
    seen = {}
    real = jev.system_one
    monkeypatch.setattr(jev, "system_one", lambda state, q: seen.setdefault("s", state) and real(state, q))
    pipeline.handle("Where is order 48213?", jev, customer_id="C001",
                    runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert seen["s"]["customer"]["name"] == "Dana Ruiz"
    assert any("tracking number" in c for c in seen["s"]["reply_template_covers"]["order_status"])
    assert set(seen["s"]["reply_template_covers"]) == set(gate.FAST_TEMPLATES)
