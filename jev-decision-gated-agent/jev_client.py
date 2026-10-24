"""Jev client construction: the real TypeSafe client, or the same client over a FAKE transport.

Single integration point: `make_client()`. Both modes return a real `typesafe_sdk.TypeSafeClient`,
so triage.py and verify.py always go through the SDK's own question validation, request
encoding, and response decoding. In fake mode only the HTTP server is replaced.

FakeJevTransport is a keyword heuristic that answers the questions this demo asks. Its
probabilities are hand-set constants, NOT calibrated, and NOT evidence of anything Jev does. It
exists so routing, thresholds, logging, and the eval harness run without a TYPESAFE_API_KEY.
"""

import json
import os
import re

import httpx2
from typesafe_sdk import RetryPolicy, TypeSafeClient

FAKE_MODEL = "FAKE-jev-keyword-heuristic"
JEV_USD_PER_MTOK_INPUT = 0.042  # docs.typesafe.ai/models, Jev 1.14; output tokens are free


def make_client(fake: bool = False) -> TypeSafeClient:
    if fake:
        return TypeSafeClient(api_key="fake-key-no-network", transport=FakeJevTransport(),
                              retry=RetryPolicy(max_retries=0))
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        raise SystemExit("TYPESAFE_API_KEY is not set. Set it, or pass --fake-jev to use the "
                         "uncalibrated keyword fake (routing plumbing only).")
    return TypeSafeClient()


def jev_cost_usd(input_tokens: int | None) -> float:
    return (input_tokens or 0) * JEV_USD_PER_MTOK_INPUT / 1_000_000


# ---------------------------------------------------------------- fake transport, keyword rules

INTENT_WORDS = {
    "order_status": r"where is|where's|tracking|track|shipped|arrive|delivery|status|eta|"
                    r"hasn't come|not arrived|still waiting",
    "refund_request": r"refund|money back|reimburse",
    "refund_status": r"refund (went|has gone|came) through|still no refund",
    "return_how": r"how (do|can) i return|send it back",
    "billing_dispute": r"charged|charge|overcharg",
    "invoice_request": r"invoice|receipt",
    "account_change": r"shipping address|email address|update the card|cancel my subscription|"
                      r"delete my account",
    "login_help": r"password|log ?in|sign in",
}
HUMAN = r"(talk|speak|chat) (to|with) (a |an |some)?(person|human|someone|agent|representative|" \
        r"manager|real)|real person|human being|a human|representative|transfer me|call me"
ANGRY = r"ridiculous|unacceptable|furious|worst|angry|terrible|scam|!!|third time|fed up"
CALM = r"\bplease\b|\bthanks\b|thank you|appreciate|no rush|when you get a chance"
PROMISE = r"refund (has been|was|is being|will be|is) (processed|issued|sent|on its way)|" \
          r"(i've|i have|we've|we have) (issued|processed|sent) (a|your|the) refund"


def _hits(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text, flags=re.I))


def _intent_hits(text: str) -> dict[str, int]:
    return {label: _hits(text, pat) for label, pat in INTENT_WORDS.items()}


def _choice(probs: dict[str, float]) -> dict:
    total = sum(probs.values())
    probs = {k: round(v / total, 4) for k, v in probs.items()}
    top = max(probs, key=probs.get)
    return {"type": "choice", "choice": top, "confidence": probs[top], "probabilities": probs}


def _score(level: int, n_levels: int, peak: float, legend: list) -> dict:
    rest = (1 - peak) / (n_levels - 1)
    probs = {str(i): round(peak if i == level else rest, 4) for i in range(n_levels)}
    expected = sum(i * p for i, p in enumerate(probs.values()))
    return {"type": "score", "score": round(expected, 4), "confidence": peak,
            "legend": {str(i): d for i, d in enumerate(legend)}, "probabilities": probs}


def _noul(p: float) -> dict:
    return {"type": "noul", "noul": p}


def _triage_answer(name: str, question: dict, text: str) -> dict:
    hits = _intent_hits(text)
    concerns = max(sum(1 for v in hits.values() if v),
                   2 if _hits(text, r"\balso\b|another thing|and one more") else 1)
    if name == "intent":
        probs = {label: 0.2 + 12.0 * hits.get(label, 0) for label in question["criteria"]}
        probs["other"] = probs.get("other", 0.2) + 0.3
        return _choice(probs)
    if name == "concern_count":
        return _score(min(max(concerns, 1), 3) - 1, 3, 0.7, question["criteria"])
    if name == "wants_human":
        return _noul(0.95 if _hits(text, HUMAN) else 0.04)
    if name == "frustration":
        level = 2 if _hits(text, ANGRY) else 0 if _hits(text, CALM) else 1
        return _score(level, 3, 0.75, question["criteria"])
    if name == "needs_llm":
        lone_status = hits["order_status"] and concerns <= 1 and \
            re.search(r"\b\d{5}\b|my order", text, flags=re.I)
        return _noul(0.08 if lone_status else 0.85)
    raise KeyError(name)


def _verify_answer(name: str, state: dict) -> dict:
    message, draft = state.get("customer_message", ""), state.get("draft_reply", "")
    if name == "addresses_all_concerns":
        asked = {k for k, v in _intent_hits(message).items() if v}
        covered = {k for k, v in _intent_hits(draft).items() if v}
        return _noul(0.9 if asked <= covered else 0.2)
    if name == "promises_unconfirmed":
        confirmed = any(r.get("tool") == "process_refund" and not r.get("is_error")
                        for r in state.get("tool_results", []))
        return _noul(0.9 if _hits(draft, PROMISE) and not confirmed else 0.08)
    if name == "tone_matches_frustration":
        angry = state.get("customer_frustration") == "angry"
        return _noul(0.3 if angry and not _hits(draft, r"sorry|apolog") else 0.85)
    raise KeyError(name)


class FakeJevTransport(httpx2.BaseTransport):
    """Answers POST /v1/systemone locally. Uncalibrated. See module docstring."""

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        state = body["state"] if isinstance(body["state"], dict) else {"message": body["state"]}
        text = state.get("message", "")
        answers = {}
        for name, question in body["questions"].items():
            try:
                answers[name] = (_verify_answer(name, state) if "draft_reply" in state
                                 else _triage_answer(name, question, text))
            except KeyError:
                answers[name] = _noul(0.5)
        payload = {"model": FAKE_MODEL, "answers": answers,
                   "usage": {"input_tokens": len(request.content) // 4, "output_tokens": 0}}
        return httpx2.Response(200, json=payload)
