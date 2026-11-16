"""Simple, transparent scoring model for imported Shopee product data."""
import math

def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))

def log_score(value, scale):
    value = max(0.0, float(value or 0))
    return clamp((math.log1p(value) / math.log1p(scale)) * 100)

def calculate_score(product, max_sales, max_commission):
    # Missing values are treated neutrally/zero; they are not fabricated.
    sales_score = log_score(product.get("sales", 0), max(max_sales, 1))
    commission_score = clamp((float(product.get("commission_rate", 0) or 0) / max(max_commission, 1)) * 100)
    rating = float(product.get("rating", 0) or 0)
    rating_score = clamp((rating / 5.0) * 100) if rating else 0
    price = float(product.get("price", 0) or 0)
    # Initial affordability heuristic: strongest around Rp20k-Rp150k, tapering outside.
    if price <= 0:
        price_score = 0
    elif price <= 150000:
        price_score = 100 - (abs(math.log(max(price, 1) / 60000)) * 15)
    else:
        price_score = 75 - (math.log(price / 150000) * 18)
    price_score = clamp(price_score)
    score = round(
        sales_score * 0.35 +
        commission_score * 0.30 +
        rating_score * 0.20 +
        price_score * 0.15
    )
    return score, {
        "popularitas": round(sales_score),
        "komisi": round(commission_score),
        "rating": round(rating_score),
        "harga": round(price_score),
    }
