"""Pilih N produk terbaik per kategori dari file ekspor Shopee Affiliate.

Sumber: file "Link Produk Sekaligus" (LinkProdukSekaligus*.csv) yang diunduh dari
dasbor Shopee Affiliate -> Penawaran Produk -> pilih produk -> ambil link sekaligus.
Satu file = hasil satu kata kunci. Kategori tiap file dideteksi otomatis dengan
mencocokkan nama file/folder dan nama-nama produk ke 'queries' di config/research.json.
Kalau deteksi salah, ganti nama file supaya memuat kata kunci atau nama kategorinya,
misalnya "rak dapur.csv" atau "Peralatan Dapur - chopper.csv", atau taruh di folder
bernama kategori.

Hasilnya CSV dengan kolom yang dibaca generator (name, category, price, ...).
Impor ke Google Sheet (File > Impor > Upload > Ganti sheet saat ini) atau simpan
sebagai data/import/products.csv.

Contoh:
  python scripts/curate_exports.py ~/Downloads/LinkProdukSekaligus*.csv
  python scripts/curate_exports.py ~/Downloads/ekspor --per-category 10 -o produk_minggu_ini.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import calculate_score  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "research.json"
OUT_COLUMNS = ["name", "category", "price", "commission_rate", "commission_amount", "sales", "rating",
               "review_count", "image_url", "product_url", "affiliate_url", "shop_name", "item_id", "keyword"]

# Kolom ekspor Shopee Affiliate (bahasa Indonesia) -> nama internal
EXPORT_COLUMNS = {
    "item_id": ["ID Produk", "Item ID"],
    "name": ["Nama Produk", "Product Name"],
    "price": ["Harga", "Price"],
    "sales": ["Penjualan", "Sales"],
    "shop_name": ["Nama Toko", "Shop Name"],
    "commission_rate": ["Komisi hingga", "Commission Rate"],
    "commission_amount": ["Komisi", "Commission"],
    "product_url": ["Link Produk", "Product Link"],
    "affiliate_url": ["Link Komisi Ekstra", "Link Komisi", "Offer Link"],
}
MULTIPLIER = {"RB": 1_000, "K": 1_000, "JT": 1_000_000, "M": 1_000_000}


def parse_amount(text) -> float:
    """'14,4RB' -> 14400, '10RB+' -> 10000, 'Rp1.008' -> 1008, '1,2JT' -> 1200000, '7,5%' -> 7.5."""
    s = str(text or "").strip().upper().replace("RP", "").replace("+", "").replace("%", "").replace(" ", "")
    if not s:
        return 0.0
    m = re.fullmatch(r"([\d.,]+)(RB|K|JT|M)?", s)
    if not m:
        return 0.0
    num, unit = m.group(1), m.group(2)
    if unit:
        num = num.replace(".", "").replace(",", ".") if "," in num else num
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", num):  # 1.250.000 / 14.400 (format id-ID)
        num = num.replace(".", "").replace(",", ".")
    else:
        num = num.replace(",", ".")
    try:
        return float(num) * MULTIPLIER.get(unit, 1)
    except ValueError:
        return 0.0


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def pick(row: dict, key: str) -> str:
    for col in EXPORT_COLUMNS[key]:
        if col in row and row[col] is not None:
            return str(row[col]).strip()
    return ""


def read_export(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if rows and not any(c in rows[0] for c in EXPORT_COLUMNS["name"]):
        raise ValueError(f"{path.name}: bukan file ekspor 'Link Produk Sekaligus' (kolom 'Nama Produk' tidak ada)")
    products = []
    for row in rows:
        name = re.sub(r"\s+", " ", pick(row, "name"))
        if not name:
            continue
        products.append({
            "item_id": pick(row, "item_id"),
            "name": name,
            "price": parse_amount(pick(row, "price")),
            "sales": parse_amount(pick(row, "sales")),
            "shop_name": pick(row, "shop_name"),
            "commission_rate": parse_amount(pick(row, "commission_rate")),
            "commission_amount": parse_amount(pick(row, "commission_amount")) or None,
            "product_url": pick(row, "product_url"),
            "affiliate_url": pick(row, "affiliate_url"),
            "rating": 0.0,
        })
    return products


def detect_category(path: Path, products: list[dict], queries: list[dict]) -> tuple[str, str, str]:
    """Return (category, keyword, how)."""
    keyword_queries = [q for q in queries if q.get("keyword")]
    hint = norm(f"{path.parent.name} {path.stem}")
    # 1) nama file/folder memuat kata kunci (paling spesifik) atau nama kategori
    for q in sorted(keyword_queries, key=lambda q: -len(q["keyword"])):
        if f" {norm(q['keyword'])} " in f" {hint} ":
            return q["category"], q["keyword"], "nama file"
    for cat in sorted({q["category"] for q in queries}, key=len, reverse=True):
        if f" {norm(cat)} " in f" {hint} ":
            return cat, "", "nama file"
    # 2) banyak nama produk memuat kata khas dari kata kunci (kata >= 4 huruf, mis. "organizer", "chopper")
    names = [f" {norm(p['name'])} " for p in products]
    best, best_share = None, 0.0
    for q in keyword_queries:
        tokens = [t for t in norm(q["keyword"]).split() if len(t) >= 4] or norm(q["keyword"]).split()
        share = max(sum(f" {t}" in n for n in names) for t in tokens) / max(len(names), 1)
        if share > best_share:
            best, best_share = q, share
    if best and best_share >= 0.25:
        return best["category"], best["keyword"], f"isi produk ({best_share:.0%})"
    return "Lainnya", "", "tidak terdeteksi"


def passes(p: dict, f: dict) -> str | None:
    """None kalau lolos, atau alasan ditolak."""
    if not p["product_url"].startswith("https://"):
        return "tanpa link produk"
    if p["commission_rate"] < f.get("min_commission_rate", 0):
        return "komisi rendah"
    if p["price"] and not (f.get("min_price", 0) <= p["price"] <= f.get("max_price", float("inf"))):
        return "harga di luar rentang"
    if p["sales"] < f.get("min_sales", 0):
        return "penjualan rendah"
    low = p["name"].lower()
    if any(k.lower() in low for k in f.get("exclude_keywords", [])):
        return "kata terlarang"
    return None


def select(products: list[dict], n: int, max_per_shop: int) -> list[dict]:
    ctx = {
        "max_sales": max((p["sales"] for p in products), default=1),
        "max_commission_rate": max((p["commission_rate"] for p in products), default=1),
        "max_commission_amount": max(((p["commission_amount"] or 0) for p in products), default=0),
    }
    for p in products:
        p["score"], _ = calculate_score(p, ctx)
    ranked = sorted(products, key=lambda p: (p["score"], p["sales"]), reverse=True)
    picked, per_shop = [], {}
    for p in ranked:
        shop = p["shop_name"].lower()
        if shop and per_shop.get(shop, 0) >= max_per_shop:
            continue
        picked.append(p)
        per_shop[shop] = per_shop.get(shop, 0) + 1
        if len(picked) >= n:
            break
    return picked


def collect_files(inputs: list[str]) -> list[Path]:
    files = []
    for item in inputs:
        p = Path(item).expanduser()
        if p.is_dir():
            files += sorted(x for x in p.rglob("*.csv") if x.is_file())
        elif p.is_file():
            files.append(p)
        else:
            print(f"PERINGATAN: {item} tidak ditemukan", file=sys.stderr)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="file CSV ekspor atau folder berisi file-file tersebut")
    ap.add_argument("-o", "--output", default="produk_kurasi.csv", help="file CSV hasil (default: produk_kurasi.csv)")
    ap.add_argument("-n", "--per-category", type=int, default=10)
    ap.add_argument("--max-per-shop", type=int, default=2)
    ap.add_argument("--config", default=str(CONFIG_PATH))
    args = ap.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    queries, filters = cfg.get("queries", []), cfg.get("filters", {})
    files = collect_files(args.inputs)
    if not files:
        raise SystemExit("Tidak ada file CSV yang ditemukan.")

    by_cat: dict[str, dict] = {}
    seen: set[str] = set()
    print(f"{'File':<52} {'Kategori':<18} {'Deteksi':<18} Produk")
    for path in files:
        try:
            products = read_export(path)
        except (ValueError, UnicodeDecodeError) as e:
            print(f"LEWATI {path.name}: {e}")
            continue
        cat, kw, how = detect_category(path, products, queries)
        print(f"{path.name[:52]:<52} {cat[:18]:<18} {how[:18]:<18} {len(products)}")
        bucket = by_cat.setdefault(cat, {"products": [], "keywords": set(), "rejected": {}})
        bucket["keywords"].add(kw)
        for p in products:
            key = p["item_id"] or p["product_url"] or p["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            reason = passes(p, filters)
            if reason:
                bucket["rejected"][reason] = bucket["rejected"].get(reason, 0) + 1
                continue
            p["category"], p["keyword"] = cat, kw
            bucket["products"].append(p)

    rows = []
    print(f"\n{'Kategori':<20} {'Kandidat':>8} {'Dipilih':>8}  Ditolak")
    for cat in sorted(by_cat):
        b = by_cat[cat]
        picked = select(b["products"], args.per_category, args.max_per_shop)
        rows += picked
        rej = ", ".join(f"{k}: {v}" for k, v in b["rejected"].items()) or "-"
        print(f"{cat[:20]:<20} {len(b['products']):>8} {len(picked):>8}  {rej}")
        if "Lainnya" == cat:
            print("  ^ ganti nama file agar memuat kata kunci/kategori dari config/research.json")

    out = Path(args.output).expanduser()
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(OUT_COLUMNS)
        for p in rows:
            w.writerow([
                p["name"], p["category"], int(p["price"]), f"{p['commission_rate']:g}",
                int(p["commission_amount"]) if p["commission_amount"] else "", int(p["sales"]), "", "", "",
                p["product_url"], p["affiliate_url"], p["shop_name"], p["item_id"], p["keyword"],
            ])
    print(f"\nSelesai: {len(rows)} produk dari {len(by_cat)} kategori -> {out}")
    return rows


if __name__ == "__main__":
    main()
