"""Tes untuk scripts/curate_exports.py (kurasi dari file ekspor Shopee Affiliate)."""
import csv
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import curate_exports as cur  # noqa: E402

HEADER = "ID Produk,Nama Produk,Harga,Penjualan,Nama Toko,Komisi hingga,Komisi,Link Produk,Link Komisi Ekstra\n"


def row(i, name, price, sales, shop, rate):
    return f'{i},{name},"{price}",{sales},{shop},"{rate}",Rp1.000,https://shopee.co.id/product/9/{i},https://s.shopee.co.id/x{i}\n'


class CurateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_parse_amount(self):
        p = cur.parse_amount
        self.assertEqual(p("14,4RB"), 14400)
        self.assertEqual(p("10RB+"), 10000)
        self.assertEqual(p("1,2JT"), 1200000)
        self.assertEqual(p("Rp1.008"), 1008)
        self.assertEqual(p("Rp10.989"), 10989)
        self.assertEqual(p("7,5%"), 7.5)
        self.assertEqual(p("500+"), 500)
        self.assertEqual(p(""), 0)

    def test_select_per_category(self):
        a = self.tmp / "LinkProdukSekaligus1.csv"
        a.write_text(HEADER + "".join(
            row(i, f"Chopper Elektrik Tipe {i}", "50,0RB", "5RB+", f"Toko {i % 4}", "8%") for i in range(1, 16)
        ) + row(99, "Chopper Rokok", "50,0RB", "5RB+", "Toko X", "8%")
          + row(98, "Chopper Murah", "5,0RB", "5RB+", "Toko Y", "8%")
          + row(97, "Chopper Komisi Kecil", "50,0RB", "5RB+", "Toko Z", "1%"), encoding="utf-8")
        b = self.tmp / "organizer rumah.csv"  # kategori dari nama file
        b.write_text(HEADER + row(1, "Duplikat produk", "50,0RB", "1RB+", "Toko 1", "8%")
                     + row(200, "Kotak Serbaguna", "40,0RB", "2RB+", "Toko B", "6%"), encoding="utf-8")
        out = self.tmp / "hasil.csv"
        cur.main([str(self.tmp), "-o", str(out), "-n", "10", "--max-per-shop", "3"])
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        dapur = [r for r in rows if r["category"] == "Peralatan Dapur"]
        home = [r for r in rows if r["category"] == "Home & Living"]
        self.assertEqual(len(dapur), 10)
        self.assertTrue(all(r["name"] not in ("Chopper Rokok", "Chopper Murah", "Chopper Komisi Kecil") for r in dapur))
        shops = [r["shop_name"] for r in dapur]
        self.assertTrue(all(shops.count(s) <= 3 for s in shops), "maks per toko")
        self.assertEqual([r["name"] for r in home], ["Kotak Serbaguna"], "item_id 1 sudah dipakai -> duplikat dibuang")
        self.assertEqual(dapur[0]["price"], "50000")
        self.assertEqual(dapur[0]["commission_amount"], "1000")


if __name__ == "__main__":
    unittest.main()
