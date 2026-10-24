import anthropic
import httpx2 as httpx
import pytest

from extract import extract, extract_naive
from helpers import INVOICE_TEXT, FakeClient, invoice, tool_message


def test_clean_extraction_is_accepted_in_one_call():
    client = FakeClient(tool_message(invoice()))
    r = extract(client, "invoice", INVOICE_TEXT)
    assert (r.status, r.attempts) == ("accepted", 1)


def test_request_shape():
    client = FakeClient(tool_message(invoice()))
    extract(client, "invoice", INVOICE_TEXT)
    req = client.calls[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["tool_choice"] == {"type": "auto"}
    assert req["tools"][0]["strict"] is True
    assert "thinking" not in req
    assert req["messages"][-1]["role"] == "user"  # no assistant prefill


def test_arithmetic_error_retries_with_document_failed_json_and_error():
    client = FakeClient(tool_message(invoice(stated_total=118.0)), tool_message(invoice()))
    r = extract(client, "invoice", INVOICE_TEXT)
    assert (r.status, r.attempts) == ("resolved", 2)
    prompt = client.calls[1]["messages"][0]["content"]
    assert INVOICE_TEXT in prompt
    assert '"stated_total": 118.0' in prompt
    assert "stated_total 118.00 != subtotal 100.00 + tax 8.00 = 108.00." in prompt


def test_persistent_arithmetic_error_is_unresolvable_after_max_retries():
    bad = [tool_message(invoice(stated_total=118.0 + n)) for n in range(3)]
    client = FakeClient(*bad)
    r = extract(client, "invoice", INVOICE_TEXT, max_retries=2)
    assert (r.status, r.attempts) == ("unresolvable", 3)
    assert "still failing" in r.reason


def test_identical_retry_output_stops_early():
    client = FakeClient(tool_message(invoice(stated_total=118.0)), tool_message(invoice(stated_total=118.0)))
    r = extract(client, "invoice", INVOICE_TEXT, max_retries=2)
    assert (r.status, r.attempts) == ("unresolvable", 2)
    assert "same extraction" in r.reason


def test_absent_field_null_does_not_retry():
    client = FakeClient(tool_message(invoice(warranty_date=None)))
    r = extract(client, "invoice", INVOICE_TEXT)
    assert r.status == "accepted" and r.data["warranty_date"] is None
    assert len(client.calls) == 1


def test_fabricated_absent_field_is_flagged_without_retry():
    client = FakeClient(tool_message(invoice(warranty_date="2028-01-01")))
    r = extract(client, "invoice", INVOICE_TEXT)
    assert (r.status, r.attempts) == ("unresolvable", 1)
    assert "absent from source" in r.reason
    assert len(client.calls) == 1


def test_refusal_and_truncation():
    r = extract(FakeClient(tool_message({}, stop_reason="refusal")), "invoice", INVOICE_TEXT)
    assert r.status == "refused"
    r = extract(FakeClient(*[tool_message({}, stop_reason="max_tokens")] * 3), "invoice", INVOICE_TEXT)
    assert r.status == "unresolvable" and "max_tokens" in r.reason


def test_api_errors_are_caught_by_specific_class():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.RateLimitError("slow down", response=httpx.Response(429, request=req), body=None)
    r = extract(FakeClient(err), "invoice", INVOICE_TEXT)
    assert r.status == "error" and "RateLimitError" in r.reason
    auth = anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)
    with pytest.raises(anthropic.AuthenticationError):
        extract(FakeClient(auth), "invoice", INVOICE_TEXT)


def test_naive_loop_ships_the_fabrication_or_burns_every_retry():
    fake = tool_message(invoice(warranty_date="2028-01-01"))
    c1 = FakeClient(fake)
    r1 = extract_naive(c1, "invoice", INVOICE_TEXT, ground=False)
    assert r1.status == "accepted" and r1.data["warranty_date"] == "2028-01-01" and len(c1.calls) == 1
    c2 = FakeClient(*[tool_message(invoice(warranty_date=f"2028-01-0{n}")) for n in range(1, 7)])
    r2 = extract_naive(c2, "invoice", INVOICE_TEXT, retries=5, ground=True)
    assert r2.status == "unresolvable" and len(c2.calls) == 6
    assert c2.calls[0]["tools"][0]["input_schema"]["properties"]["warranty_date"]["type"] == "string"  # not nullable
