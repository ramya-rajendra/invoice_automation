"""Loads data/invoices.csv into a local SQLite database (invoices.db)."""
import sqlite3
import pandas as pd

df = pd.read_csv("data/invoices.csv")
with sqlite3.connect("invoices.db") as con:
    df.to_sql("invoices", con, if_exists="replace", index=False)
print(f"Loaded {len(df):,} rows into invoices.db")
