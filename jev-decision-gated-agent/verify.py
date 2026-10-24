"""Second Jev call: does the LLM's draft reply hold up against the message and the tool results?

All three checks go in one `system_one` call. gate.failed_checks applies the thresholds.
"""

import time
from dataclasses import dataclass

from typesafe_sdk import Noul, TypeSafeClient

import gate

VERIFY_QUESTIONS = {
    "addresses_all_concerns": Noul(
        instructions="The draft reply responds to every distinct request in the customer message.",
        criteria={"false": "At least one request in the customer message is ignored."}),
    "promises_unconfirmed": Noul(
        instructions=("The draft reply states or promises an outcome (refund issued, address "
                      "changed, item shipped) that the tool results do not confirm."),
        criteria={"true": "Claims an action happened or will happen with no successful tool "
                          "result backing it."}),
    "tone_matches_frustration": Noul(
        instructions="The draft reply's tone fits the customer's frustration level.",
        criteria={"false": "Breezy or upbeat toward an angry customer, or curt toward a calm one."}),
}


@dataclass(frozen=True)
class VerifyResult:
    probabilities: dict[str, float]
    failed: list[str]
    jev_model: str
    input_tokens: int
    latency_ms: float

    @property
    def passed(self) -> bool:
        return not self.failed


def verify(client: TypeSafeClient, message: str, tool_results: list[dict], draft: str,
           frustration: str | None) -> VerifyResult:
    state = {"customer_message": message, "tool_results": tool_results, "draft_reply": draft,
             "customer_frustration": frustration or "unknown"}
    start = time.perf_counter()
    response = client.system_one(state, VERIFY_QUESTIONS)
    latency_ms = (time.perf_counter() - start) * 1000
    probs = {name: answer.noul for name, answer in response.nouls.items()}
    return VerifyResult(probabilities=probs, failed=gate.failed_checks(probs),
                        jev_model=response.model, input_tokens=response.usage.input_tokens or 0,
                        latency_ms=latency_ms)
