"""
Generates a synthetic dataset of supplier invoices for a fictional
mid-sized German manufacturing company (one year, 2025).

The data is made up, but the patterns are modelled on how manual
accounts payable usually works: paper invoices are slower, mismatches
with the purchase order cause long waits, and late payment means the
early-payment discount (Skonto) is lost.
"""

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
N = 12_000

suppliers = pd.DataFrame({
    "supplier_id": [f"S{i:03d}" for i in range(1, 81)],
    "category": rng.choice(
        ["Raw materials", "Components", "Logistics", "MRO", "IT & Services"],
        size=80, p=[0.30, 0.30, 0.15, 0.15, 0.10]),
    "skonto_rate": rng.choice([0.0, 0.02, 0.03], size=80, p=[0.35, 0.50, 0.15]),
})

# a few large suppliers send most invoices
weights = rng.pareto(1.2, 80) + 1
weights = weights / weights.sum()
sup = suppliers.sample(N, replace=True, weights=weights, random_state=1).reset_index(drop=True)

invoice_date = pd.to_datetime("2025-01-01") + pd.to_timedelta(rng.integers(0, 365, N), unit="D")
channel = rng.choice(["Email (PDF)", "Paper", "EDI"], size=N, p=[0.55, 0.30, 0.15])

amount = np.round(rng.lognormal(mean=7.3, sigma=1.1, size=N), 2)  # median ~1,500 EUR
has_po = rng.random(N) > 0.07

# match outcome against purchase order and goods receipt
match_status = np.where(~has_po, "Missing PO",
                rng.choice(["Matched", "Price mismatch", "Quantity mismatch"],
                           size=N, p=[0.74, 0.15, 0.11]))
match_status = np.where(channel == "EDI",
                        np.where(rng.random(N) < 0.9, "Matched", match_status),
                        match_status)

# --- process timings (days) ---
receipt_delay = np.select(
    [channel == "Paper", channel == "Email (PDF)", channel == "EDI"],
    [rng.integers(2, 7, N), rng.integers(0, 2, N), np.zeros(N, dtype=int)])

entry_delay = np.where(channel == "EDI", 0, rng.integers(1, 5, N))   # backlog before manual entry

exception_wait = np.select(
    [match_status == "Matched", match_status == "Price mismatch",
     match_status == "Quantity mismatch", match_status == "Missing PO"],
    [np.zeros(N, dtype=int), rng.integers(3, 12, N),
     rng.integers(2, 9, N), rng.integers(5, 18, N)])

approval_required = amount > 5000
approval_wait = np.where(approval_required, rng.integers(1, 7, N), 0)

payment_run_wait = rng.integers(0, 7, N)  # weekly payment run

received_date = invoice_date + pd.to_timedelta(receipt_delay, unit="D")
entered_date = received_date + pd.to_timedelta(entry_delay, unit="D")
matched_date = entered_date + pd.to_timedelta(exception_wait, unit="D")
approved_date = matched_date + pd.to_timedelta(approval_wait, unit="D")
payment_date = approved_date + pd.to_timedelta(payment_run_wait, unit="D")

# manual touches: entry, each exception round, approval
touches = (np.where(channel == "EDI", 0, 1)
           + np.where(match_status != "Matched", rng.integers(2, 5, N), 1)
           + approval_required.astype(int))

df = pd.DataFrame({
    "invoice_id": [f"INV{100000 + i}" for i in range(N)],
    "supplier_id": sup["supplier_id"],
    "category": sup["category"],
    "channel": channel,
    "amount_eur": amount,
    "has_po": has_po,
    "match_status": match_status,
    "approval_required": approval_required,
    "invoice_date": invoice_date.date,
    "received_date": received_date.date,
    "entered_date": entered_date.date,
    "matched_date": matched_date.date,
    "approved_date": approved_date.date,
    "payment_date": payment_date.date,
    "payment_terms_days": 30,
    "skonto_rate": sup["skonto_rate"],
    "skonto_days": 10,
    "manual_touches": touches,
})

df.to_csv("data/invoices.csv", index=False)
print(f"Wrote {len(df):,} invoices to data/invoices.csv")
