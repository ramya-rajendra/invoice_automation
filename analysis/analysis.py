"""
Invoice process analysis: where do time and money get lost,
and what would an AI-supported process be worth?

Run from the project root:  python analysis/analysis.py
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ---------------- assumptions (change these to test the business case) ----------------
MINUTES_PER_TOUCH = 8          # average manual handling time per touch
COST_PER_HOUR = 45             # fully loaded cost of an AP clerk, EUR
AI_STRAIGHT_THROUGH = 0.85     # share of email/paper invoices AI extraction handles without a person
AUTO_RESOLVE_PRICE = 0.40      # share of price mismatches solved by tolerance rules + AI suggestion
EXCEPTION_WAIT_CUT = 0.50      # faster exception handling via automatic routing to the right buyer
# ---------------------------------------------------------------------------------------

df = pd.read_csv("data/invoices.csv", parse_dates=[
    "invoice_date", "received_date", "entered_date",
    "matched_date", "approved_date", "payment_date"])

df["cycle_days"] = (df["payment_date"] - df["invoice_date"]).dt.days
df["skonto_deadline"] = df["invoice_date"] + pd.to_timedelta(df["skonto_days"], unit="D")
df["skonto_possible_eur"] = df["amount_eur"] * df["skonto_rate"]
df["skonto_taken"] = (df["payment_date"] <= df["skonto_deadline"]) & (df["skonto_rate"] > 0)
df["skonto_lost_eur"] = np.where(df["skonto_taken"], 0, df["skonto_possible_eur"])
df["late_payment"] = df["cycle_days"] > df["payment_terms_days"]

stages = {
    "Receipt": ("invoice_date", "received_date"),
    "Waiting for entry": ("received_date", "entered_date"),
    "Exception handling": ("entered_date", "matched_date"),
    "Approval": ("matched_date", "approved_date"),
    "Payment run": ("approved_date", "payment_date"),
}
for name, (a, b) in stages.items():
    df[name] = (df[b] - df[a]).dt.days

# ---------------- AS-IS KPIs ----------------
n = len(df)
hours = df["manual_touches"].sum() * MINUTES_PER_TOUCH / 60
as_is = {
    "Invoices": n,
    "Avg cycle time (days)": df["cycle_days"].mean(),
    "First-pass match rate": (df["match_status"] == "Matched").mean(),
    "Paid within Skonto window": df.loc[df["skonto_rate"] > 0, "skonto_taken"].mean(),
    "Manual hours / year": hours,
    "Processing cost / invoice (EUR)": hours * COST_PER_HOUR / n,
    "Skonto available (EUR)": df["skonto_possible_eur"].sum(),
    "Skonto lost (EUR)": df["skonto_lost_eur"].sum(),
}

print("\n=== AS-IS ===")
for k, v in as_is.items():
    print(f"{k:35s} {v:,.2f}" if isinstance(v, float) else f"{k:35s} {v:,}")

print("\nAverage days per stage:")
print(df[list(stages)].mean().round(1).to_string())

print("\nBy channel:")
print(df.groupby("channel").agg(
    invoices=("invoice_id", "count"),
    avg_cycle=("cycle_days", "mean"),
    skonto_lost=("skonto_lost_eur", "sum")).round(1).to_string())

print("\nBy match status:")
print(df.groupby("match_status").agg(
    invoices=("invoice_id", "count"),
    avg_cycle=("cycle_days", "mean"),
    skonto_lost=("skonto_lost_eur", "sum")).round(2).to_string())

# ---------------- TO-BE simulation ----------------
rng = np.random.default_rng(7)
tb = df.copy()

manual_channel = tb["channel"] != "EDI"
ai_handles = manual_channel & (rng.random(n) < AI_STRAIGHT_THROUGH)

# AI extraction: no entry backlog, no manual entry touch
tb.loc[ai_handles, "Waiting for entry"] = 0
tb.loc[ai_handles, "manual_touches"] -= 1

# price mismatches within tolerance get resolved automatically
auto_price = (tb["match_status"] == "Price mismatch") & (rng.random(n) < AUTO_RESOLVE_PRICE)
tb.loc[auto_price, "Exception handling"] = 0
tb.loc[auto_price, "manual_touches"] = tb.loc[auto_price, "manual_touches"].clip(upper=1)

# remaining exceptions routed automatically to the right buyer
rest = (tb["match_status"] != "Matched") & ~auto_price
tb.loc[rest, "Exception handling"] = np.ceil(tb.loc[rest, "Exception handling"] * (1 - EXCEPTION_WAIT_CUT))

# Skonto-aware payment: invoices with a discount are paid in the next daily run, not the weekly one
tb.loc[tb["skonto_rate"] > 0, "Payment run"] = 1

tb["cycle_days"] = tb[list(stages)].sum(axis=1)
tb["skonto_taken"] = (tb["cycle_days"] <= tb["skonto_days"]) & (tb["skonto_rate"] > 0)
tb["skonto_lost_eur"] = np.where(tb["skonto_taken"], 0, tb["skonto_possible_eur"])
tb["late_payment"] = tb["cycle_days"] > tb["payment_terms_days"]
tb_hours = tb["manual_touches"].clip(lower=0).sum() * MINUTES_PER_TOUCH / 60

to_be = {
    "Avg cycle time (days)": tb["cycle_days"].mean(),
    "Paid within Skonto window": tb.loc[tb["skonto_rate"] > 0, "skonto_taken"].mean(),
    "Manual hours / year": tb_hours,
    "Processing cost / invoice (EUR)": tb_hours * COST_PER_HOUR / n,
    "Skonto lost (EUR)": tb["skonto_lost_eur"].sum(),
}

labour_saving = (hours - tb_hours) * COST_PER_HOUR
skonto_gain = as_is["Skonto lost (EUR)"] - to_be["Skonto lost (EUR)"]

print("\n=== TO-BE (simulated) ===")
for k, v in to_be.items():
    print(f"{k:35s} {v:,.2f}")
print(f"\nLabour saving / year:      EUR {labour_saving:,.0f}")
print(f"Extra Skonto captured:     EUR {skonto_gain:,.0f}")
print(f"Total EBIT effect / year:  EUR {labour_saving + skonto_gain:,.0f}")
print(f"FTE freed up (1,600 h/FTE): {(hours - tb_hours) / 1600:.1f}")

# ---------------- charts ----------------
plt.rcParams.update({"figure.dpi": 120, "axes.spines.top": False, "axes.spines.right": False})

ax = df[list(stages)].mean().plot(kind="barh", color="#4C72B0", figsize=(7, 3.5))
ax.invert_yaxis()
ax.set_xlabel("Average days")
ax.set_title("Where invoices wait (as-is)")
plt.tight_layout(); plt.savefig("images/stage_wait_times.png"); plt.close()

order = ["Matched", "Quantity mismatch", "Price mismatch", "Missing PO"]
ax = df.groupby("match_status")["cycle_days"].mean().reindex(order).plot(
    kind="bar", color=["#55A868", "#DD8452", "#DD8452", "#C44E52"], figsize=(7, 3.5))
ax.axhline(10, ls="--", color="grey"); ax.text(-0.4, 10.4, "Skonto deadline (10 days)", ha="left", color="grey")
ax.set_ylabel("Avg cycle time (days)"); ax.set_xlabel("")
ax.set_title("Mismatches push invoices past the discount deadline")
plt.xticks(rotation=0); plt.tight_layout(); plt.savefig("images/cycle_by_match.png"); plt.close()

monthly = df.groupby(df["invoice_date"].dt.to_period("M"))["skonto_lost_eur"].sum()
ax = monthly.plot(kind="bar", color="#C44E52", figsize=(7, 3.5))
ax.set_ylabel("EUR"); ax.set_xlabel("")
ax.set_title("Skonto lost per month (as-is)")
plt.xticks(rotation=45); plt.tight_layout(); plt.savefig("images/skonto_lost_monthly.png"); plt.close()

comp = pd.DataFrame({
    "As-is": [as_is["Avg cycle time (days)"], as_is["Processing cost / invoice (EUR)"]],
    "To-be": [to_be["Avg cycle time (days)"], to_be["Processing cost / invoice (EUR)"]],
}, index=["Avg cycle time (days)", "Cost per invoice (EUR)"])
ax = comp.plot(kind="bar", color=["#8C8C8C", "#4C72B0"], figsize=(7, 3.5))
ax.set_title("As-is vs AI-supported process"); ax.set_xlabel("")
plt.xticks(rotation=0); plt.tight_layout(); plt.savefig("images/as_is_vs_to_be.png"); plt.close()

print("\nCharts saved to images/")
