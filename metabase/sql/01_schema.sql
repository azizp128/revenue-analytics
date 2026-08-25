-- ============================================================================
-- DataForge — Postgres schema (star schema)
-- Run:  docker exec -i postgres_dataforge psql -U dataforge -d dataforge < sql/01_schema.sq
-- ============================================================================

DROP VIEW  IF EXISTS v_revenue          CASCADE;
DROP TABLE IF EXISTS fact_daily_usage   CASCADE;
DROP TABLE IF EXISTS dim_product        CASCADE;
DROP TABLE IF EXISTS dim_domain         CASCADE;
DROP TABLE IF EXISTS dim_client         CASCADE;

-- ---------------------------------------------------------------- dimensions
CREATE TABLE dim_client (
    client_id      INT PRIMARY KEY,
    client_name    TEXT NOT NULL,
    client_group   TEXT NOT NULL,          -- Strategic | Standard
    client_tier    TEXT NOT NULL,          -- Enterprise | Growth | Startup
    home_timezone  TEXT NOT NULL
);

CREATE TABLE dim_domain (
    domain    TEXT PRIMARY KEY,
    platform  TEXT NOT NULL,
    country   TEXT NOT NULL
);

CREATE TABLE dim_product (
    product_id        INT PRIMARY KEY,
    product_name      TEXT NOT NULL,
    service_type      TEXT NOT NULL,       -- Scraper | Proxy | Payments | Account
    invoice_category  TEXT NOT NULL,
    action            TEXT NOT NULL,
    billing_unit      TEXT NOT NULL,       -- request | MB
    list_usd_rate     NUMERIC(12,8) NOT NULL
);

-- --------------------------------------------------------------------- fact
-- Grain: one row per (day x client x domain x action x product)
CREATE TABLE fact_daily_usage (
    id                BIGSERIAL PRIMARY KEY,
    usage_date        DATE   NOT NULL,
    client_id         INT    NOT NULL REFERENCES dim_client(client_id),
    service_type      TEXT   NOT NULL,
    domain            TEXT   NOT NULL REFERENCES dim_domain(domain),
    action            TEXT   NOT NULL,
    product_id        INT    NOT NULL REFERENCES dim_product(product_id),
    invoice_category  TEXT   NOT NULL,
    timezone          TEXT   NOT NULL,
    bandwidth_mb      NUMERIC(16,2) NOT NULL DEFAULT 0,
    total_request     BIGINT NOT NULL,
    success_request   BIGINT NOT NULL,
    usd_rate          NUMERIC(12,8) NOT NULL,
    revenue_usd       NUMERIC(14,6) NOT NULL,

    CONSTRAINT chk_success  CHECK (success_request <= total_request),
    CONSTRAINT chk_positive CHECK (revenue_usd >= 0 AND bandwidth_mb >= 0)
);

CREATE INDEX idx_fact_date     ON fact_daily_usage (usage_date);
CREATE INDEX idx_fact_client   ON fact_daily_usage (client_id, usage_date);
CREATE INDEX idx_fact_service  ON fact_daily_usage (service_type, usage_date);
CREATE INDEX idx_fact_product  ON fact_daily_usage (product_id);
CREATE INDEX idx_fact_invoice  ON fact_daily_usage (invoice_category);

COMMENT ON TABLE fact_daily_usage IS
  'Synthetic daily usage & billing facts. Revenue engine: Proxy bills on '
  'bandwidth_mb * usd_rate; every other service bills on success_request * usd_rate.';

-- ------------------------------------------------ denormalised analytics view
-- Point every Metabase question at this view: filters and breakouts all work
-- off one flat surface, which keeps the dashboard cards simple.
CREATE VIEW v_revenue AS
SELECT
    f.usage_date,
    c.client_name,
    c.client_group,
    c.client_tier,
    f.service_type,
    f.domain,
    d.platform,
    d.country,
    f.action,
    p.product_name,
    f.invoice_category,
    f.timezone,
    p.billing_unit,
    f.bandwidth_mb,
    f.total_request,
    f.success_request,
    ROUND(f.success_request::NUMERIC / NULLIF(f.total_request, 0), 4) AS success_rate,
    f.usd_rate,
    f.revenue_usd
FROM fact_daily_usage f
JOIN dim_client  c ON c.client_id  = f.client_id
JOIN dim_product p ON p.product_id = f.product_id
JOIN dim_domain  d ON d.domain     = f.domain;