"""Generate daily Shopee affiliate picks.

Sources:
  api   -> live research via the official Shopee Affiliate Open API
  csv   -> manual data: Google Sheets published as CSV (env PRODUCTS_CSV_URL),
           falling back to data/import/products.csv
  auto  -> api when SHOPEE_APP_ID & SHOPEE_APP_SECRET are set, else csv (default)

Usage:
  python scripts/generate_daily_picks.py               # auto
  python scripts/generate_daily_picks.py --source api
  python scripts/generate_daily_picks.py --dry-run     # print, don't write files
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import WEIGHTS, calculate_score  # noqa: E402
import shopee_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "research.json"
CSV_PATH = ROOT / "data" / "import" / "products.csv"
OUTPUT_PATH = ROOT / "data" / "products.json"
HISTORY_DIR = ROOT / "data" / "history"
SNAPSHOT_PATH = HISTORY_DIR / "sales_snapshot.json"
HISTORY_KEEP_DAYS = 30
CSV_URL_ENV = "PRODUCTS_CSV_URL"
CSV_MAX_BYTES = 5 * 1024 * 1024
WIB = timezone(timedelta(hours=7))

SORT_MAP = {
    "relevance": shopee_api.SORT_RELEVANCE,
    "sales": shopee_api.SORT_ITEM_SOLD_DESC,
    "price_high": shopee_api.SORT_PRICE_DESC,
    "price_low": shopee_api.SORT_PRICE_ASC,
    "commission": shopee_api.SORT_COMMISSION_DESC,
}
LIST_MAP = {"all": shopee_api.LIST_ALL, "top_performing": shopee_api.LIST_TOP_PERFORMING}


# ---------------------------------------------------------------- utilities
def as_number(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("Rp", "").replace(" ", "")
    if not s:
        return default
    # "1.250.000" (id-ID thousands) vs "4.8" / "0.25"
    if s.count(".") > 1 or ("," in s and "." in s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return default


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_config():
    cfg = load_json(CONFIG_PATH, {})
    cfg.setdefault("top_n", 20)
    cfg.setdefault("max_per_category", 5)
    cfg.setdefault("max_per_shop", 2)
    cfg.setdefault("filters", {})
    cfg.setdefault("freshness", {"lookback_days": 3, "penalty_per_appearance": 0.07})
    cfg.setdefault("defaults", {"limit": 50, "pages": 1, "sort": "sales"})
    cfg.setdefault("queries", [])
    return cfg


# ------------------------------------------------------------------ sources
def normalize_api_node(node: dict, category: str) -> dict:
    rate = as_number(node.get("commissionRate"))
    # API returns fractions ("0.08" = 8%); guard against already-percent values
    rate_pct = rate * 100 if rate <= 1 else rate
    price_min = as_number(node.get("priceMin"))
    price_max = as_number(node.get("priceMax"))
    item_id = str(node.get("itemId") or "").strip()
    shop_id = str(node.get("shopId") or "").strip()
    product_url = node.get("productLink") or (
        f"https://shopee.co.id/product/{shop_id}/{item_id}" if shop_id and item_id else "")
    return {
        "id": item_id or None,
        "name": (node.get("productName") or "").strip(),
        "category": category,
        "price": price_min or price_max,
        "price_max": price_max if price_max and price_max != price_min else None,
        "discount_rate": int(as_number(node.get("priceDiscountRate"))) or None,
        "commission_rate": round(rate_pct, 2),
        "commission_amount": round(as_number(node.get("commission"))) or None,
        "seller_commission_rate": round(as_number(node.get("sellerCommissionRate")) * 100, 2) or None,
        "sales": as_number(node.get("sales")),
        "rating": round(as_number(node.get("ratingStar")), 2),
        "review_count": None,
        "shop_name": (node.get("shopName") or "").strip() or None,
        "shop_id": shop_id or None,
        "image_url": node.get("imageUrl") or "",
        "product_url": product_url,
        "affiliate_url": node.get("offerLink") or "",
        "offer_ends_at": int(node["periodEndTime"]) if node.get("periodEndTime") else None,
        "source": "shopee_api",
    }


def fetch_from_api(cfg) -> tuple[list[dict], list[str]]:
    client = shopee_api.ShopeeAffiliateClient.from_env()
    defaults = cfg["defaults"]
    products, warnings = [], []
    for q in cfg["queries"]:
        label = q.get("category") or q.get("keyword") or "Lainnya"
        try:
            nodes = client.product_offers(
                keyword=q.get("keyword"),
                list_type=LIST_MAP.get(q.get("list")) if q.get("list") else None,
                match_id=q.get("match_id"),
                product_cat_id=q.get("product_cat_id"),
                sort_type=SORT_MAP.get(q.get("sort", defaults.get("sort", "sales")), 2),
                limit=int(q.get("limit", defaults.get("limit", 50))),
                pages=int(q.get("pages", defaults.get("pages", 1))),
                is_ams_offer=q.get("ams_only"),
                is_key_seller=q.get("key_seller_only"),
            )
        except shopee_api.ShopeeAPIError as e:
            warnings.append(f"[{label}] {e}")
            print(f"  ! {label}: {e}", file=sys.stderr)
            continue
        print(f"  - {label} ({q.get('keyword') or q.get('list')}): {len(nodes)} produk")
        products.extend(normalize_api_node(n, label) for n in nodes)
    return products, warnings


def normalize_csv_url(url: str) -> str:
    """Turn Google Drive / Google Sheets share links into direct CSV download links.

    - drive.google.com/file/d/<ID>/view...      -> drive.google.com/uc?export=download&id=<ID>
    - drive.google.com/open?id=<ID>             -> same
    - docs.google.com/spreadsheets/d/<ID>/edit#gid=<G> -> .../d/<ID>/export?format=csv&gid=<G>
    Other URLs (e.g. 'Publish to web' links ending in output=csv) are returned unchanged.
    """
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [x for x in parsed.path.split("/") if x]
    query = urllib.parse.parse_qs(parsed.query)
    if host == "drive.google.com":
        file_id = None
        if len(parts) >= 3 and parts[0] == "file" and parts[1] == "d":
            file_id = parts[2]
        elif query.get("id"):
            file_id = query["id"][0]
        if file_id:
            return "https://drive.google.com/uc?export=download&id=" + urllib.parse.quote(file_id)
    if host == "docs.google.com" and len(parts) >= 3 and parts[:2] == ["spreadsheets", "d"] and parts[2] != "e":
        gid = (query.get("gid") or [None])[0]
        if not gid and parsed.fragment.startswith("gid="):
            gid = parsed.fragment[4:]
        out = f"https://docs.google.com/spreadsheets/d/{parts[2]}/export?format=csv"
        return out + (f"&gid={urllib.parse.quote(gid)}" if gid else "")
    return url


def download_csv(url: str) -> list[dict]:
    """Download a CSV (Google Drive file, Google Sheets, or any https URL) and parse it."""
    url = normalize_csv_url(url)
    parsed = urllib.parse.urlparse(url)
    local = parsed.hostname in ("127.0.0.1", "localhost")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError("URL harus diawali https://")
    req = urllib.request.Request(url, headers={"User-Agent": "daily-shopee-picks"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read(CSV_MAX_BYTES + 1)
    if len(data) > CSV_MAX_BYTES:
        raise ValueError("file CSV lebih dari 5 MB")
    text = data.decode("utf-8-sig")
    if text.lstrip().startswith("<"):
        raise ValueError("yang terunduh adalah halaman HTML, bukan CSV. Pastikan file dibagikan 'Siapa saja yang memiliki link' (Drive/Sheets) atau di-'Publish to web' sebagai CSV")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows or "name" not in rows[0]:
        raise ValueError("CSV kosong atau tidak punya kolom 'name'")
    return rows


def load_csv_rows() -> tuple[list[dict], str, list[str]]:
    """Return (rows, origin, warnings). origin is 'sheet' or 'csv'."""
    warnings: list[str] = []
    url = os.environ.get(CSV_URL_ENV, "").strip()
    if url:
        try:
            rows = download_csv(url)
            print(f"CSV diunduh dari {CSV_URL_ENV}: {len(rows)} baris")
            return rows, "sheet", warnings
        except Exception as e:  # network error, bad URL, unpublished sheet...
            warnings.append(f"Gagal mengunduh {CSV_URL_ENV} ({e}); memakai {CSV_PATH.name} di repository.")
            print("PERINGATAN:", warnings[-1])
    if not CSV_PATH.exists():
        raise SystemExit(f"CSV tidak ditemukan: {CSV_PATH}")
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f)), "csv", warnings


def fetch_from_csv() -> tuple[list[dict], str, list[str]]:
    rows, origin, warnings = load_csv_rows()
    products = []
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        products.append({
            "id": (row.get("item_id") or "").strip() or None,
            "name": name,
            "category": (row.get("category") or "Lainnya").strip(),
            "price": as_number(row.get("price")),
            "commission_rate": as_number(row.get("commission_rate")),
            "commission_amount": None,
            "sales": as_number(row.get("sales")),
            "rating": as_number(row.get("rating")),
            "review_count": int(as_number(row.get("review_count"))) or None,
            "shop_name": (row.get("shop_name") or "").strip() or None,
            "image_url": (row.get("image_url") or "").strip(),
            "product_url": (row.get("product_url") or "").strip(),
            "affiliate_url": (row.get("affiliate_url") or "").strip(),
            "source": origin,
        })
    return products, origin, warnings


# ------------------------------------------------------------------ ranking
def product_key(p):
    return p.get("id") or p.get("product_url") or p["name"].lower()


def apply_filters(products, f, strict=True):
    if not strict:
        return [p for p in products if p.get("name")]
    excl = [k.lower() for k in f.get("exclude_keywords", [])]
    out = []
    for p in products:
        if not p.get("name"):
            continue
        name = p["name"].lower()
        if any(k in name for k in excl):
            continue
        if p["rating"] and p["rating"] < f.get("min_rating", 0):
            continue
        if p["sales"] < f.get("min_sales", 0):
            continue
        if p["price"] and not (f.get("min_price", 0) <= p["price"] <= f.get("max_price", float("inf"))):
            continue
        if p["commission_rate"] < f.get("min_commission_rate", 0):
            continue
        out.append(p)
    return out


def dedupe(products):
    """Keep one entry per product; merge category labels it was found under."""
    unique: dict[str, dict] = {}
    for p in products:
        k = product_key(p)
        if k in unique:
            cats = unique[k].setdefault("found_in", [unique[k]["category"]])
            if p["category"] not in cats:
                cats.append(p["category"])
            continue
        unique[k] = p
    for p in unique.values():
        # Prefer a real category over the generic research buckets
        generic = {"Top Performing", "Komisi Tinggi"}
        cats = p.get("found_in") or [p["category"]]
        specific = [c for c in cats if c not in generic]
        if specific:
            p["category"] = specific[0]
        p["tags"] = [c for c in cats if c in generic]
        p.pop("found_in", None)
    return list(unique.values())


def recent_appearances(lookback_days: int, today: date) -> dict[str, int]:
    counts: dict[str, int] = {}
    for i in range(1, lookback_days + 1):
        day = load_json(HISTORY_DIR / f"{(today - timedelta(days=i)).isoformat()}.json", {})
        for item in day.get("products", []):
            counts[item["key"]] = counts.get(item["key"], 0) + 1
    return counts


def build_reason(p):
    bits = []
    if p.get("sales_growth_pct") and p["sales_growth_pct"] >= 1:
        bits.append(f"penjualan naik {p['sales_growth_pct']:.1f}%/hari")
    if p["sales"] >= 1000:
        bits.append(f"{int(p['sales']):,} terjual".replace(",", "."))
    if p["commission_rate"] >= 8:
        bits.append(f"komisi tinggi {p['commission_rate']:g}%")
    elif p["commission_rate"] > 0:
        bits.append(f"komisi {p['commission_rate']:g}%")
    if p.get("commission_amount"):
        bits.append(f"±Rp{int(p['commission_amount']):,}/penjualan".replace(",", "."))
    if p["rating"] >= 4.8:
        bits.append(f"rating {p['rating']:g}")
    if p.get("discount_rate") and p["discount_rate"] >= 20:
        bits.append(f"diskon {p['discount_rate']}%")
    if p["price"] and p["price"] <= 100000:
        bits.append("harga ramah impulse-buy")
    if not bits:
        return "Data awal tersedia; perlu evaluasi manual."
    return bits[0][0].upper() + ", ".join(bits)[1:] + "."


def select_diverse(ranked, top_n, max_per_cat, max_per_shop):
    picked, cat_count, shop_count, leftovers = [], {}, {}, []
    for p in ranked:
        c, s = p["category"], p.get("shop_id") or p.get("shop_name")
        if cat_count.get(c, 0) >= max_per_cat or (s and shop_count.get(s, 0) >= max_per_shop):
            leftovers.append(p)
            continue
        picked.append(p)
        cat_count[c] = cat_count.get(c, 0) + 1
        if s:
            shop_count[s] = shop_count.get(s, 0) + 1
        if len(picked) >= top_n:
            return picked
    # not enough diversity available -> fill with best remaining
    for p in leftovers:
        if len(picked) >= top_n:
            break
        picked.append(p)
    return sorted(picked, key=lambda p: p["score"], reverse=True)


def rank(products, cfg, today: date, strict_filters=True):
    candidates = dedupe(apply_filters(products, cfg["filters"], strict_filters))
    if not candidates:
        return [], 0

    snapshot = load_json(SNAPSHOT_PATH, {})
    for p in candidates:
        prev = snapshot.get(product_key(p))
        if prev and prev.get("sales") and p["sales"]:
            days = max((today - date.fromisoformat(prev["date"])).days, 1)
            p["sales_growth_pct"] = round(max(p["sales"] - prev["sales"], 0) / prev["sales"] * 100 / days, 2)
        else:
            p["sales_growth_pct"] = None

    ctx = {
        "max_sales": max(p["sales"] for p in candidates),
        "max_commission_rate": max(p["commission_rate"] for p in candidates),
        "max_commission_amount": max((p.get("commission_amount") or 0) for p in candidates),
    }
    fresh = cfg["freshness"]
    seen = recent_appearances(int(fresh.get("lookback_days", 0)), today)
    for p in candidates:
        base, breakdown = calculate_score(p, ctx)
        n_seen = seen.get(product_key(p), 0)
        penalty = min(n_seen * float(fresh.get("penalty_per_appearance", 0)), 0.5)
        p["score"] = round(base * (1 - penalty))
        p["score_breakdown"] = breakdown
        p["days_featured_recently"] = n_seen
        p["is_new"] = n_seen == 0
        p["recommendation_reason"] = build_reason(p)

    ranked = sorted(candidates, key=lambda p: (p["score"], p["sales"]), reverse=True)
    picks = select_diverse(ranked, int(cfg["top_n"]), int(cfg["max_per_category"]), int(cfg["max_per_shop"]))
    return picks, len(candidates)


# ------------------------------------------------------------------ outputs
def save_history(all_products, picks, today: date):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (HISTORY_DIR / f"{today.isoformat()}.json").write_text(json.dumps({
        "date": today.isoformat(),
        "products": [{"key": product_key(p), "name": p["name"], "score": p["score"]} for p in picks],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    snapshot = load_json(SNAPSHOT_PATH, {})
    for p in all_products:
        if p.get("sales"):
            snapshot[product_key(p)] = {"sales": p["sales"], "date": today.isoformat()}
    cutoff = (today - timedelta(days=HISTORY_KEEP_DAYS)).isoformat()
    snapshot = {k: v for k, v in snapshot.items() if v["date"] >= cutoff}
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    for f in HISTORY_DIR.glob("20??-??-??.json"):
        if f.stem < cutoff:
            f.unlink()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["auto", "api", "csv"], default=os.environ.get("PICKS_SOURCE", "auto"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    now = datetime.now(WIB)
    today = now.date()

    has_creds = bool(os.environ.get("SHOPEE_APP_ID") and os.environ.get("SHOPEE_APP_SECRET"))
    source = args.source if args.source != "auto" else ("api" if has_creds else "csv")
    print(f"Sumber data: {source}")

    warnings: list[str] = []
    if source == "api":
        raw, warnings = fetch_from_api(cfg)
        if not raw:
            # Do NOT overwrite yesterday's data with nothing; fail loudly instead.
            raise SystemExit("Shopee API tidak mengembalikan produk. products.json tidak diubah.\n" + "\n".join(warnings))
        picks, n_candidates = rank(raw, cfg, today, strict_filters=True)
    else:
        raw, source, warnings = fetch_from_csv()
        # CSV is curated manually -> don't drop rows with strict filters
        picks, n_candidates = rank(raw, cfg, today, strict_filters=False)

    if not picks:
        raise SystemExit("Tidak ada produk yang lolos filter. Longgarkan 'filters' di config/research.json.")

    output = {
        "generated_at": today.isoformat(),
        "updated_at": now.strftime("%H:%M WIB"),
        "source": source,
        "total_fetched": len(raw),
        "total_candidates": n_candidates,
        "new_today": sum(1 for p in picks if p.get("is_new")),
        "weights": {k: round(v * 100) for k, v in WEIGHTS.items()},
        "warnings": warnings,
        "products": picks,
    }

    if args.dry_run:
        for i, p in enumerate(picks, 1):
            print(f"{i:>2}. [{p['score']:>3}] {p['category']:<16} {p['name'][:60]}")
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    save_history(raw, picks, today)
    print(f"Berhasil: {len(picks)} rekomendasi dari {n_candidates} kandidat ({len(raw)} hasil riset).")


if __name__ == "__main__":
    main()
