"""Generate the synthetic corpus: docs/<id>.txt plus docs/truth.json (ground truth per doc).

Deterministic (fixed seed). Three document types:
  invoice   formats: narrative, table, email (email is held out of the few-shot examples)
  abstract  formats: inline citations, bibliography, sources (sources is held out)
  contract  formats: clauses, letter. Deliberately hard: terms are spelled out in words and
            amendments override earlier clauses, so the correct value is the amended one.

Usage: python generate_docs.py   (rewrites docs/)
"""
import datetime as dt
import json
import random
from pathlib import Path

DOCS = Path(__file__).parent / "docs"
VENDORS = ["Northwind Supply", "Harbor Labs", "Pinecrest Software", "Alder & Finch", "Quill Freight",
           "Blue Heron Systems", "Tallgrass Co", "Meridian Works"]
CATEGORY_LABEL = {"software": "Software licence", "hardware": "Hardware purchase",
                  "services": "Professional services", "travel": "Travel expenses"}
OTHER_CATEGORIES = ["catering", "equipment rental", "venue hire", "printing"]
SURNAMES = ["Okafor", "Lindqvist", "Marsh", "Tanaka", "Reyes", "Haddad", "Novak", "Barros", "Quinn", "Osei"]
DESIGN_LABEL = {"rct": "randomised controlled trial", "cohort": "prospective cohort study",
                "survey": "cross-sectional survey", "meta_analysis": "meta-analysis"}
TOPICS = ["sleep duration and recall", "remote work and attention", "urban tree cover and heat",
          "dietary fibre and glucose", "tutoring and exam scores", "noise exposure and hearing"]
WORDS = {12: "twelve (12) months", 18: "eighteen (18) months", 24: "two (2) years",
         36: "three (3) years", 30: "thirty (30) months"}
PAY_WORDS = {15: "fifteen (15)", 30: "thirty (30)", 45: "forty-five (45)", 60: "sixty (60)"}
STATES = ["Delaware", "New York", "Oregon", "Texas"]


def _date(rng, y0=2024, y1=2026):
    return dt.date(rng.randint(y0, y1), rng.randint(1, 12), rng.randint(1, 28))


def _long(d: dt.date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


def invoice(rng, fmt, i, bad_total=False):
    cat = rng.choice(list(CATEGORY_LABEL) + ["other"] * 2)
    detail = rng.choice(OTHER_CATEGORIES) if cat == "other" else None
    label = detail.capitalize() if detail else CATEGORY_LABEL[cat]
    items = [(f"Item {chr(65 + k)}", rng.randint(1, 5), rng.randint(40, 900)) for k in range(rng.randint(2, 4))]
    subtotal = float(sum(q * p for _, q, p in items))
    tax = round(subtotal * rng.choice([0.05, 0.07, 0.08, 0.0825]), 2)
    stated = round(subtotal + tax + (rng.choice([-1, 1]) * rng.randint(5, 40) if bad_total else 0), 2)
    d, vendor, num = _date(rng), rng.choice(VENDORS), f"INV-2026-{1000 + i}"
    warranty = _date(rng, 2027, 2029) if rng.random() < 0.25 else None
    wline = f"Warranty valid until {_long(warranty)}." if warranty else ""
    if fmt == "narrative":
        lines = "; ".join(f"{q} x {n} at ${p:.2f}" for n, q, p in items)
        text = (f"Invoice {num} from {vendor}, issued {_long(d)}. This covers: {lines}. Purchase type: {label}. "
                f"Subtotal comes to ${subtotal:.2f}, tax is ${tax:.2f}, so the amount due is ${stated:.2f}. {wline}")
    elif fmt == "table":
        rows = "\n".join(f"{n:<10}{q:>4}{p:>10.2f}" for n, q, p in items)
        text = (f"{vendor}\nINVOICE {num}   Date: {d.isoformat()}\nCategory: {label}\n\n"
                f"{'Item':<10}{'Qty':>4}{'Price':>10}\n{rows}\n\nSubtotal {subtotal:.2f}\nTax {tax:.2f}\n"
                f"TOTAL {stated:.2f}\n{wline}")
    else:  # email (held out)
        text = (f"Subject: your invoice\nFrom: billing@{vendor.split()[0].lower()}.example\n\nHi, attaching {num} "
                f"dated {_long(d)} for {label.lower()}. Goods came to {subtotal:.2f} before tax; tax was {tax:.2f}; "
                f"grand total {stated:.2f}. {wline}\nThanks, {vendor} billing")
    fields = {"invoice_number": num, "vendor": vendor, "invoice_date": d.isoformat(), "category": cat,
              "other_detail": detail, "subtotal": subtotal, "tax": tax, "stated_total": stated,
              "calculated_total": round(subtotal + tax, 2),
              "warranty_date": warranty.isoformat() if warranty else None}
    return text, fields, {"inconsistent": bad_total}


def abstract(rng, fmt, i):
    design = rng.choice(list(DESIGN_LABEL) + ["other"])
    detail = "qualitative interview study" if design == "other" else None
    dlabel = detail or DESIGN_LABEL[design]
    authors = rng.sample(SURNAMES, rng.randint(1, 3))
    year = rng.randint(2015, 2026)
    topic = rng.choice(TOPICS)
    n = None if design == "meta_analysis" or rng.random() < 0.2 else rng.randint(24, 4000)
    refs = [f"{a} {rng.randint(2005, 2023)}" for a in rng.sample(SURNAMES, rng.randint(3, 6))]
    ntext = f"We enrolled {n} participants. " if n else "Participant numbers were not reported. "
    head = f"{'; '.join(authors)} ({year}). Effects of {topic}: a {dlabel}.\n"
    if fmt == "inline":
        cites = "; ".join(f"({r.replace(' ', ', ')})" for r in refs)
        body = f"{ntext}Prior work {cites} motivates this question. Effects were modest."
    elif fmt == "bibliography":
        body = (f"{ntext}Prior work [1-{len(refs)}] motivates this question. Effects were modest.\n\nReferences\n"
                + "\n".join(f"{k}. {r.split()[0]} et al. {r.split()[1]}." for k, r in enumerate(refs, 1)))
    else:  # sources (held out)
        body = f"{ntext}Effects were modest.\nSources: " + "; ".join(refs)
    fields = {"title": f"Effects of {topic}: a {dlabel}", "authors": authors, "year": year,
              "study_design": design, "other_detail": detail, "sample_size": n, "reference_count": len(refs)}
    return head + body, fields, {}


def contract(rng, fmt, i):
    parties = rng.sample(VENDORS, 2)
    eff = _date(rng)
    term = rng.choice(list(WORDS))
    pay = rng.choice(list(PAY_WORDS))
    notice = rng.choice([None, 30, 60, 90])
    law = rng.choice([None] + STATES)
    renew = rng.choice([None, True, False])
    final_term, final_pay, amend = term, pay, ""
    if rng.random() < 0.6:  # the amendment, not the original clause, is correct
        final_term = rng.choice([t for t in WORDS if t != term])
        amend = f"Amendment No. 1: Section 2 is replaced so that the term is {WORDS[final_term]}. "
        if rng.random() < 0.5:
            final_pay = rng.choice([p for p in PAY_WORDS if p != pay])
            amend += f"Section 4 is replaced so that invoices are due within {PAY_WORDS[final_pay]} days. "
    renew_t = {True: "The term renews automatically for successive twelve (12) month periods unless cancelled. ",
               False: "This Agreement does not renew automatically. ", None: ""}[renew]
    notice_t = f"Either party may terminate on {notice} days written notice. " if notice else ""
    law_t = f"This Agreement is governed by the laws of the State of {law}. " if law else ""
    clauses = [f"1. This Agreement between {parties[0]} and {parties[1]} is effective as of "
               f"{eff.day} {eff.strftime('%B, %Y')}.",
               f"2. The initial term is {WORDS[term]}. {renew_t}".strip(),
               f"3. {notice_t}{law_t}".strip(),
               f"4. Invoices are due within {PAY_WORDS[pay]} days of receipt.", amend.strip()]
    if fmt == "clauses":
        text = "SERVICES AGREEMENT\n" + "\n".join(c for c in clauses if len(c) > 3)
    else:
        text = ("Dear counsel, to confirm what we agreed: " + " ".join(c.split(". ", 1)[-1] if c[:2].rstrip(".").isdigit() else c
                                                          for c in clauses if len(c) > 3)
                + " Please countersign.")
    fields = {"parties": parties, "effective_date": eff.isoformat(), "term_months": final_term,
              "payment_due_days": final_pay, "notice_days": notice, "governing_law": law, "auto_renew": renew}
    return text, fields, {}


def build():
    rng = random.Random(7)
    plan = ([("invoice", f, invoice) for f in ["narrative"] * 14 + ["table"] * 14 + ["email"] * 12]
            + [("abstract", f, abstract) for f in ["inline"] * 12 + ["bibliography"] * 12 + ["sources"] * 6]
            + [("contract", f, contract) for f in ["clauses"] * 15 + ["letter"] * 15])
    out, counters = {}, {}
    for doc_type, fmt, fn in plan:
        counters[doc_type] = counters.get(doc_type, 0) + 1
        k = counters[doc_type]
        kw = {"bad_total": k % 8 == 0} if doc_type == "invoice" else {}
        text, fields, meta = fn(rng, fmt, k, **kw)
        doc_id = f"{doc_type[:3]}-{k:03d}"
        held = (doc_type, fmt) in {("invoice", "email"), ("abstract", "sources")}
        out[doc_id] = {"doc_type": doc_type, "format": fmt, "held_out": held, "fields": fields, **meta, "text": text}
    return out


def main():
    DOCS.mkdir(exist_ok=True)
    for old in DOCS.glob("*"):
        old.unlink()
    corpus = build()
    for doc_id, d in corpus.items():
        (DOCS / f"{doc_id}.txt").write_text(d.pop("text") + "\n")
    (DOCS / "truth.json").write_text(json.dumps(corpus, indent=1) + "\n")
    print(f"wrote {len(corpus)} documents to {DOCS}")


if __name__ == "__main__":
    main()
