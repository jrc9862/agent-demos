"""Single-document path: extract -> validate -> targeted retry -> accept | resolved | unresolvable.

Usage:
  python extract.py docs/inv-003.txt            # doc type inferred from the file prefix
  python extract.py --counter-demo              # naive retry loop vs this pipeline; needs a key
"""
import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from few_shot import examples_block
from schema import MODEL, TOOL_NAME, build_tool
from validate import Issue, validate

PREFIX = {"inv": "invoice", "abs": "abstract", "con": "contract"}
HERE = Path(__file__).parent


class ExtractionError(Exception):
    pass


class Refused(ExtractionError):
    pass


class Truncated(ExtractionError):
    pass


class NoToolCall(ExtractionError):
    pass


@dataclass
class Result:
    doc_id: str
    doc_type: str
    status: str                  # accepted | resolved | unresolvable | refused | error
    data: dict | None = None
    reason: str = ""
    attempts: int = 0
    issues: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)


def system_prompt(doc_type: str, allow_null: bool = True) -> str:
    rules = [f"You extract fields from one {doc_type} document. Call the `{TOOL_NAME}` tool exactly once.",
             "Copy values from the document; never infer a value the document does not state.",
             "stated_total is the total as printed, even if it disagrees with the line items.",
             "If the document describes a category or design outside the enum, use 'other' and describe it "
             "in other_detail.",
             "Contracts: when an amendment replaces a clause, report the amended value.",
             "Give each field a confidence from 0.0 to 1.0. Use below 0.7 when the text is ambiguous."]
    rules.append("If a nullable field is not stated in the document, return null." if allow_null
                 else "Every field is required.")
    return "\n".join(rules) + "\n\n" + examples_block(doc_type)


def build_params(doc_type: str, user_text: str, allow_null: bool = True) -> dict:
    """Request body shared by the single-document and Batches paths.

    tool_choice is auto: forcing a tool returns 400 on claude-opus-5-5. `strict: true` on the tool
    guarantees the shape of the call; the system prompt tells the model to make it.
    """
    return {"model": MODEL, "max_tokens": 4096, "system": system_prompt(doc_type, allow_null),
            "tools": [build_tool(doc_type, allow_null)], "tool_choice": {"type": "auto"},
            "messages": [{"role": "user", "content": user_text}]}


def initial_prompt(text: str) -> str:
    return f"<document>\n{text}\n</document>"


def retry_prompt(text: str, failed: dict, issues: list[Issue]) -> str:
    errors = "\n".join(f"- {i.message}" for i in issues)
    return (f"{initial_prompt(text)}\n\nYour previous extraction:\n{json.dumps(failed)}\n\n"
            f"It failed these checks:\n{errors}\n\nRe-read the document and call `{TOOL_NAME}` again. "
            "If the document itself contains the inconsistent numbers, keep the printed values.")


def parse_response(message) -> dict:
    """Return the tool input, or raise. Always checks stop_reason first."""
    if message.stop_reason == "refusal":
        raise Refused(str(getattr(message, "stop_details", "") or "refused"))
    if message.stop_reason == "max_tokens":
        raise Truncated("output hit max_tokens before the tool call completed")
    for block in message.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return block.input
    raise NoToolCall(f"stop_reason={message.stop_reason}, no {TOOL_NAME} tool call")


def call_model(client, doc_type: str, prompt: str, allow_null: bool = True) -> dict:
    return parse_response(client.messages.create(**build_params(doc_type, prompt, allow_null)))


def extract(client, doc_type: str, text: str, doc_id: str = "doc", max_retries: int = 2) -> Result:
    res = Result(doc_id, doc_type, "error")
    prompt, prev = initial_prompt(text), None
    for attempt in range(max_retries + 1):
        res.attempts = attempt + 1
        try:
            data = call_model(client, doc_type, prompt)
        except Refused as e:
            res.status, res.reason = "refused", str(e)
            return res
        except (Truncated, NoToolCall) as e:
            res.reason = str(e)
            continue
        except anthropic.AuthenticationError:
            raise  # a config problem; every document would fail the same way
        except (anthropic.RateLimitError, anthropic.BadRequestError, anthropic.APIStatusError) as e:
            res.reason = f"{type(e).__name__}: {e}"
            return res
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
            res.reason = f"{type(e).__name__}: {e}"
            return res
        issues = validate(doc_type, data, text)
        res.data, res.issues = data, [i.message for i in issues]
        res.history.append({"attempt": attempt + 1, "data": data, "issues": res.issues})
        if not issues:
            res.status = "accepted" if attempt == 0 else "resolved"
            return res
        absent = [i for i in issues if not i.retryable]
        if absent:  # information is not in the source; another call cannot add it
            res.status, res.reason = "unresolvable", "absent from source: " + "; ".join(i.message for i in absent)
            return res
        if data == prev:
            res.status, res.reason = "unresolvable", "model returned the same extraction; the source is likely inconsistent"
            return res
        prev, prompt = data, retry_prompt(text, data, issues)
    res.status = "unresolvable"
    res.reason = res.reason or f"still failing after {max_retries} retries"
    return res


def extract_naive(client, doc_type: str, text: str, retries: int = 5, ground: bool = False) -> Result:
    """Counter-demo: no nullable fields, retry on every error until it passes or retries run out.

    ground=False is the naive validator (shape and arithmetic only). ground=True adds the
    absent-from-source check but still retries on it, which is the "retry until it passes" loop.
    """
    res, prompt = Result("naive", doc_type, "unresolvable"), initial_prompt(text)
    for attempt in range(retries + 1):
        res.attempts = attempt + 1
        data = call_model(client, doc_type, prompt, allow_null=False)
        issues = validate(doc_type, data, text, grounding=ground)
        res.data, res.issues = data, [i.message for i in issues]
        res.history.append({"attempt": attempt + 1, "prompt_tail": prompt[-400:], "data": data, "issues": res.issues})
        if not issues:
            res.status = "accepted"
            return res
        prompt = retry_prompt(text, data, issues)
    return res


def counter_demo(client) -> None:
    truth = json.loads((HERE / "docs" / "truth.json").read_text())
    ids = [k for k, v in truth.items() if v["doc_type"] == "invoice"
           and v["fields"]["warranty_date"] is None and v["fields"]["category"] != "other"][:3]
    out = []
    for doc_id in ids:
        text = (HERE / "docs" / f"{doc_id}.txt").read_text()
        entry = {"doc_id": doc_id, "truth_warranty_date": None}
        for name, ground in (("naive_no_grounding", False), ("naive_retry_5x", True)):
            r = extract_naive(client, "invoice", text, ground=ground)
            entry[name] = {"calls": r.attempts, "final_warranty_date": r.data["warranty_date"], "history": r.history}
        p = extract(client, "invoice", text, doc_id)
        entry["pipeline"] = {"calls": p.attempts, "status": p.status, "final_warranty_date": (p.data or {}).get("warranty_date")}
        out.append(entry)
        print(doc_id, {k: v.get("final_warranty_date") for k, v in entry.items() if isinstance(v, dict)})
    path = HERE / "results" / "counter_demo_transcript.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"transcript: {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--counter-demo", action="store_true")
    ap.add_argument("--max-retries", type=int, default=2)
    args = ap.parse_args()
    client = anthropic.Anthropic()
    if args.counter_demo:
        counter_demo(client)
        return 0
    if not args.path:
        ap.error("path or --counter-demo required")
    p = Path(args.path)
    r = extract(client, PREFIX[p.stem[:3]], p.read_text(), p.stem, args.max_retries)
    print(json.dumps({"status": r.status, "attempts": r.attempts, "reason": r.reason, "issues": r.issues,
                      "data": r.data}, indent=1))
    return 0 if r.status in ("accepted", "resolved") else 1


if __name__ == "__main__":
    sys.exit(main())
