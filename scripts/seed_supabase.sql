-- ============================================================
-- DataPulse — Demo seed for Supabase (public schema only)
-- Paste and run in Supabase SQL Editor
-- ============================================================

-- ── orders ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.orders (
    id          SERIAL PRIMARY KEY,
    customer_id INT NOT NULL,
    amount      NUMERIC(10,2) NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.orders (customer_id, amount, status, created_at)
SELECT
    (random() * 9999 + 1)::INT,
    round((random() * 4900 + 100)::NUMERIC, 2),
    (ARRAY['pending','completed','cancelled','refunded'])[floor(random()*4+1)],
    NOW() - (random() * INTERVAL '30 minutes')
FROM generate_series(1, 250);

-- ── users ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.users (
    id         SERIAL PRIMARY KEY,
    email      TEXT NOT NULL UNIQUE,
    username   TEXT NOT NULL,
    plan       TEXT NOT NULL DEFAULT 'free',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.users (email, username, plan, created_at)
SELECT
    'user' || n || '@example.com',
    'user_' || n,
    (ARRAY['free','pro','enterprise'])[floor(random()*3+1)],
    NOW() - (n * INTERVAL '2 hours')
FROM generate_series(1, 580) AS n;

-- ── products ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.products (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    sku        TEXT NOT NULL UNIQUE,
    price      NUMERIC(10,2) NOT NULL,
    stock      INT NOT NULL DEFAULT 0,
    synced_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.products (name, sku, price, stock, synced_at)
SELECT
    'Product ' || n,
    'SKU-' || LPAD(n::TEXT, 5, '0'),
    round((random() * 999 + 1)::NUMERIC, 2),
    (random() * 1000)::INT,
    NOW() - (random() * INTERVAL '6 hours')
FROM generate_series(1, 80) AS n;

-- ── sessions ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.sessions (
    id         SERIAL PRIMARY KEY,
    user_id    INT NOT NULL,
    ip_address TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    duration_s INT NOT NULL DEFAULT 0
);

INSERT INTO public.sessions (user_id, ip_address, started_at, duration_s)
SELECT
    (random() * 580 + 1)::INT,
    '10.' || (random()*255)::INT || '.' || (random()*255)::INT || '.' || (random()*255)::INT,
    NOW() - (random() * INTERVAL '24 hours'),
    (random() * 3600)::INT
FROM generate_series(1, 1200) AS n;

-- ── events ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.events (
    id         SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    user_id    INT,
    payload    JSONB,
    logged_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.events (event_type, user_id, logged_at)
SELECT
    (ARRAY['page_view','click','purchase','signup','logout'])[floor(random()*5+1)],
    (random() * 580 + 1)::INT,
    NOW() - (random() * INTERVAL '90 minutes')
FROM generate_series(1, 500) AS n;

-- ── payments ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.payments (
    id         SERIAL PRIMARY KEY,
    order_id   INT NOT NULL,
    amount     NUMERIC(10,2) NOT NULL,
    method     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    paid_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.payments (order_id, amount, method, status, paid_at)
SELECT
    (random() * 250 + 1)::INT,
    round((random() * 4900 + 100)::NUMERIC, 2),
    (ARRAY['card','transfer','paypal','blik'])[floor(random()*4+1)],
    (ARRAY['completed','pending','failed'])[floor(random()*3+1)],
    NOW() - (random() * INTERVAL '3 hours')
FROM generate_series(1, 30) AS n;

-- ── alerts ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.alerts (
    id           SERIAL PRIMARY KEY,
    severity     TEXT NOT NULL DEFAULT 'info',
    message      TEXT NOT NULL,
    source       TEXT NOT NULL,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.alerts (severity, message, source, triggered_at)
SELECT
    (ARRAY['info','warning','critical'])[floor(random()*3+1)],
    'Alert message #' || n,
    (ARRAY['monitor','api','scheduler','db'])[floor(random()*4+1)],
    NOW() - (random() * INTERVAL '45 minutes')
FROM generate_series(1, 25) AS n;

-- ── inventory ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.inventory (
    id          SERIAL PRIMARY KEY,
    product_id  INT NOT NULL,
    warehouse   TEXT NOT NULL,
    quantity    INT NOT NULL DEFAULT 0,
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.inventory (product_id, warehouse, quantity, snapshot_at)
SELECT
    (random() * 80 + 1)::INT,
    (ARRAY['WAW-01','KRK-01','WRO-01','GDN-01'])[floor(random()*4+1)],
    (random() * 500)::INT,
    NOW() - (random() * INTERVAL '20 hours')
FROM generate_series(1, 320) AS n;

-- ── dim_customers ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.dim_customers (
    id           SERIAL PRIMARY KEY,
    external_id  TEXT NOT NULL UNIQUE,
    segment      TEXT NOT NULL DEFAULT 'standard',
    country      TEXT NOT NULL DEFAULT 'PL',
    ltv          NUMERIC(12,2) NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.dim_customers (external_id, segment, country, ltv)
SELECT
    'CUS-' || LPAD(n::TEXT, 7, '0'),
    (ARRAY['standard','premium','enterprise','churned'])[floor(random()*4+1)],
    (ARRAY['PL','DE','GB','FR','CZ','NL'])[floor(random()*6+1)],
    round((random() * 50000)::NUMERIC, 2)
FROM generate_series(1, 5200) AS n;

-- ── fact_sales ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.fact_sales (
    id          SERIAL PRIMARY KEY,
    customer_id INT NOT NULL,
    product_id  INT NOT NULL,
    quantity    INT NOT NULL DEFAULT 1,
    revenue     NUMERIC(12,2) NOT NULL,
    sale_date   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.fact_sales (customer_id, product_id, quantity, revenue, sale_date)
SELECT
    (random() * 5200 + 1)::INT,
    (random() * 80 + 1)::INT,
    (random() * 10 + 1)::INT,
    round((random() * 9900 + 100)::NUMERIC, 2),
    NOW() - (random() * INTERVAL '20 hours')
FROM generate_series(1, 400) AS n;

-- ── api_requests ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.api_requests (
    id          SERIAL PRIMARY KEY,
    method      TEXT NOT NULL,
    endpoint    TEXT NOT NULL,
    status_code INT NOT NULL,
    duration_ms INT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.api_requests (method, endpoint, status_code, duration_ms, ts)
SELECT
    (ARRAY['GET','POST','PUT','DELETE'])[floor(random()*4+1)],
    (ARRAY['/api/orders','/api/users','/api/products','/api/events','/health'])[floor(random()*5+1)],
    (ARRAY[200,200,200,201,400,404,500])[floor(random()*7+1)],
    (random() * 2000)::INT,
    NOW() - (random() * INTERVAL '30 minutes')
FROM generate_series(1, 800) AS n;

-- ── report_snapshots ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.report_snapshots (
    id           SERIAL PRIMARY KEY,
    report_name  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'success',
    rows_written INT NOT NULL DEFAULT 0,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.report_snapshots (report_name, status, rows_written, generated_at)
SELECT
    (ARRAY['daily_sales','user_cohort','inventory_summary','payment_reconciliation','churn_report'])[floor(random()*5+1)],
    (ARRAY['success','success','success','failed'])[floor(random()*4+1)],
    (random() * 10000)::INT,
    NOW() - (random() * INTERVAL '8 hours')
FROM generate_series(1, 40) AS n;

-- ============================================================
-- Done! All 12 tables created and seeded.
-- ============================================================
