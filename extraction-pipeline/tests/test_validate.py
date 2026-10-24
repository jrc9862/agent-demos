from helpers import INVOICE_TEXT, invoice
from validate import validate


def codes(issues):
    return {(i.field, i.code) for i in issues}


def test_clean_invoice_passes():
    assert validate("invoice", invoice(), INVOICE_TEXT) == []


def test_arithmetic_mismatch_gives_specific_retryable_error():
    issues = validate("invoice", invoice(stated_total=118.0), INVOICE_TEXT)
    arith = [i for i in issues if i.code == "arithmetic"]
    assert [i.message for i in arith] == ["stated_total 118.00 != subtotal 100.00 + tax 8.00 = 108.00."]
    assert arith[0].retryable


def test_model_calculated_total_is_also_checked():
    issues = validate("invoice", invoice(calculated_total=99.0), INVOICE_TEXT)
    assert codes(issues) == {("calculated_total", "arithmetic")}


def test_absent_field_null_is_accepted():
    assert validate("invoice", invoice(warranty_date=None), INVOICE_TEXT) == []


def test_invented_value_for_absent_field_is_not_retryable():
    issues = validate("invoice", invoice(warranty_date="2028-01-01"), INVOICE_TEXT)
    assert codes(issues) == {("warranty_date", "ungrounded")}
    assert not issues[0].retryable


def test_grounded_warranty_date_passes():
    text = INVOICE_TEXT + " Warranty valid until 1 January 2028."
    assert validate("invoice", invoice(warranty_date="2028-01-01"), text) == []


def test_other_category_requires_detail():
    issues = validate("invoice", invoice(category="other"), INVOICE_TEXT)
    assert ("other_detail", "other_detail") in codes(issues)
    assert validate("invoice", invoice(category="other", other_detail="catering"), INVOICE_TEXT) == []


def test_bad_enum_bad_date_and_confidence_range():
    d = invoice(category="furniture", invoice_date="March 1")
    d["confidence"]["vendor"] = 1.4
    assert codes(validate("invoice", d, INVOICE_TEXT)) >= {
        ("category", "bad_enum"), ("invoice_date", "bad_date"), ("vendor", "confidence")}


def test_required_field_null_is_flagged():
    assert ("vendor", "missing") in codes(validate("invoice", invoice(vendor=None), INVOICE_TEXT))
