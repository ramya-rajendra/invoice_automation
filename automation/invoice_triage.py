"""
Prototype of the to-be process: read incoming invoices, check them against
the purchase order and goods receipt, and decide what happens next.

  - matched and small        -> post automatically
  - matched but large        -> send to manager for approval
  - price within tolerance   -> accept, note the difference
  - real mismatch / no PO    -> route to the right person with the reason
  - everything sorted by Skonto deadline, so discounts are not missed

Extraction works in two ways:
  1. Rule-based (regex) - runs offline, no setup needed
  2. LLM-based (Claude API) - used if ANTHROPIC_API_KEY is set; handles
     messy layouts the rules can't. Its output is still checked by the
     same matching rules, so the AI never approves anything on its own.

Run from the project root:  python automation/invoice_triage.py
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

PRICE_TOLERANCE = 0.01      # accept up to 1% price difference
APPROVAL_LIMIT = 5000       # EUR, above this a manager must approve
BASE = Path(__file__).parent


def parse_eur(text):
    # German number format: 8.240,00 -> 8240.00
    return float(text.replace(".", "").replace(",", "."))


def extract_rule_based(text):
    def find(pattern):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    skonto = find(r"(\d+)\s*%\s*Skonto")
    return {
        "supplier": text.strip().splitlines()[0],
        "invoice_no": find(r"(?:Rechnung Nr\.|Invoice No\.)\s*(\S+)"),
        "invoice_date": find(r"(?:Rechnungsdatum|Invoice date):\s*([\d.]+)"),
        "po_number": find(r"(?:Bestellnummer|PO number):\s*(\S+)"),
        "quantity": int(find(r"(?:Menge|Quantity):\s*(\d+)") or 0),
        "amount_eur": parse_eur(find(r"(?:Gesamtbetrag netto|Total net):\s*([\d.,]+)")),
        "skonto_rate": int(skonto) / 100 if skonto else 0.0,
    }


def extract_with_llm(text):
    import anthropic  # pip install anthropic

    client = anthropic.Anthropic()
    prompt = (
        "Extract these fields from the invoice and return only JSON: "
        "supplier, invoice_no, invoice_date (DD.MM.YYYY), po_number (null if missing), "
        "quantity (int), amount_eur (float, net), skonto_rate (e.g. 0.02, 0 if none).\n\n"
        + text
    )
    msg = client.messages.create(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip().strip("`").removeprefix("json").strip()
    return json.loads(raw)


def extract(text):
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return extract_with_llm(text), "LLM"
        except Exception as e:
            print(f"  LLM extraction failed ({e}), falling back to rules")
    return extract_rule_based(text), "rules"


def decide(inv, pos):
    if not inv["po_number"] or inv["po_number"] not in pos.index:
        return "Route to procurement", "No purchase order found", None

    po = pos.loc[inv["po_number"]]
    if inv["quantity"] > po["received_qty"]:
        return ("Route to buyer", f"Invoiced {inv['quantity']} but only "
                f"{po['received_qty']} received", po["buyer"])

    diff = (inv["amount_eur"] - po["agreed_amount_eur"]) / po["agreed_amount_eur"]
    if abs(diff) > PRICE_TOLERANCE:
        return "Route to buyer", f"Price differs by {diff:+.1%} from PO", po["buyer"]

    note = f"price diff {diff:+.1%} within tolerance" if diff else "full match"
    if inv["amount_eur"] > APPROVAL_LIMIT:
        return "Manager approval", note, None
    return "Post automatically", note, None


def main():
    pos = pd.read_csv(BASE / "purchase_orders.csv").set_index("po_number")
    rows = []

    for f in sorted((BASE / "sample_invoices").glob("*.txt")):
        inv, method = extract(f.read_text(encoding="utf-8"))
        action, reason, owner = decide(inv, pos)

        inv_date = datetime.strptime(inv["invoice_date"], "%d.%m.%Y")
        deadline = inv_date + timedelta(days=10) if inv["skonto_rate"] else None

        rows.append({
            "file": f.name,
            "supplier": inv["supplier"],
            "amount_eur": inv["amount_eur"],
            "action": action,
            "reason": reason,
            "owner": owner or "-",
            "skonto_eur": round(inv["amount_eur"] * inv["skonto_rate"], 2),
            "skonto_deadline": deadline.date() if deadline else "-",
            "extracted_by": method,
        })

    out = pd.DataFrame(rows)
    # invoices with a discount at stake and the earliest deadline go first
    out["_sort"] = pd.to_datetime(out["skonto_deadline"].replace("-", None))
    out = out.sort_values(["_sort", "skonto_eur"], ascending=[True, False],
                          na_position="last").drop(columns="_sort")

    pd.set_option("display.width", 200)
    print("\nInvoice work queue (sorted by Skonto deadline):\n")
    print(out.to_string(index=False))
    out.to_csv(BASE / "work_queue.csv", index=False)
    print("\nSaved to automation/work_queue.csv")


if __name__ == "__main__":
    main()
