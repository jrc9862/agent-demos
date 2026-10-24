"""One Jev call, five questions, typed result.

All five triage questions go in a single `system_one` call: Jev answers every question about one
state in one pass, so this is one round trip per message, not five.
"""

import time
from dataclasses import asdict, dataclass

from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

INTENTS = {
    "order_status": {
        "definition": "Asks where an order is, when it will arrive, or what its shipping status is.",
        "contrast": "Not for a complaint that the order is wrong or damaged (other), and not for "
                    "whether a refund went through (refund_status)."},
    "refund_request": {
        "definition": "Wants money back for an order or item, for a stated reason such as damage, "
                      "wrong item, or a leak.",
        "contrast": "Not for asking whether an existing refund has gone through (refund_status), "
                    "and not for asking how to send something back (return_how)."},
    "refund_status": {
        "definition": "Asks whether a refund already requested or promised has gone through.",
        "contrast": "Not for asking for a new refund (refund_request); the customer already "
                    "believes a refund is under way."},
    "return_how": {
        "definition": "Asks how to send an item back: the process, the label, the window.",
        "contrast": "Not for demanding the money (refund_request); this customer wants the "
                    "procedure."},
    "billing_dispute": {
        "definition": "A charge on the customer's card is wrong, duplicated, or unexplained.",
        "contrast": "Not for requesting a copy of an invoice (invoice_request), and not for a "
                    "refund of a correct charge (refund_request)."},
    "invoice_request": {
        "definition": "Asks for an invoice or receipt for a purchase.",
        "contrast": "Not for disputing the amount on it (billing_dispute)."},
    "account_change": {
        "definition": "Wants the account changed: shipping address, email, saved card, cancel a "
                      "subscription, or delete the account.",
        "contrast": "Not for being unable to sign in (login_help)."},
    "login_help": {
        "definition": "Cannot log in, or needs a password reset.",
        "contrast": "Not for changing profile details once logged in (account_change)."},
    "other": {
        "definition": "Anything that matches none of the other options, or is too vague to tell.",
        "contrast": "Choose this over guessing when no other option clearly fits."},
}
CONCERN_LEVELS = ["One distinct request", "Two distinct requests", "Three or more distinct requests"]
FRUSTRATION_LEVELS = ["Calm or friendly", "Civil but impatient", "Angry or hostile"]
FRUSTRATION_LABELS = ["calm", "civil", "angry"]

# Shared with eval/run_eval.py so Jev and the LLM are asked the same intent question.
INTENT_QUESTION = "What is the customer's first request about?"
# What each fast-path template can say, given to Jev as the named state field
# `reply_template_covers` so `needs_llm` is one judgment: does this message need something no
# listed template provides?
TEMPLATE_COVERS = {
    "order_status": ["status, carrier, tracking number and arrival date of one order the customer "
                     "names by its order ID",
                     "a plain status list of all orders when none is named (no dates or tracking)",
                     "does not address an order marked delivered that the customer says never "
                     "arrived, or a package that is late"],
    "account_change": ["tells the customer a support teammate will make the requested change"],
    "return_how": ["30-day return window", "how to start a return", "where the prepaid label comes from"],
    "login_help": ["how to reset a password", "how to request a new reset email"],
    "invoice_request": ["the most recent order and its invoice ID"],
    "refund_status": ["whether a refund was issued on an order the customer names by its order ID, "
                      "with its ID, amount and date",
                      "that no refund is on record and a teammate will review the request"],
}

TRIAGE_QUESTIONS = {
    "intent": Choice(instructions=INTENT_QUESTION, criteria=INTENTS),
    "concern_count": Score(instructions="How many distinct requests does the message contain?",
                           criteria=CONCERN_LEVELS),
    "wants_human": Noul(instructions="The customer explicitly asks to talk to a human agent."),
    "frustration": Score(instructions="How frustrated is the customer?", criteria=FRUSTRATION_LEVELS),
    "needs_llm": Noul(instructions=(
        "The customer needs something that no template listed in `reply_template_covers` provides."),
        criteria={"true": "Wants an action, an explanation, a decision, an apology, or an answer "
                          "that none of the listed templates covers.",
                  "false": "One listed template covers everything the customer asked."}),
}


@dataclass(frozen=True)
class TriageResult:
    intent: str
    intent_confidence: float
    intent_probabilities: dict[str, float]
    concern_count: int                    # argmax level, 1..3 (3 means "3+")
    concern_probabilities: dict[int, float]
    wants_human: float                    # noul: P(yes)
    frustration: str
    frustration_probabilities: dict[str, float]
    needs_llm: float                      # noul: P(yes)
    jev_model: str
    input_tokens: int
    latency_ms: float

    def probabilities(self) -> dict:
        """Everything a routing decision depended on, for the decision log."""
        return {k: v for k, v in asdict(self).items() if k not in ("jev_model", "input_tokens", "latency_ms")}

    def facts(self) -> dict:
        """What the LLM path is told, so it does not re-derive it."""
        return {"intent": self.intent, "intent_confidence": round(self.intent_confidence, 3),
                "concern_count": self.concern_count if self.concern_count < 3 else "3+",
                "frustration": self.frustration}


def triage(client: TypeSafeClient, message: str, customer: dict | None = None) -> TriageResult:
    """Raises typesafe_sdk.TypeSafeError subclasses; the caller decides the fallback."""
    state = {"message": message, "reply_template_covers": TEMPLATE_COVERS}
    if customer:
        state["customer"] = customer
    start = time.perf_counter()
    response = client.system_one(state, TRIAGE_QUESTIONS)
    latency_ms = (time.perf_counter() - start) * 1000

    intent = response.choices["intent"]
    concern = response.scores["concern_count"].probabilities
    frustration = response.scores["frustration"].probabilities
    top_frustration = max(frustration, key=frustration.get)
    return TriageResult(
        intent=intent.choice,
        intent_confidence=intent.confidence,
        intent_probabilities=dict(intent.probabilities),
        concern_count=max(concern, key=concern.get) + 1,
        concern_probabilities={level + 1: p for level, p in concern.items()},
        wants_human=response.nouls["wants_human"].noul,
        frustration=FRUSTRATION_LABELS[top_frustration],
        frustration_probabilities={FRUSTRATION_LABELS[i]: p for i, p in frustration.items()},
        needs_llm=response.nouls["needs_llm"].noul,
        jev_model=response.model,
        input_tokens=response.usage.input_tokens or 0,
        latency_ms=latency_ms,
    )
