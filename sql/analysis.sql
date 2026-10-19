-- Invoice process analysis in SQL (SQLite)
-- Load the data first:  python sql/load_to_sqlite.py
-- Then run:             sqlite3 invoices.db < sql/analysis.sql

.headers on
.mode column

-- 1. Overall KPIs
SELECT
    COUNT(*)                                                         AS invoices,
    ROUND(AVG(julianday(payment_date) - julianday(invoice_date)), 1) AS avg_cycle_days,
    ROUND(100.0 * SUM(match_status = 'Matched') / COUNT(*), 1)       AS first_pass_match_pct,
    SUM(manual_touches)                                              AS manual_touches
FROM invoices;

-- 2. Skonto: how much discount was possible and how much did we lose?
SELECT
    ROUND(SUM(amount_eur * skonto_rate), 0) AS skonto_possible_eur,
    ROUND(SUM(CASE WHEN julianday(payment_date) - julianday(invoice_date) > skonto_days
                   THEN amount_eur * skonto_rate ELSE 0 END), 0) AS skonto_lost_eur
FROM invoices
WHERE skonto_rate > 0;

-- 3. Which stage holds invoices the longest?
SELECT
    ROUND(AVG(julianday(received_date) - julianday(invoice_date)), 1)  AS receipt,
    ROUND(AVG(julianday(entered_date)  - julianday(received_date)), 1) AS waiting_for_entry,
    ROUND(AVG(julianday(matched_date)  - julianday(entered_date)), 1)  AS exception_handling,
    ROUND(AVG(julianday(approved_date) - julianday(matched_date)), 1)  AS approval,
    ROUND(AVG(julianday(payment_date)  - julianday(approved_date)), 1) AS payment_run
FROM invoices;

-- 4. Cycle time and lost Skonto by channel
SELECT
    channel,
    COUNT(*) AS invoices,
    ROUND(AVG(julianday(payment_date) - julianday(invoice_date)), 1) AS avg_cycle_days,
    ROUND(SUM(CASE WHEN skonto_rate > 0
                    AND julianday(payment_date) - julianday(invoice_date) > skonto_days
                   THEN amount_eur * skonto_rate ELSE 0 END), 0) AS skonto_lost_eur
FROM invoices
GROUP BY channel
ORDER BY avg_cycle_days DESC;

-- 5. Exceptions by type
SELECT
    match_status,
    COUNT(*) AS invoices,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM invoices), 1) AS share_pct,
    ROUND(AVG(julianday(matched_date) - julianday(entered_date)), 1) AS avg_days_to_resolve
FROM invoices
GROUP BY match_status
ORDER BY invoices DESC;

-- 6. Top 10 suppliers by lost Skonto (who to talk to first / move to EDI)
SELECT
    supplier_id,
    category,
    COUNT(*) AS invoices,
    ROUND(SUM(CASE WHEN skonto_rate > 0
                    AND julianday(payment_date) - julianday(invoice_date) > skonto_days
                   THEN amount_eur * skonto_rate ELSE 0 END), 0) AS skonto_lost_eur,
    ROUND(100.0 * SUM(match_status <> 'Matched') / COUNT(*), 1) AS exception_rate_pct
FROM invoices
GROUP BY supplier_id, category
ORDER BY skonto_lost_eur DESC
LIMIT 10;
