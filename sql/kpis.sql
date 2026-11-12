-- Monthly KPI extract (SQLite). One row per month. All rates are fractions (0-1).

WITH app AS (
  SELECT substr(received_date, 1, 7) AS month,
         COUNT(*)                                                         AS applications,
         AVG(decision = 'Approved') * 1.0                                 AS approval_rate,
         AVG(tat_hours)                                                   AS avg_tat_hours,
         AVG(tat_hours <= 48) * 1.0                                       AS within_sla_rate
  FROM applications GROUP BY 1
), acc AS (
  SELECT month,
         SUM(active)                                                      AS active_accounts,
         SUM(spend)                                                       AS total_spend,
         SUM(spend) / NULLIF(SUM(active), 0)                              AS spend_per_active,
         SUM(txn_count)                                                   AS transactions,
         SUM(balance) / SUM(credit_limit)                                 AS utilisation,
         AVG(dpd30) * 1.0                                                 AS dpd30_rate
  FROM account_month GROUP BY 1
), dsp AS (
  SELECT substr(opened_date, 1, 7) AS month,
         COUNT(*)                                                         AS disputes,
         SUM(amount)                                                      AS dispute_amount,
         AVG(julianday(resolved_date) - julianday(opened_date) <= 30) * 1.0 AS disputes_resolved_30d_rate,
         AVG(reason = 'Duplicate charge') * 1.0                           AS duplicate_charge_share
  FROM disputes GROUP BY 1
), cmp AS (
  SELECT substr(received_date, 1, 7) AS month,
         COUNT(*)                                                         AS complaints,
         AVG(julianday(resolved_date) - julianday(received_date))         AS avg_complaint_days
  FROM complaints GROUP BY 1
)
SELECT acc.month,
       app.applications, app.approval_rate, app.avg_tat_hours, app.within_sla_rate,
       acc.active_accounts, acc.total_spend, acc.spend_per_active, acc.transactions, acc.utilisation, acc.dpd30_rate,
       dsp.disputes, dsp.dispute_amount, dsp.disputes * 10000.0 / acc.transactions AS disputes_per_10k_txns,
       dsp.disputes_resolved_30d_rate, dsp.duplicate_charge_share,
       cmp.complaints, cmp.complaints * 1000.0 / acc.active_accounts AS complaints_per_1k_active, cmp.avg_complaint_days
FROM acc
LEFT JOIN app USING (month)
LEFT JOIN dsp USING (month)
LEFT JOIN cmp USING (month)
ORDER BY acc.month;
