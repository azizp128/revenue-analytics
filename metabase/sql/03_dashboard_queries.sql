-- ============================================================================
-- DataForge — one query per dashboard card
-- ============================================================================


-- ---------------------------------------------------------------------------
-- CARD 1-2 :: Total Monthly Revenue + Average Daily Revenue
--             (single "Number" card each, with a trend comparison)
-- ---------------------------------------------------------------------------
WITH bounds AS (
    SELECT date_trunc('month', MAX(usage_date))::date AS m_start,
           MAX(usage_date)                            AS m_end
    FROM v_revenue
),
monthly AS (
    SELECT date_trunc('month', usage_date)::date AS month,
           SUM(revenue_usd)                      AS revenue,
           COUNT(DISTINCT usage_date)            AS active_days
    FROM v_revenue
    GROUP BY 1
)
SELECT
    m.month,
    ROUND(m.revenue, 2)                              AS total_monthly_revenue,
    ROUND(m.revenue / m.active_days, 2)              AS average_daily_revenue,
    ROUND(LAG(m.revenue) OVER (ORDER BY m.month), 2) AS prev_month_revenue,
    ROUND(100.0 * (m.revenue - LAG(m.revenue) OVER (ORDER BY m.month))
          / NULLIF(LAG(m.revenue) OVER (ORDER BY m.month), 0), 2) AS mom_pct
FROM monthly m
ORDER BY m.month DESC;


-- ---------------------------------------------------------------------------
-- CARD 3-4 :: Total Monthly Request + Average Daily Request
-- ---------------------------------------------------------------------------
SELECT
    date_trunc('month', usage_date)::date                       AS month,
    SUM(total_request)                                          AS total_monthly_request,
    ROUND(SUM(total_request)::NUMERIC
          / COUNT(DISTINCT usage_date), 0)                      AS average_daily_request
FROM v_revenue
GROUP BY 1
ORDER BY 1 DESC;


-- ---------------------------------------------------------------------------
-- CARD 5 :: Daily Revenue Trend  (area chart — x: day, y: revenue)
-- ---------------------------------------------------------------------------
SELECT
    usage_date                  AS "Date",
    ROUND(SUM(revenue_usd), 2)  AS "Revenue ($)"
FROM v_revenue
GROUP BY 1
ORDER BY 1;


-- Optional: day-over-day delta, useful as a second series or a tooltip column
SELECT
    usage_date,
    ROUND(SUM(revenue_usd), 2) AS revenue,
    ROUND(SUM(revenue_usd) - LAG(SUM(revenue_usd)) OVER (ORDER BY usage_date), 2) AS dod_change,
    ROUND(AVG(SUM(revenue_usd)) OVER (ORDER BY usage_date
          ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS revenue_7d_moving_avg
FROM v_revenue
GROUP BY usage_date
ORDER BY usage_date;


-- ---------------------------------------------------------------------------
-- CARD 6 :: Daily Revenue Table  (the raw drill-down grid)
-- ---------------------------------------------------------------------------
SELECT
    usage_date        AS "Date",
    service_type      AS "Service Type",
    client_name       AS "Client",
    domain            AS "Domain",
    action            AS "Action",
    product_name      AS "Product Name",
    invoice_category  AS "Invoice Category",
    timezone          AS "Timezone",
    bandwidth_mb      AS "Bandwidth Usage (MB)",
    success_request   AS "Success Request",
    usd_rate          AS "USD Rate ($)",
    revenue_usd       AS "Revenue ($)"
FROM v_revenue
ORDER BY usage_date DESC, revenue_usd DESC;

-- by Client
SELECT client_name AS dimension, ROUND(SUM(revenue_usd), 2) AS revenue
FROM v_revenue GROUP BY 1 ORDER BY 2 DESC;

-- by Client Group  (the two-slice Strategic vs Standard donut)
SELECT client_group AS dimension, ROUND(SUM(revenue_usd), 2) AS revenue
FROM v_revenue GROUP BY 1 ORDER BY 2 DESC;

-- by Service Type
SELECT service_type AS dimension, ROUND(SUM(revenue_usd), 2) AS revenue
FROM v_revenue GROUP BY 1 ORDER BY 2 DESC;

-- by Domain
SELECT domain AS dimension, ROUND(SUM(revenue_usd), 2) AS revenue
FROM v_revenue GROUP BY 1 ORDER BY 2 DESC;

-- by Action
SELECT action AS dimension, ROUND(SUM(revenue_usd), 2) AS revenue
FROM v_revenue GROUP BY 1 ORDER BY 2 DESC;

-- by Product Name
SELECT product_name AS dimension, ROUND(SUM(revenue_usd), 2) AS revenue
FROM v_revenue GROUP BY 1 ORDER BY 2 DESC;

-- by Invoice Category
SELECT invoice_category AS dimension, ROUND(SUM(revenue_usd), 2) AS revenue
FROM v_revenue GROUP BY 1 ORDER BY 2 DESC;

-- Revenue concentration: how exposed is the business to its biggest accounts?
WITH by_client AS (
    SELECT client_name, SUM(revenue_usd) AS revenue
    FROM v_revenue GROUP BY 1
)
SELECT
    client_name,
    ROUND(revenue, 2) AS revenue,
    ROUND(100.0 * revenue / SUM(revenue) OVER (), 2) AS pct_of_total,
    ROUND(100.0 * SUM(revenue) OVER (ORDER BY revenue DESC)
          / SUM(revenue) OVER (), 2) AS cumulative_pct
FROM by_client
ORDER BY revenue DESC;


-- Delivery quality: success rate by service line, weighted by volume
SELECT
    service_type,
    SUM(total_request)                                   AS total_requests,
    SUM(success_request)                                 AS success_requests,
    ROUND(100.0 * SUM(success_request) / SUM(total_request), 2) AS success_rate_pct,
    ROUND(SUM(revenue_usd), 2)                           AS revenue
FROM v_revenue
GROUP BY 1
ORDER BY revenue DESC;


-- Effective yield: what each service line actually earns per million requests
SELECT
    service_type,
    billing_unit,
    ROUND(SUM(revenue_usd), 2)                                        AS revenue,
    ROUND(SUM(revenue_usd) / NULLIF(SUM(total_request), 0) * 1e6, 2)  AS revenue_per_million_requests,
    ROUND(SUM(bandwidth_mb) / 1024.0, 2)                              AS bandwidth_gb
FROM v_revenue
GROUP BY 1, 2
ORDER BY revenue DESC;


-- Week-over-week momentum per client — spot churn risk early
SELECT
    client_name,
    date_trunc('week', usage_date)::date AS week,
    ROUND(SUM(revenue_usd), 2)           AS revenue,
    ROUND(100.0 * (SUM(revenue_usd) - LAG(SUM(revenue_usd))
          OVER (PARTITION BY client_name ORDER BY date_trunc('week', usage_date)))
          / NULLIF(LAG(SUM(revenue_usd))
          OVER (PARTITION BY client_name ORDER BY date_trunc('week', usage_date)), 0), 1) AS wow_pct
FROM v_revenue
GROUP BY 1, 2
ORDER BY client_name, week;