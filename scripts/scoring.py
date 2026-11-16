"""Transparent scoring model for daily Shopee product research.

Components (0-100 each):
  popularitas  30%  total sales, log-scaled against the day's best candidate
  komisi       30%  70% commission rate + 30% estimated commission in Rupiah
  rating       20%  rating star, emphasising the 4.0-5.0 band
  harga        10%  affordability sweet spot (Rp20k-Rp150k)
  momentum     10%  sales growth since the previous snapshot (neutral 50 if unknown)

Missing values are never fabricated: they score 0 (or neutral for momentum).
"""
import math

WEIGHTS = {"popularitas": 0.30, "komisi": 0.30, "rating": 0.20, "harga": 0.10, "momentum": 0.10}


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def log_score(value, scale):
    value = max(0.0, float(value or 0))
    scale = max(float(scale or 0), 1.0)
    return clamp((math.log1p(value) / math.log1p(scale)) * 100)


def price_score(price):
    price = float(price or 0)
    if price <= 0:
        return 0.0
    if price <= 150000:
        return clamp(100 - abs(math.log(max(price, 1) / 60000)) * 15)
    return clamp(75 - math.log(price / 150000) * 18)


def rating_score(rating):
    rating = float(rating or 0)
    if rating <= 0:
        return 0.0
    # 4.0 -> 50, 4.5 -> 75, 5.0 -> 100; below 4.0 drops fast
    return clamp(50 + (rating - 4.0) * 50) if rating >= 4.0 else clamp(rating / 4.0 * 50)


def momentum_score(growth_pct):
    """growth_pct = daily sales growth in percent, or None when unknown."""
    if growth_pct is None:
        return 50.0
    if growth_pct <= 0:
        return 30.0
    # 1%/day -> ~62, 5%/day -> ~85, >=10%/day -> 100
    return clamp(50 + math.log1p(growth_pct) / math.log1p(10) * 50)


def calculate_score(product, context):
    """context: dict with max_sales, max_commission_rate, max_commission_amount."""
    pop = log_score(product.get("sales", 0), context.get("max_sales", 1))

    rate = float(product.get("commission_rate", 0) or 0)
    amount = float(product.get("commission_amount", 0) or 0)
    rate_part = clamp(rate / max(context.get("max_commission_rate", 1), 1) * 100)
    amount_part = log_score(amount, context.get("max_commission_amount", 1)) if amount else 0
    kom = rate_part * 0.7 + amount_part * 0.3 if context.get("max_commission_amount") else rate_part

    parts = {
        "popularitas": pop,
        "komisi": kom,
        "rating": rating_score(product.get("rating")),
        "harga": price_score(product.get("price")),
        "momentum": momentum_score(product.get("sales_growth_pct")),
    }
    score = sum(parts[k] * w for k, w in WEIGHTS.items())
    return round(score), {k: round(v) for k, v in parts.items()}
