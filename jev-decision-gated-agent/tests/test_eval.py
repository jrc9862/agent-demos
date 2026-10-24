from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import run_eval
from triage import INTENTS
from conftest import make_triage

# 10 at 0.95 (9 right), 2 at 0.55 (1 right), 1 at exactly 1.0 (right), 1 at 0.30 (wrong)
FIXTURE = [(0.95, True)] * 9 + [(0.95, False), (0.55, True), (0.55, False), (1.0, True), (0.30, False)]


def test_calibration_table_on_fixed_fixture():
    rows = {r["bucket"]: r for r in run_eval.calibration_table(FIXTURE)}
    assert list(rows) == ["0.0-0.5", "0.5-0.6", "0.6-0.7", "0.7-0.8", "0.8-0.9", "0.9-1.0"]
    top = rows["0.9-1.0"]
    assert top["n"] == 11 and top["accuracy"] == pytest.approx(10 / 11)
    assert top["mean_confidence"] == pytest.approx((0.95 * 10 + 1.0) / 11)
    assert rows["0.5-0.6"] == {"bucket": "0.5-0.6", "n": 2, "mean_confidence": pytest.approx(0.55),
                               "accuracy": 0.5}
    assert rows["0.0-0.5"]["n"] == 1 and rows["0.0-0.5"]["accuracy"] == 0.0
    assert rows["0.7-0.8"] == {"bucket": "0.7-0.8", "n": 0, "mean_confidence": None, "accuracy": None}


def test_expected_calibration_error():
    rows = run_eval.calibration_table(FIXTURE)
    top_gap = abs((0.95 * 10 + 1.0) / 11 - 10 / 11)
    expected = (11 * top_gap + 2 * 0.05 + 1 * 0.30) / 14
    assert run_eval.expected_calibration_error(rows) == pytest.approx(expected)
    assert run_eval.expected_calibration_error(run_eval.calibration_table([])) is None


def test_score_skips_failed_predictions():
    msgs = [{"intent": "refund_request", "wants_human": False, "concern_count": 2},
            {"intent": "billing", "wants_human": True, "concern_count": 1}]
    preds = [{"intent": ("refund_request", 0.9), "wants_human": (True, 0.8), "concern_count": (2, 0.7)}, None]
    records = run_eval.score(msgs, preds)
    assert records == {"intent": [(0.9, True)], "wants_human": [(0.8, False)], "concern_count": [(0.7, True)]}


def test_jev_prediction_uses_probability_of_the_chosen_answer_not_choice_confidence():
    # .confidence (0.7) is a concentration measure; the eval uses probabilities[choice] (0.55).
    t = make_triage(intent="refund_request", intent_confidence=0.7,
                    intent_probabilities={"refund_request": 0.55, "billing_dispute": 0.45}, wants_human=0.1,
                    concern_count=2, concern_probabilities={1: 0.2, 2: 0.65, 3: 0.15})
    p = run_eval.jev_prediction(t)
    assert p == {"intent": ("refund_request", 0.55), "wants_human": (False, 0.9), "concern_count": (2, 0.65)}
    assert run_eval.jev_prediction(make_triage(wants_human=0.8))["wants_human"] == (True, 0.8)


def test_triage_and_llm_prompt_ask_the_same_intent_question():
    from triage import INTENT_QUESTION, TRIAGE_QUESTIONS
    assert TRIAGE_QUESTIONS["intent"].instructions == INTENT_QUESTION
    assert INTENT_QUESTION in run_eval.LLM_PROMPT.format(
        intent_question=INTENT_QUESTION, intents="", message="")


def mocked_client(stop_reason="end_turn", parsed=None):
    client = MagicMock()
    client.messages.parse.return_value = SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed)
    return client


def test_llm_baseline_uses_structured_output_and_maps_answers():
    parsed = run_eval.LLMTriage(intent="billing_dispute", intent_confidence=1.3, wants_human=False,
                                wants_human_confidence=0.9, concern_count="3+",
                                concern_count_confidence=0.8)
    client = mocked_client(parsed=parsed)
    p = run_eval.llm_predict(client, "charged twice, also reset my password, and where is 48213")
    assert p == {"intent": ("billing_dispute", 1.0), "wants_human": (False, 0.9), "concern_count": (3, 0.8)}
    kwargs = client.messages.parse.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5-5" and kwargs["output_format"] is run_eval.LLMTriage
    assert not {"thinking", "tool_choice", "tools"} & set(kwargs)


def test_llm_refusal_is_counted_not_guessed():
    assert run_eval.llm_predict(mocked_client(stop_reason="refusal"), "x") is None


def test_labeled_messages_are_well_formed():
    msgs = run_eval.load_messages()
    assert 55 <= len(msgs) <= 65 and len({m["id"] for m in msgs}) == len(msgs)
    for m in msgs:
        assert m["intent"] in INTENTS
        assert isinstance(m["wants_human"], bool) and m["concern_count"] in {1, 2, 3}
