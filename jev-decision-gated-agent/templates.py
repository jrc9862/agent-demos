"""Fast-path reply templates. No LLM. String formatting over tool results."""


def order_status(order: dict) -> str:
    oid, status = order["order_id"], order["status"]
    if status == "shipped":
        return (f"Order {oid} shipped with {order['carrier']} (tracking {order['tracking']}) and "
                f"is expected to arrive {order['eta']}.")
    if status == "delivered":
        return f"Order {oid} was delivered on {order['delivered']}."
    if status == "processing":
        return f"Order {oid} was placed {order['placed']} and is being prepared for shipment."
    if status == "cancelled":
        return f"Order {oid} was cancelled. No charge was taken for it."
    return f"Order {oid} has status: {status}."



def backend_unavailable() -> str:
    return ("Our order system isn't responding right now, so I can't see your order status. "
            "Nothing is wrong with your order that I know of; please try again in a few minutes.")


def escalated(ticket_id: str) -> str:
    return (f"I've passed this to a member of our support team (ticket {ticket_id}). They have "
            "the details and will contact you directly.")


def account_change() -> str:
    return ("Changes to your address, email, saved card, or subscription are made by our support "
            "team, not in chat.")


def return_how() -> str:
    return ("You can return most items within 30 days of delivery. To start a return, open "
            "Account > Orders, choose the order, and select Return items. We email a prepaid "
            "return label to the address on your account; print it, pack the item, and drop it "
            "off with the carrier named on the label. Your refund is issued after the item "
            "arrives at our warehouse.")


def login_help() -> str:
    return ("To reset your password, choose Forgot password on the sign-in page and enter the "
            "email on your account. We send a reset link that is valid for one hour. If nothing "
            "arrives in ten minutes, check your spam folder, then request a new link.")


def invoice(order: dict) -> str:
    items = ", ".join(order["items"])
    return (f"Your most recent order is {order['order_id']} ({items}), placed {order['placed']}. "
            f"Its invoice ID is {order['invoice_id']}; you can download it from "
            "Account > Orders > Invoices.")


def refund_status(order: dict) -> str | None:
    """None when the order has no refund on record."""
    refunds = order.get("refunds") or []
    if not refunds:
        return None
    lines = [f"a refund of ${r['amount']:.2f} (refund {r['refund_id']}) was issued on {r['date']}"
             for r in refunds]
    return (f"For order {order['order_id']}, " + "; ".join(lines) + ". It can take 5 to 10 "
            "business days to appear on your statement.")


def refund_not_on_record(order_id: str) -> str:
    return (f"I don't see a refund on record for order {order_id}. A refund request goes to our "
            "team for review.")
