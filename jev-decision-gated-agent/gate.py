"""Thresholds live here, in code: visible, versioned, testable.

Jev supplies probabilities. This file decides what they mean. Every routing decision is appended
to the decision log with the probabilities and thresholds that produced it.
"""

import json
import os
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from triage import FRUSTRATION_LABELS, TriageResult

# Triage thresholds, set by eval/sweep_thresholds.py from the 60 labeled messages.
WANTS_HUMAN_ESCALATE = 0.50   # wants_human.noul >  this -> escalate before anything else
INTENT_CONFIDENCE_MIN = 0.80  # intent.confidence < this -> LLM path, never a guessed fast path
NEEDS_LLM_FAST_MAX = 0.40     # needs_llm.noul    < this (and intent is fast-pathable) -> fast path
# Fast-path intent -> template name. Each template is string formatting over a tool result or
# fixed text; none moves money.
FAST_TEMPLATES = {name: name for name in ("order_status", "account_change", "return_how",
                                          "login_help", "invoice_request", "refund_status")}
FAST_PATH_INTENTS = frozenset(FAST_TEMPLATES)
# These templates state facts about one order, so the message must name it. A message like
# "When will my shoes arrive?" gets no template: a status list has no dates.
ORDER_ID = re.compile(r"\b(\d{5})\b")
FAST_NEEDS_ORDER_ID = frozenset({"order_status", "refund_status"})
FAST_PATH_MAX_CONCERNS = 1                  # one request only
FAST_PATH_BLOCKED_FRUSTRATION = FRUSTRATION_LABELS[-1]   # "angry": a template is the wrong reply

# Verification thresholds. A check fails when its probability is on the wrong side.
ADDRESSES_ALL_MIN = 0.50          # addresses_all_concerns.noul must be >= this
PROMISES_UNCONFIRMED_MAX = 0.50   # promises_unconfirmed.noul must be <  this
TONE_MATCH_MIN = 0.50             # tone_matches_frustration.noul must be >= this

LOG_PATH = Path(os.environ.get("DECISION_LOG", Path(__file__).parent / "logs" / "decisions.jsonl"))


class Route(str, Enum):
    ESCALATE = "ESCALATE"
    FAST_PATH = "FAST_PATH"
    LLM_PATH = "LLM_PATH"


@dataclass(frozen=True)
class Decision:
    route: Route
    reason: str
    template: str | None = None     # set on FAST_PATH: which template answers


def decide(t: TriageResult | None, message: str | None = None) -> Decision:
    """Pure routing function. Order matters: escalation is checked first."""
    if t is None:
        return Decision(Route.LLM_PATH, "triage unavailable; LLM path handles everything")
    if t.wants_human > WANTS_HUMAN_ESCALATE:
        return Decision(Route.ESCALATE, f"wants_human {t.wants_human:.2f} > {WANTS_HUMAN_ESCALATE}")
    if t.intent_confidence < INTENT_CONFIDENCE_MIN:
        return Decision(Route.LLM_PATH,
                        f"intent confidence {t.intent_confidence:.2f} < {INTENT_CONFIDENCE_MIN}")
    # The fast path needs every condition; no single vague Noul can send a reply on its own.
    if t.intent in FAST_NEEDS_ORDER_ID and message is not None and not ORDER_ID.search(message):
        return Decision(Route.LLM_PATH, f"intent {t.intent} names no order ID")
    fast = (t.intent in FAST_PATH_INTENTS and t.needs_llm < NEEDS_LLM_FAST_MAX
            and t.concern_count <= FAST_PATH_MAX_CONCERNS
            and t.frustration != FAST_PATH_BLOCKED_FRUSTRATION)
    if fast:
        return Decision(Route.FAST_PATH,
                        f"intent {t.intent} ({t.intent_confidence:.2f}), needs_llm "
                        f"{t.needs_llm:.2f} < {NEEDS_LLM_FAST_MAX}, {t.concern_count} request, "
                        f"frustration {t.frustration}", FAST_TEMPLATES[t.intent])
    return Decision(Route.LLM_PATH, f"intent {t.intent}, needs_llm {t.needs_llm:.2f}, "
                                    f"concern_count {t.concern_count}, frustration {t.frustration}")


def thresholds() -> dict:
    return {"WANTS_HUMAN_ESCALATE": WANTS_HUMAN_ESCALATE,
            "INTENT_CONFIDENCE_MIN": INTENT_CONFIDENCE_MIN,
            "NEEDS_LLM_FAST_MAX": NEEDS_LLM_FAST_MAX,
            "FAST_PATH_INTENTS": sorted(FAST_PATH_INTENTS)}


def route(t: TriageResult | None, message_id: str, log_path: Path | None = None,
          message: str | None = None) -> Decision:
    """Decide and log. The log entry carries every probability the decision could depend on."""
    decision = decide(t, message)
    log_event("route", log_path, message_id=message_id, route=decision.route.value,
              reason=decision.reason, template=decision.template, thresholds=thresholds(),
              probabilities=t.probabilities() if t else None,
              jev_model=t.jev_model if t else None)
    return decision


def failed_checks(p: dict[str, float]) -> list[str]:
    """Names of verification checks that failed, given Jev's noul probabilities."""
    failed = []
    if p["addresses_all_concerns"] < ADDRESSES_ALL_MIN:
        failed.append("addresses_all_concerns")
    if p["promises_unconfirmed"] >= PROMISES_UNCONFIRMED_MAX:
        failed.append("promises_unconfirmed")
    if p["tone_matches_frustration"] < TONE_MATCH_MIN:
        failed.append("tone_matches_frustration")
    return failed


def log_event(kind: str, log_path: Path | None = None, **fields) -> None:
    path = Path(log_path or LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"ts": time.time(), "kind": kind, **fields}, default=str) + "\n")
