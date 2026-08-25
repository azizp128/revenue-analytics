-- ============================================================================
-- DataForge — load the generated CSVs
-- Run from the project root so the relative paths resolve:
--   docker exec -i postgres_dataforge psql -U dataforge -d dataforge < sql/02_load.sq
--
-- \copy runs client-side, so this works against a remote/Dockerised Postgres
-- without needing superuser or the files to live on the server.
-- ============================================================================

TRUNCATE fact_daily_usage, dim_product, dim_domain, dim_client RESTART IDENTITY CASCADE;

\copy dim_client  (client_id, client_name, client_group, client_tier, home_timezone) FROM '/tmp/dim_client.csv'  WITH (FORMAT csv, HEADER true)
\copy dim_domain  (domain, platform, country)                                        FROM '/tmp/dim_domain.csv'  WITH (FORMAT csv, HEADER true)
\copy dim_product (product_id, product_name, service_type, invoice_category, action, billing_unit, list_usd_rate) FROM '/tmp/dim_product.csv' WITH (FORMAT csv, HEADER true)

\copy fact_daily_usage (usage_date, client_id, service_type, domain, action, product_id, invoice_category, timezone, bandwidth_mb, total_request, success_request, usd_rate, revenue_usd) FROM '/tmp/fact_daily_usage.csv' WITH (FORMAT csv, HEADER true)

ANALYZE dim_client;
ANALYZE dim_domain;
ANALYZE dim_product;
ANALYZE fact_daily_usage;

-- quick smoke test
SELECT
    COUNT(*)                        AS fact_rows,
    MIN(usage_date)                 AS period_start,
    MAX(usage_date)                 AS period_end,
    ROUND(SUM(revenue_usd), 2)      AS total_revenue,
    SUM(total_request)              AS total_requests
FROM fact_daily_usage;