"""Extraction tool schema, built per document type.

Shape is enforced by `strict: true` on the tool. Strict mode needs every property listed in
`required` and `additionalProperties: false`, so "optional" is expressed as a nullable type.
Absence is data: the model returns null instead of inventing a value.
"""
import copy

MODEL = "claude-opus-5-5"
TOOL_NAME = "extract"

INVOICE_CATEGORIES = ["software", "hardware", "services", "travel", "other"]
STUDY_DESIGNS = ["rct", "cohort", "survey", "meta_analysis", "other"]

# field -> (JSON type, nullable). Enums are added in _ENUMS.
FIELDS = {
    "invoice": {
        "invoice_number": ("string", False),
        "vendor": ("string", False),
        "invoice_date": ("string", False),       # ISO 8601
        "category": ("string", False),
        "other_detail": ("string", True),        # required when category == "other"
        "subtotal": ("number", False),
        "tax": ("number", False),
        "stated_total": ("number", False),       # the total printed on the document
        "calculated_total": ("number", False),   # the model's own subtotal + tax
        "warranty_date": ("string", True),       # ISO 8601; absent from most invoices
    },
    "abstract": {
        "title": ("string", False),
        "authors": ("array", False),
        "year": ("integer", False),
        "study_design": ("string", False),
        "other_detail": ("string", True),
        "sample_size": ("integer", True),
        "reference_count": ("integer", False),
    },
    "contract": {
        "parties": ("array", False),
        "effective_date": ("string", False),
        "term_months": ("integer", False),
        "payment_due_days": ("integer", False),
        "notice_days": ("integer", True),
        "governing_law": ("string", True),
        "auto_renew": ("boolean", True),
    },
}

_ENUMS = {
    ("invoice", "category"): INVOICE_CATEGORIES,
    ("abstract", "study_design"): STUDY_DESIGNS,
}

DESCRIPTIONS = {
    "stated_total": "The total exactly as printed on the document, even if it looks wrong.",
    "calculated_total": "subtotal + tax, computed by you.",
    "warranty_date": "Warranty expiry as YYYY-MM-DD. null if the document does not state one.",
    "other_detail": "When the value is 'other': a short lowercase noun phrase naming it, e.g. "
                    "'equipment rental' or 'qualitative interview study'. Otherwise null.",
    "notice_days": "Termination notice period in days. null if the contract does not say.",
    "governing_law": "Jurisdiction name only, as a bare proper noun: 'Oregon', not 'State of Oregon' "
                     "or 'the laws of Oregon'. null if the contract does not say.",
    "auto_renew": "true or false if stated; null if the contract is silent.",
    "term_months": "Final term in months after applying any amendment.",
    "payment_due_days": "Final payment period in days after applying any amendment.",
    "sample_size": "Number of participants. null if not reported.",
    "reference_count": "Number of distinct works cited, however the citations are formatted.",
    "invoice_number": "The invoice identifier exactly as printed, e.g. 'INV-2026-1001'.",
    "vendor": "The issuing vendor's name only, as printed, e.g. 'Harbor Labs'. No address or email.",
    "subtotal": "Pre-tax amount as a plain number, no currency symbol or thousands separator.",
    "tax": "Tax amount as a plain number, no currency symbol or thousands separator.",
    "title": "The study title only, as printed, without authors or year.",
    "authors": "Author surnames only, e.g. ['Quinn', 'Osei'], in the order printed.",
    "year": "Four-digit publication year.",
    "parties": "Party names as printed, without role words or punctuation added, e.g. ['Harbor Labs', 'Alder & Finch'].",
    "invoice_date": "YYYY-MM-DD",
    "effective_date": "YYYY-MM-DD",
}


def field_names(doc_type: str) -> list[str]:
    return list(FIELDS[doc_type])


def nullable_fields(doc_type: str) -> list[str]:
    return [f for f, (_, n) in FIELDS[doc_type].items() if n]


def _prop(doc_type: str, name: str, jtype: str, nullable: bool) -> dict:
    prop: dict = {"type": [jtype, "null"] if nullable else jtype}
    if jtype == "array":
        prop["items"] = {"type": "string"}
    if (doc_type, name) in _ENUMS:
        prop = {"type": "string", "enum": list(_ENUMS[(doc_type, name)])}
    if name in DESCRIPTIONS:
        prop["description"] = DESCRIPTIONS[name]
    return prop


def build_tool(doc_type: str, allow_null: bool = True) -> dict:
    """Return the extraction tool definition.

    allow_null=False strips every nullable type. It exists only for the counter-demo, where it
    forces the model to produce a value for fields the document does not contain.
    """
    props = {}
    for name, (jtype, nullable) in FIELDS[doc_type].items():
        props[name] = _prop(doc_type, name, jtype, nullable and allow_null)
    conf = {
        "type": "object",
        "description": "Per-field confidence from 0.0 to 1.0, one key per extracted field.",
        "properties": {name: {"type": "number"} for name in FIELDS[doc_type]},
        "required": list(FIELDS[doc_type]),
        "additionalProperties": False,
    }
    props["confidence"] = conf
    return {
        "name": TOOL_NAME,
        "description": f"Record the fields extracted from one {doc_type} document.",
        "strict": True,
        "input_schema": copy.deepcopy({
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
        }),
    }
