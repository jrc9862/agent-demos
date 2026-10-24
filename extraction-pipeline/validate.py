"""Semantic checks that a JSON schema cannot express.

Each Issue is either retryable (the document probably contains the right answer and the model
got it wrong, e.g. arithmetic) or not (the information is not in the document, so no retry helps).
"""
import datetime as dt
from dataclasses import dataclass

from schema import FIELDS, _ENUMS

TOLERANCE = 0.005

# A non-null value for these fields is only plausible if the source contains the keyword at all.
ANCHORS = {"warranty_date": "warrant", "notice_days": "notice", "governing_law": "law"}


@dataclass(frozen=True)
class Issue:
    field: str
    code: str        # missing | bad_enum | bad_date | other_detail | arithmetic | ungrounded | confidence
    message: str
    retryable: bool


def _is_iso_date(value) -> bool:
    try:
        dt.date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def validate(doc_type: str, data: dict, source: str, grounding: bool = True) -> list[Issue]:
    issues: list[Issue] = []
    spec = FIELDS[doc_type]
    lowered = source.lower()

    for name, (_, nullable) in spec.items():
        value = data.get(name)
        if value is None and not nullable:
            issues.append(Issue(name, "missing", f"{name} is required but was null.", True))
        if (doc_type, name) in _ENUMS and value is not None and value not in _ENUMS[(doc_type, name)]:
            issues.append(Issue(name, "bad_enum", f"{name}={value!r} is not one of {_ENUMS[(doc_type, name)]}.", True))
        if name.endswith("_date") and value is not None and not _is_iso_date(value):
            issues.append(Issue(name, "bad_date", f"{name}={value!r} is not a valid YYYY-MM-DD date.", True))
        anchor = ANCHORS.get(name)
        if grounding and anchor and value is not None and anchor not in lowered:
            issues.append(Issue(name, "ungrounded",
                                f"{name}={value!r} but the document never mentions '{anchor}'. "
                                "The information is absent from the source.", False))

    cat_field = "category" if doc_type == "invoice" else "study_design" if doc_type == "abstract" else None
    if cat_field and data.get(cat_field) == "other" and not data.get("other_detail"):
        issues.append(Issue("other_detail", "other_detail",
                            f"{cat_field} is 'other' so other_detail must name it.", True))

    if doc_type == "invoice":
        issues += _check_invoice_arithmetic(data)

    conf = data.get("confidence") or {}
    for name in spec:
        c = conf.get(name)
        if not isinstance(c, (int, float)) or isinstance(c, bool) or not 0.0 <= c <= 1.0:
            issues.append(Issue(name, "confidence", f"confidence[{name}]={c!r} must be a number in [0, 1].", True))
    return issues


def _check_invoice_arithmetic(data: dict) -> list[Issue]:
    try:
        sub, tax, stated = float(data["subtotal"]), float(data["tax"]), float(data["stated_total"])
    except (KeyError, TypeError, ValueError):
        return []  # the missing-field check already reported it
    expected = round(sub + tax, 2)
    issues = []
    if abs(stated - expected) > TOLERANCE:
        issues.append(Issue("stated_total", "arithmetic",
                            f"stated_total {stated:.2f} != subtotal {sub:.2f} + tax {tax:.2f} = {expected:.2f}.", True))
    calc = data.get("calculated_total")
    if isinstance(calc, (int, float)) and abs(calc - expected) > TOLERANCE:
        issues.append(Issue("calculated_total", "arithmetic",
                            f"calculated_total {calc:.2f} != subtotal {sub:.2f} + tax {tax:.2f} = {expected:.2f}.", True))
    return issues
