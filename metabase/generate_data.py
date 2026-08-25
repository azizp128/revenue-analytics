#!/usr/bin/env python3
"""
DataForge — Synthetic Revenue Dataset Generator
================================================
Generates a fully synthetic dataset for a fictional web-data-extraction &
proxy-infrastructure company ("DataForge").

No real, proprietary, or client data is used anywhere in this project.

Billing model (two revenue engines in one dataset):
    Scraper / Payments / Account  ->  revenue = success_request * usd_rate
    Proxy                         ->  revenue = bandwidth_mb    * usd_rate

Output (./data):
    dim_client.csv
    dim_domain.csv
    dim_product.csv
    fact_daily_usage.csv

Usage:
    python generate_data.py                 
    python generate_data.py --seed 7 --days 220 --start 2026-01-01
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_SEED = 42
DEFAULT_DAYS = 220
DEFAULT_START = date(2026, 1, 1)
DEFAULT_TOTAL_REVENUE = 252_000.00

# Share of total revenue per client (must sum to 1.0)
CLIENT_REVENUE_SHARE = {
    "rakuza":      0.312,   # anchor account — drives the "Strategic vs Standard" donut
    "vendora":     0.163,
    "zenkart":     0.129,
    "payhub":      0.095,
    "mercora":     0.095,
    "lumina":      0.052,
    "skyfare":     0.034,
    "nomadly":     0.030,
    "kiosko":      0.028,
    "bytecart":    0.022,
    "freshroute":  0.018,
    "globalwear":  0.015,
    "tokopanda":   0.005,
    "pixelbay":    0.002,
}

# Share of total revenue per service line (must sum to 1.0)
SERVICE_REVENUE_SHARE = {
    "Scraper":  0.742,
    "Proxy":    0.136,
    "Payments": 0.095,
    "Account":  0.027,
}

# Demand shaping
WEEKDAY_FACTOR = {0: 1.04, 1: 1.06, 2: 1.05, 3: 1.03, 4: 0.98, 5: 0.79, 6: 0.72}
GROWTH_PER_DAY = 0.004          # slow organic growth across the month
GLOBAL_NOISE_SIGMA = 0.055      # market-wide day-to-day wobble
SKU_NOISE_SIGMA = 0.115         # per-SKU wobble
SPIKE_DAY_INDEX = 18            # one campaign/flash-sale spike
SPIKE_FACTOR = 1.62
DIP_DAYS = {7: 0.66, 8: 0.79}   # a two-day incident / throttling dip

# Proxy response size (KB per request) -> converts requests <-> bandwidth
PROXY_KB_MEAN = 90.0
PROXY_KB_STD = 14.0

SUCCESS_RATIO_RANGE = (0.928, 0.988)

# ---------------------------------------------------------------------------
# 2. DIMENSIONS
# ---------------------------------------------------------------------------

CLIENTS = {
    # key          name                  group        tier          timezone
    "rakuza":     ("Rakuza Commerce",   "Strategic", "Enterprise", "Asia/Seoul"),
    "vendora":    ("Vendora Marketplace", "Standard", "Enterprise", "America/Sao_Paulo"),
    "zenkart":    ("Zenkart",           "Standard",  "Enterprise", "Asia/Jakarta"),
    "payhub":     ("Payhub",            "Standard",  "Growth",     "UTC"),
    "mercora":    ("Mercora",           "Standard",  "Growth",     "Europe/Moscow"),
    "lumina":     ("Lumina Retail",     "Standard",  "Growth",     "Asia/Singapore"),
    "skyfare":    ("Skyfare",           "Standard",  "Growth",     "Asia/Bangkok"),
    "nomadly":    ("Nomadly",           "Standard",  "Growth",     "Europe/Paris"),
    "kiosko":     ("Kiosko",            "Standard",  "Startup",    "America/Santiago"),
    "bytecart":   ("Bytecart",          "Standard",  "Startup",    "UTC"),
    "freshroute": ("FreshRoute",        "Standard",  "Startup",    "Asia/Jakarta"),
    "globalwear": ("GlobalWear",        "Standard",  "Startup",    "Europe/Berlin"),
    "tokopanda":  ("Tokopanda",         "Standard",  "Startup",    "Asia/Jakarta"),
    "pixelbay":   ("Pixelbay",          "Standard",  "Startup",    "UTC"),
}

DOMAIN_META = {
    # domain                     platform            country
    "rakuza.co.kr":            ("Marketplace",     "KR"),
    "m.rakuza.co.kr":          ("Marketplace",     "KR"),
    "rakuza.com":              ("Marketplace",     "KR"),
    "vendora.com.br":          ("Marketplace",     "BR"),
    "vendora.mx":              ("Marketplace",     "MX"),
    "pay.vendora.com.br":      ("Payments",        "BR"),
    "zenkart.co.id":           ("Super App",       "ID"),
    "zenkart.sg":              ("Super App",       "SG"),
    "payhub.io":               ("Payments",        "GLOBAL"),
    "api.payhub.io":           ("Payments",        "GLOBAL"),
    "mercora.com":             ("Marketplace",     "GLOBAL"),
    "mercora.ru":              ("Marketplace",     "RU"),
    "lumina-retail.com":       ("Retail",          "SG"),
    "luminahome.com":          ("Retail",          "SG"),
    "pay.lumina-retail.com":   ("Payments",        "SG"),
    "skyfare.com":             ("Travel",          "TH"),
    "nomadly.travel":          ("Travel",          "FR"),
    "kiosko.cl":               ("Retail",          "CL"),
    "kiosko.pe":               ("Retail",          "PE"),
    "bytecart.io":             ("Search",          "GLOBAL"),
    "freshroute.id":           ("Food Delivery",   "ID"),
    "freshroute.my":           ("Food Delivery",   "MY"),
    "globalwear.com":          ("Fashion",         "DE"),
    "globalwear.eu":           ("Fashion",         "EU"),
    "tokopanda.co.id":         ("Marketplace",     "ID"),
    "pixelbay.io":             ("Digital Assets",  "GLOBAL"),
    "gateway.dfproxy.net":     ("Proxy Network",   "GLOBAL"),
    "edge.dfproxy.net":        ("Proxy Network",   "GLOBAL"),
    "auth.dfnet.io":           ("Account Network", "GLOBAL"),
}

PROXY_TIMEZONES = [
    "Asia/Jakarta", "America/Sao_Paulo", "Indian/Cocos",
    "Europe/Amsterdam", "UTC", "Asia/Seoul",
]

# (client_key, service_type, domain, action, product_name, invoice_category, usd_rate)
# Order within a client = popularity rank (drives the long-tail distribution).
SKU_SPEC = [
    # --- Rakuza Commerce (anchor account) -----------------------------------
    ("rakuza", "Scraper",  "rakuza.co.kr",       "rakuza-pdp",           "Rakuza Product Detail",       "Rakuza/Retail",        0.00300),
    ("rakuza", "Scraper",  "m.rakuza.co.kr",     "rakuza-mobile-pdp",    "Rakuza Mobile PDP",           "Rakuza/Retail",        0.00300),
    ("rakuza", "Scraper",  "rakuza.co.kr",       "rakuza-plp",           "Rakuza Product List",         "Rakuza/Retail",        0.00150),
    ("rakuza", "Scraper",  "rakuza.com",         "rakuza-search",        "Rakuza Search Rank",          "Rakuza Search",        0.00120),
    ("rakuza", "Scraper",  "rakuza.com",         "rakuza-deal",          "Rakuza Deal Tracker",         "Rakuza Promo",         0.00125),
    ("rakuza", "Scraper",  "rakuza.co.kr",       "rakuza-seller",        "Rakuza Seller Index",         "Rakuza Marketplace",   0.00090),
    ("rakuza", "Scraper",  "rakuza.com",         "rakuza-brand-store",   "Rakuza BrandStore Product",   "Rakuza Promo",         0.00125),
    ("rakuza", "Scraper",  "rakuza.com",         "rakuza-review",        "Rakuza Review Feed",          "Rakuza Reviews",       0.00060),
    ("rakuza", "Scraper",  "rakuza.co.kr",       "rakuza-coupon",        "Rakuza Coupon Feed",          "Rakuza Promo",         0.00060),
    ("rakuza", "Scraper",  "rakuza.com",         "rakuza-sitemap",       "Rakuza Sitemap Crawl",        "Rakuza Discovery",     0.00028),
    ("rakuza", "Account",  "auth.dfnet.io",      "rakuza-account-pool",  "Rakuza Account Pool",         "Account Pool KR",      0.00020),

    # --- Vendora Marketplace ------------------------------------------------
    ("vendora", "Scraper",  "vendora.com.br",    "vendora-pdp",          "Vendora Product Detail",      "Vendora/Retail",       0.00180),
    ("vendora", "Proxy",    "gateway.dfproxy.net","proxy-vendora-t1",    "Proxy Vendora - Tier 1",      "Proxy Gateway",        0.00045),
    ("vendora", "Scraper",  "vendora.mx",        "vendora-mx-plp",       "Vendora MX Product List",     "Vendora/Retail LATAM", 0.00150),
    ("vendora", "Proxy",    "edge.dfproxy.net",  "proxy-vendora-t2",     "Proxy Vendora - Tier 2",      "Proxy Edge",           0.00050),
    ("vendora", "Scraper",  "vendora.com.br",    "vendora-seller",       "Vendora Seller Index",        "Vendora Marketplace",  0.00090),
    ("vendora", "Payments", "pay.vendora.com.br","vendora-checkout",     "Vendora Checkout Feed",       "Payments/Vendora",     0.00028),
    ("vendora", "Scraper",  "vendora.com.br",    "vendora-category",     "Vendora Category Tree",       "Vendora Discovery",    0.00090),
    ("vendora", "Scraper",  "vendora.mx",        "vendora-review",       "Vendora Review Feed",         "Vendora Reviews",      0.00060),

    # --- Zenkart ------------------------------------------------------------
    ("zenkart", "Scraper",  "zenkart.co.id",     "zenkart-pdp",          "Zenkart Product Detail",      "Zenkart/Retail",       0.00180),
    ("zenkart", "Proxy",    "gateway.dfproxy.net","proxy-zenkart-t1",    "Proxy Zenkart - Tier 1",      "Proxy Gateway",        0.00048),
    ("zenkart", "Scraper",  "zenkart.co.id",     "zenkart-food",         "Zenkart Food Delivery Fee",   "Food Regular Zenkart", 0.00110),
    ("zenkart", "Scraper",  "zenkart.sg",        "zenkart-sg-plp",       "Zenkart SG Product List",     "Zenkart/Retail SG",    0.00150),
    ("zenkart", "Scraper",  "zenkart.co.id",     "zenkart-transport",    "Zenkart Transport Fare",      "Transport",            0.00090),
    ("zenkart", "Proxy",    "edge.dfproxy.net",  "proxy-zenkart-t2",     "Proxy Zenkart - Tier 2",      "Proxy Edge",           0.00050),
    ("zenkart", "Scraper",  "zenkart.co.id",     "zenkart-brand-store",  "Zenkart BrandStore Product",  "Zenkart Promo",        0.00125),
    ("zenkart", "Scraper",  "zenkart.sg",        "zenkart-voucher",      "Zenkart Voucher Feed",        "Zenkart Promo",        0.00060),
    ("zenkart", "Account",  "auth.dfnet.io",     "zenkart-account-pool", "Zenkart Account Pool",        "Account Pool SEA",     0.00020),

    # --- Payhub -------------------------------------------------------------
    ("payhub", "Payments", "payhub.io",          "payhub-retail",        "Payhub/Retail",               "Payments/Retail",      0.00028),
    ("payhub", "Payments", "payhub.io",          "payhub-subscription",  "Payhub Subscription Sync",    "Payments/Subscription",0.00028),
    ("payhub", "Payments", "api.payhub.io",      "payhub-payout",        "Payhub Payout Ledger",        "Payments/Payout",      0.00032),
    ("payhub", "Payments", "api.payhub.io",      "payhub-dispute",       "Payhub Dispute Feed",         "Payments/Dispute",     0.00040),
    ("payhub", "Account",  "auth.dfnet.io",      "payhub-account-pool",  "Payhub Account Pool",         "Account Pool Global",  0.00020),

    # --- Mercora ------------------------------------------------------------
    ("mercora", "Scraper",  "mercora.com",       "mercora-pdp",          "Mercora Product Detail",      "Mercora/Retail",       0.00180),
    ("mercora", "Scraper",  "mercora.com",       "mercora-price",        "Mercora Price Monitor",       "Mercora Pricing",      0.00120),
    ("mercora", "Proxy",    "gateway.dfproxy.net","proxy-mercora-t1",    "Proxy Mercora - Tier 1",      "Proxy Gateway",        0.00045),
    ("mercora", "Scraper",  "mercora.ru",        "mercora-seller",       "Mercora Merchant Seller",     "Mercora Marketplace",  0.00090),
    ("mercora", "Scraper",  "mercora.ru",        "mercora-review",       "Mercora Review Feed",         "Mercora Reviews",      0.00060),
    ("mercora", "Scraper",  "mercora.com",       "mercora-category",     "Mercora Category Tree",       "Mercora Discovery",    0.00090),

    # --- Lumina Retail ------------------------------------------------------
    ("lumina", "Scraper",  "lumina-retail.com",  "lumina-pdp",           "Lumina Product Detail",       "Lumina/Retail",        0.00180),
    ("lumina", "Proxy",    "gateway.dfproxy.net","proxy-lumina-t1",      "Proxy Lumina - Tier 1",       "Proxy Gateway",        0.00048),
    ("lumina", "Scraper",  "luminahome.com",     "lumina-home-plp",      "Lumina Home Product List",    "Lumina Home",          0.00150),
    ("lumina", "Payments", "pay.lumina-retail.com","lumina-checkout",    "Lumina Checkout Feed",        "Payments/Lumina",      0.00028),
    ("lumina", "Scraper",  "lumina-retail.com",  "lumina-stock",         "Lumina Stock Monitor",        "Lumina Inventory",     0.00090),
    ("lumina", "Scraper",  "luminahome.com",     "lumina-review",        "Lumina Review Feed",          "Lumina Reviews",       0.00060),

    # --- Skyfare ------------------------------------------------------------
    ("skyfare", "Scraper", "skyfare.com",        "skyfare-fare",         "Skyfare Fare Search",         "Skyfare/Flights",      0.00250),
    ("skyfare", "Scraper", "skyfare.com",        "skyfare-bundle",       "Skyfare Hotel Bundle",        "Skyfare Ancillary",    0.00120),
    ("skyfare", "Scraper", "skyfare.com",        "skyfare-seat",         "Skyfare Seatmap",             "Skyfare/Flights",      0.00090),
    ("skyfare", "Scraper", "skyfare.com",        "skyfare-baggage",      "Skyfare Baggage Fee",         "Skyfare Ancillary",    0.00060),

    # --- Nomadly ------------------------------------------------------------
    ("nomadly", "Scraper", "nomadly.travel",     "nomadly-hotel",        "Nomadly Hotel Rate",          "Nomadly/Hotels",       0.00220),
    ("nomadly", "Proxy",   "edge.dfproxy.net",   "proxy-nomadly-t1",     "Proxy Nomadly - Tier 1",      "Proxy Edge",           0.00050),
    ("nomadly", "Scraper", "nomadly.travel",     "nomadly-prorate",      "Nomadly Prorate",             "Nomadly Prorate",      0.00090),
    ("nomadly", "Scraper", "nomadly.travel",     "nomadly-review",       "Nomadly Review Feed",         "Nomadly Reviews",      0.00060),

    # --- Kiosko -------------------------------------------------------------
    ("kiosko", "Scraper",  "kiosko.cl",          "kiosko-pdp",           "Kiosko Product Detail",       "Kiosko/Retail",        0.00180),
    ("kiosko", "Proxy",    "gateway.dfproxy.net","proxy-kiosko-t1",      "Proxy Kiosko - Tier 1",       "Proxy Gateway",        0.00045),
    ("kiosko", "Scraper",  "kiosko.pe",          "kiosko-pe-plp",        "Kiosko PE Product List",      "Kiosko/Retail LATAM",  0.00150),

    # --- Bytecart -----------------------------------------------------------
    ("bytecart", "Scraper", "bytecart.io",       "bytecart-serp",        "Bytecart SERP",               "Bytecart Search",      0.00028),
    ("bytecart", "Proxy",   "edge.dfproxy.net",  "proxy-bytecart-t1",    "Proxy Bytecart - Tier 1",     "Proxy Edge",           0.00050),
    ("bytecart", "Account", "auth.dfnet.io",     "bytecart-account-pool","Bytecart Account Pool",       "Account Pool Global",  0.00020),

    # --- FreshRoute ---------------------------------------------------------
    ("freshroute", "Scraper", "freshroute.id",   "freshroute-menu",      "FreshRoute Menu Feed",        "Food Regular FreshRoute", 0.00110),
    ("freshroute", "Scraper", "freshroute.my",   "freshroute-my-menu",   "FreshRoute MY Menu Feed",     "Food Regular FreshRoute", 0.00110),
    ("freshroute", "Scraper", "freshroute.id",   "freshroute-delivery",  "FreshRoute Delivery Fee",     "Logistic",             0.00090),

    # --- GlobalWear ---------------------------------------------------------
    ("globalwear", "Scraper", "globalwear.com",  "globalwear-pdp",       "GlobalWear Product Detail",   "GlobalWear/Retail",    0.00180),
    ("globalwear", "Scraper", "globalwear.eu",   "globalwear-eu-plp",    "GlobalWear EU Product List",  "GlobalWear/Retail EU", 0.00150),
    ("globalwear", "Proxy",   "gateway.dfproxy.net","proxy-globalwear-t1","Proxy GlobalWear - Tier 1",  "Proxy Gateway",        0.00048),

    # --- Tokopanda ----------------------------------------------------------
    ("tokopanda", "Scraper", "tokopanda.co.id",  "tokopanda-pdp",        "Tokopanda Product Detail",    "Tokopanda/Retail",     0.00180),
    ("tokopanda", "Account", "auth.dfnet.io",    "tokopanda-account-pool","Tokopanda Account Pool",     "Account Pool SEA",     0.00020),

    # --- Pixelbay -----------------------------------------------------------
    ("pixelbay", "Scraper", "pixelbay.io",       "pixelbay-asset",       "Pixelbay Asset Index",        "Pixelbay Catalog",     0.00090),
    ("pixelbay", "Account", "auth.dfnet.io",     "pixelbay-account-pool","Pixelbay Account Pool",       "Account Pool Global",  0.00020),
]

ZIPF_EXPONENT = 1.15   # steepness of the within-client long tail


# ---------------------------------------------------------------------------
# 3. WEIGHT SOLVER — hit client shares AND service shares simultaneously
# ---------------------------------------------------------------------------

def solve_weights(skus: list[dict], iterations: int = 400) -> np.ndarray:
    """Iterative Proportional Fitting.

    Seeds each SKU with a Zipf weight (rank within its client), then alternately
    rescales rows/columns until both the client-share and service-share targets
    are satisfied at the same time.
    """
    w = np.array([1.0 / (s["rank"] ** ZIPF_EXPONENT) for s in skus])

    client_idx = {c: np.array([i for i, s in enumerate(skus) if s["client_key"] == c])
                  for c in CLIENT_REVENUE_SHARE}
    service_idx = {sv: np.array([i for i, s in enumerate(skus) if s["service_type"] == sv])
                   for sv in SERVICE_REVENUE_SHARE}

    for _ in range(iterations):
        for c, idx in client_idx.items():
            w[idx] *= CLIENT_REVENUE_SHARE[c] / w[idx].sum()
        for sv, idx in service_idx.items():
            w[idx] *= SERVICE_REVENUE_SHARE[sv] / w[idx].sum()

    return w / w.sum()


# ---------------------------------------------------------------------------
# 4. DEMAND CURVE
# ---------------------------------------------------------------------------

def build_multipliers(skus, days, rng):
    """Matrix [n_sku, n_day] of demand multipliers, including on/off gaps."""
    n_sku, n_day = len(skus), len(days)

    # Market-wide daily curve
    daily = np.array([WEEKDAY_FACTOR[d.weekday()] for d in days], dtype=float)
    daily *= (1 + GROWTH_PER_DAY) ** np.arange(n_day)
    daily *= rng.lognormal(0, GLOBAL_NOISE_SIGMA, n_day)
    if SPIKE_DAY_INDEX < n_day:
        daily[SPIKE_DAY_INDEX] *= SPIKE_FACTOR
    for d, f in DIP_DAYS.items():
        if d < n_day:
            daily[d] *= f

    m = np.outer(np.ones(n_sku), daily)
    m *= rng.lognormal(0, SKU_NOISE_SIGMA, (n_sku, n_day))

    # Long-tail SKUs bill intermittently; a few onboard mid-month.
    for i, sku in enumerate(skus):
        if sku["rank"] >= 6:
            active = rng.random(n_day) < 0.55
            m[i] *= active
        elif sku["rank"] == 5:
            active = rng.random(n_day) < 0.85
            m[i] *= active
        if sku["rank"] >= 4 and rng.random() < 0.12:      # mid-month onboarding
            m[i, : rng.integers(4, max(5, n_day // 2))] = 0.0

    # Never let a SKU vanish entirely
    for i in range(n_sku):
        if m[i].sum() <= 0:
            m[i, rng.integers(0, n_day)] = 1.0
    return m


# ---------------------------------------------------------------------------
# 5. MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Generate the DataForge synthetic dataset.")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--start", type=str, default=DEFAULT_START.isoformat())
    p.add_argument("--revenue", type=float, default=DEFAULT_TOTAL_REVENUE)
    p.add_argument("--outdir", type=str, default="data")
    args = p.parse_args()

    rng = np.random.default_rng(args.seed)
    start = date.fromisoformat(args.start)
    days = [start + timedelta(days=i) for i in range(args.days)]

    # -- assemble SKU catalogue --------------------------------------------
    skus, rank_counter = [], {}
    for i, (ck, service, domain, action, product, invoice, rate) in enumerate(SKU_SPEC):
        rank_counter[ck] = rank_counter.get(ck, 0) + 1
        tz = PROXY_TIMEZONES[i % len(PROXY_TIMEZONES)] if service == "Proxy" else CLIENTS[ck][3]
        skus.append({
            "sku_id": i + 1,
            "client_key": ck,
            "client_name": CLIENTS[ck][0],
            "service_type": service,
            "domain": domain,
            "action": action,
            "product_name": product,
            "invoice_category": invoice,
            "usd_rate": rate,
            "timezone": tz,
            "rank": rank_counter[ck],
            "success_ratio": rng.uniform(*SUCCESS_RATIO_RANGE),
            "kb_per_request": max(35.0, rng.normal(PROXY_KB_MEAN, PROXY_KB_STD)),
        })

    weights = solve_weights(skus)
    mult = build_multipliers(skus, days, rng)

    # Scale so each SKU's realised revenue == target share exactly
    base = args.revenue * weights / mult.sum(axis=1)
    revenue = base[:, None] * mult

    # -- emit fact rows -----------------------------------------------------
    rows = []
    for i, sku in enumerate(skus):
        for j, day in enumerate(days):
            rev = revenue[i, j]
            if rev <= 0:
                continue
            rate = sku["usd_rate"]

            if sku["service_type"] == "Proxy":
                bandwidth_mb = round(rev / rate, 2)
                success = int(bandwidth_mb * 1024 / sku["kb_per_request"])
                rev_final = round(bandwidth_mb * rate, 6)
            else:
                bandwidth_mb = 0.0
                success = int(round(rev / rate))
                rev_final = round(success * rate, 6)

            if success <= 0:
                continue
            ratio = min(0.999, sku["success_ratio"] * rng.uniform(0.985, 1.012))
            total_request = int(round(success / ratio))

            rows.append({
                "usage_date": day.isoformat(),
                "client_id": list(CLIENTS).index(sku["client_key"]) + 1,
                "service_type": sku["service_type"],
                "domain": sku["domain"],
                "action": sku["action"],
                "product_id": sku["sku_id"],
                "invoice_category": sku["invoice_category"],
                "timezone": sku["timezone"],
                "bandwidth_mb": bandwidth_mb,
                "total_request": total_request,
                "success_request": success,
                "usd_rate": f'{rate:.8f}',
                "revenue_usd": f'{rev_final:.6f}',
            })

    fact = pd.DataFrame(rows).sort_values(
        ["usage_date", "client_id", "service_type", "product_id"]
    ).reset_index(drop=True)

    dim_client = pd.DataFrame([
        {"client_id": i + 1, "client_name": v[0], "client_group": v[1],
         "client_tier": v[2], "home_timezone": v[3]}
        for i, v in enumerate(CLIENTS.values())
    ])

    dim_product = pd.DataFrame([
        {"product_id": s["sku_id"], "product_name": s["product_name"],
         "service_type": s["service_type"], "invoice_category": s["invoice_category"],
         "action": s["action"], "billing_unit": "MB" if s["service_type"] == "Proxy" else "request",
         "list_usd_rate": f'{s["usd_rate"]:.8f}'}
        for s in skus
    ])

    dim_domain = pd.DataFrame([
        {"domain": d, "platform": v[0], "country": v[1]}
        for d, v in DOMAIN_META.items()
    ])

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in [("fact_daily_usage", fact), ("dim_client", dim_client),
                     ("dim_product", dim_product), ("dim_domain", dim_domain)]:
        df.to_csv(out / f"{name}.csv", index=False, quoting=csv.QUOTE_MINIMAL)

    # -- summary ------------------------------------------------------------
    rev_col = fact["revenue_usd"].astype(float)
    total = rev_col.sum()
    print(f"\n  DataForge synthetic dataset  (seed={args.seed})")
    print(f"  {'-' * 58}")
    print(f"  Period            : {days[0]} .. {days[-1]}  ({len(days)} days)")
    print(f"  Fact rows         : {len(fact):,}")
    print(f"  SKUs / products   : {len(skus)}")
    print(f"  Unique actions    : {fact['action'].nunique()}")
    print(f"  Invoice categories: {fact['invoice_category'].nunique()}")
    print(f"  Total revenue     : ${total:,.2f}")
    print(f"  Avg daily revenue : ${total / len(days):,.2f}")
    print(f"  Total requests    : {fact['total_request'].sum() / 1e9:.2f}B")
    print(f"  Avg daily requests: {fact['total_request'].sum() / len(days) / 1e6:.1f}M")
    print(f"  Total bandwidth   : {fact['bandwidth_mb'].sum() / 1024:,.0f} GB")

    print(f"\n  Revenue by service type")
    svc = fact.assign(r=rev_col).groupby("service_type")["r"].sum().sort_values(ascending=False)
    for k, v in svc.items():
        print(f"    {k:<10} ${v:>12,.2f}   {v / total * 100:5.1f}%")

    print(f"\n  Top clients")
    cl = (fact.assign(r=rev_col).merge(dim_client, on="client_id")
              .groupby("client_name")["r"].sum().sort_values(ascending=False))
    for k, v in cl.head(6).items():
        print(f"    {k:<22} ${v:>11,.2f}   {v / total * 100:5.1f}%")

    grp = (fact.assign(r=rev_col).merge(dim_client, on="client_id")
               .groupby("client_group")["r"].sum())
    print(f"\n  Client group split")
    for k, v in grp.items():
        print(f"    {k:<10} {v / total * 100:5.1f}%")

    print(f"\n  Daily revenue curve")
    daily = fact.assign(r=rev_col).groupby("usage_date")["r"].sum()
    for k, v in daily.items():
        bar = "#" * int(v / daily.max() * 46)
        print(f"    {k}  ${v:>9,.0f}  {bar}")
    print(f"\n  -> written to {out.resolve()}/\n")


if __name__ == "__main__":
    main()