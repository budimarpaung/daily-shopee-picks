"""End-to-end test against a local mock of the Shopee Affiliate Open API.

Run:  python -m unittest discover -s tests -v
"""
import hashlib
import json
import os
import random
import re
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_daily_picks as gen  # noqa: E402
import shopee_api  # noqa: E402

APP_ID, SECRET = "123456", "test-secret"


def fake_nodes(seed, n=30):
    rnd = random.Random(seed)
    nodes = []
    for i in range(n):
        item = rnd.randint(1, 60)  # overlap between queries -> exercises dedupe
        price = rnd.choice([15000, 35000, 59000, 89000, 149000, 320000, 750000])
        rate = rnd.choice(["0.03", "0.05", "0.08", "0.1", "0.12"])
        nodes.append({
            "itemId": 1000 + item, "productName": f"Produk {item}", "commissionRate": rate,
            "sellerCommissionRate": "0.05", "shopeeCommissionRate": "0.03",
            "commission": str(int(price * float(rate))), "sales": rnd.randint(10, 20000),
            "priceMin": str(price), "priceMax": str(price), "priceDiscountRate": rnd.choice([0, 10, 25]),
            "ratingStar": rnd.choice(["4.3", "4.6", "4.8", "4.9"]), "imageUrl": "https://cf.shopee.co.id/file/x",
            "shopId": 500 + item % 7, "shopName": f"Toko {item % 7}", "shopType": [1], "productCatIds": [100],
            "productLink": f"https://shopee.co.id/product/{500 + item % 7}/{1000 + item}",
            "offerLink": f"https://s.shopee.co.id/aff{item}", "periodStartTime": 0, "periodEndTime": 1893456000,
        })
    return nodes


class MockHandler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        auth = self.headers.get("Authorization", "")
        m = re.match(r"SHA256 Credential=(\w+), Timestamp=(\d+), Signature=([0-9a-f]{64})$", auth)
        expected = m and hashlib.sha256(f"{m[1]}{m[2]}{body}{SECRET}".encode()).hexdigest()
        if not m or m[3] != expected:
            payload = {"errors": [{"message": "Invalid Signature", "extensions": {"code": 10020}}]}
        else:
            q = json.loads(body)["query"]
            MockHandler.calls.append(q)
            page = int(re.search(r"page: (\d+)", q)[1])
            payload = {"data": {"productOfferV2": {
                "nodes": fake_nodes(hash(q) % 1000), "pageInfo": {"page": page, "limit": 30, "hasNextPage": page < 2}}}}
        out = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), MockHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        os.environ.update({
            "SHOPEE_APP_ID": APP_ID, "SHOPEE_APP_SECRET": SECRET,
            "SHOPEE_API_ENDPOINT": f"http://127.0.0.1:{cls.server.server_port}/graphql",
            "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1",
        })

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        gen.OUTPUT_PATH = self.tmp / "products.json"
        gen.HISTORY_DIR = self.tmp / "history"
        gen.SNAPSHOT_PATH = gen.HISTORY_DIR / "sales_snapshot.json"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_signature_format(self):
        h = shopee_api.build_authorization("1", "s", '{"query":"x"}', 1577836800)
        sig = hashlib.sha256(b'11577836800{"query":"x"}s').hexdigest()
        self.assertEqual(h, f"SHA256 Credential=1, Timestamp=1577836800, Signature={sig}")

    def test_bad_secret_raises(self):
        c = shopee_api.ShopeeAffiliateClient(APP_ID, "wrong", endpoint=os.environ["SHOPEE_API_ENDPOINT"], min_interval=0)
        with self.assertRaises(shopee_api.ShopeeAPIError):
            c.product_offers(keyword="x")

    def test_full_run_and_rotation(self):
        cfg = gen.load_config()
        cfg["queries"] = cfg["queries"][:5]
        client_cls = shopee_api.ShopeeAffiliateClient
        orig = client_cls.from_env
        client_cls.from_env = classmethod(lambda cls: client_cls(
            APP_ID, SECRET, endpoint=os.environ["SHOPEE_API_ENDPOINT"], min_interval=0))
        try:
            raw, warnings = gen.fetch_from_api(cfg)
        finally:
            client_cls.from_env = orig
        self.assertFalse(warnings)
        self.assertTrue(raw)
        self.assertTrue(all(p["commission_rate"] >= 1 for p in raw), "rate should be converted to percent")

        d1 = date(2026, 11, 16)
        picks1, n = gen.rank(raw, cfg, d1)
        self.assertLessEqual(len(picks1), cfg["top_n"])
        keys = [gen.product_key(p) for p in picks1]
        self.assertEqual(len(keys), len(set(keys)), "no duplicates")
        for p in picks1:
            f = cfg["filters"]
            self.assertGreaterEqual(p["rating"], f["min_rating"])
            self.assertLessEqual(p["price"], f["max_price"])
            self.assertTrue(p["affiliate_url"].startswith("https://s.shopee.co.id/"))
        gen.save_history(raw, picks1, d1)

        # Next day: sales grew for everything -> momentum known; yesterday's picks penalised
        for p in raw:
            p["sales"] *= 1.05
        picks2, _ = gen.rank([dict(p) for p in raw], cfg, d1 + timedelta(days=1))
        self.assertTrue(all(p["sales_growth_pct"] is not None for p in picks2))
        self.assertTrue(any(p["is_new"] for p in picks2) or len(picks2) == n)


    def test_csv_from_url_and_fallback(self):
        csv_text = "name,category,price,commission_rate,sales,rating\nSheet A,Dapur,50000,8,900,4.8\nSheet B,Rumah,30000,5,400,4.6\n"

        class CsvHandler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = csv_text.encode() if self.path == "/ok.csv" else b"<html>login</html>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = HTTPServer(("127.0.0.1", 0), CsvHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"
        try:
            os.environ[gen.CSV_URL_ENV] = base + "/ok.csv"
            products, origin, warnings = gen.fetch_from_csv()
            self.assertEqual(origin, "sheet")
            self.assertEqual([p["name"] for p in products], ["Sheet A", "Sheet B"])
            self.assertFalse(warnings)

            os.environ[gen.CSV_URL_ENV] = base + "/not-published"
            products, origin, warnings = gen.fetch_from_csv()
            self.assertEqual(origin, "csv")
            self.assertTrue(products)
            self.assertIn("HTML", warnings[0])
        finally:
            os.environ.pop(gen.CSV_URL_ENV, None)
            srv.shutdown()

    def test_freshness_rotates_daily(self):
        cfg = gen.load_config()
        cfg["top_n"], cfg["max_per_category"], cfg["max_per_shop"] = 3, 10, 10
        pool = [{"id": str(i), "name": f"P{i}", "category": "X", "price": 50000, "commission_rate": 8,
                 "commission_amount": None, "sales": 1000 - i * 10, "rating": 4.8, "source": "csv"}
                for i in range(12)]
        d = date(2026, 11, 20)
        seen_days = []
        for k in range(3):
            picks, _ = gen.rank([dict(p) for p in pool], cfg, d + timedelta(days=k), strict_filters=False)
            gen.save_history(pool, picks, d + timedelta(days=k))
            seen_days.append({p["name"] for p in picks})
        self.assertNotEqual(seen_days[0], seen_days[1], "picks should change the next day")

if __name__ == "__main__":
    unittest.main()
