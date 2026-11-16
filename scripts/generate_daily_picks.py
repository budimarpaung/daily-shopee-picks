import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from scoring import calculate_score

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "import" / "products.csv"
OUTPUT_PATH = ROOT / "data" / "products.json"
LIMIT = 20
WIB = timezone(timedelta(hours=7))

def as_number(value, default=0):
    try:
        return float(str(value or "").replace(",", ".").strip())
    except (TypeError, ValueError):
        return default

def main():
    if not CSV_PATH.exists():
        raise SystemExit(f"CSV tidak ditemukan: {CSV_PATH}")

    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    products = []
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        p = {
            "name": name,
            "category": (row.get("category") or "Lainnya").strip(),
            "price": as_number(row.get("price")),
            "commission_rate": as_number(row.get("commission_rate")),
            "sales": as_number(row.get("sales")),
            "rating": as_number(row.get("rating")),
            "review_count": int(as_number(row.get("review_count"))),
            "image_url": (row.get("image_url") or "").strip(),
            "product_url": (row.get("product_url") or "").strip(),
            "affiliate_url": (row.get("affiliate_url") or "").strip(),
        }
        products.append(p)

    if not products:
        raise SystemExit("CSV belum berisi produk. Tambahkan minimal satu baris produk.")

    max_sales = max((p["sales"] for p in products), default=1)
    max_commission = max((p["commission_rate"] for p in products), default=1)

    for p in products:
        p["score"], p["score_breakdown"] = calculate_score(p, max_sales, max_commission)
        reasons = []
        if p["sales"] > 0:
            reasons.append("memiliki data penjualan")
        if p["commission_rate"] > 0:
            reasons.append(f"komisi {p['commission_rate']:g}%")
        if p["rating"] >= 4.7:
            reasons.append("rating tinggi")
        if p["price"] and p["price"] <= 150000:
            reasons.append("harga relatif terjangkau")
        p["recommendation_reason"] = "Kandidat menarik: " + ", ".join(reasons) + "." if reasons else "Data awal tersedia; perlu evaluasi manual."

    # De-duplicate by product URL when available, otherwise by name.
    unique = {}
    for p in products:
        key = p["product_url"] or p["name"].lower()
        if key not in unique or p["score"] > unique[key]["score"]:
            unique[key] = p
    ranked = sorted(unique.values(), key=lambda p: (p["score"], p["sales"]), reverse=True)[:LIMIT]

    now = datetime.now(WIB)
    output = {
        "generated_at": now.strftime("%Y-%m-%d"),
        "updated_at": now.strftime("%H:%M WIB"),
        "total_candidates": len(unique),
        "products": ranked
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Berhasil membuat {len(ranked)} rekomendasi dari {len(unique)} kandidat.")

if __name__ == "__main__":
    main()
