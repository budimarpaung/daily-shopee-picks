"""Minimal client for the official Shopee Affiliate Open API (GraphQL).

Only uses the Python standard library so it runs on GitHub Actions without
installing anything.

Credentials are read from environment variables:
  SHOPEE_APP_ID      -> App ID from affiliate.shopee.co.id > Open API
  SHOPEE_APP_SECRET  -> Secret/API key from the same page

Authentication (per Shopee docs):
  Authorization: SHA256 Credential={AppId}, Timestamp={ts}, Signature={sig}
  sig = sha256_hex(AppId + Timestamp + RequestBody + Secret)
The body used for the signature MUST be byte-identical to the body sent,
so we serialize once and send that exact string.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://open-api.affiliate.shopee.co.id/graphql"

PRODUCT_FIELDS = """
  itemId
  productName
  commissionRate
  sellerCommissionRate
  shopeeCommissionRate
  commission
  sales
  priceMin
  priceMax
  priceDiscountRate
  ratingStar
  imageUrl
  shopId
  shopName
  shopType
  productCatIds
  productLink
  offerLink
  periodStartTime
  periodEndTime
"""

def _gql_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(int(v))
    return json.dumps(str(v), ensure_ascii=False)


def build_product_offer_query(**args) -> str:
    """Build productOfferV2 query with inline arguments (as in Shopee's examples)."""
    arg_str = ", ".join(f"{k}: {_gql_value(v)}" for k, v in args.items() if v is not None)
    return "{ productOfferV2(%s) { nodes { %s } pageInfo { page limit hasNextPage } } }" % (
        arg_str, " ".join(PRODUCT_FIELDS.split()))

# sortType values documented by Shopee
SORT_RELEVANCE = 1
SORT_ITEM_SOLD_DESC = 2
SORT_PRICE_DESC = 3
SORT_PRICE_ASC = 4
SORT_COMMISSION_DESC = 5

# listType values documented by Shopee
LIST_ALL = 0
LIST_TOP_PERFORMING = 2


class ShopeeAPIError(RuntimeError):
    pass


def build_authorization(app_id: str, secret: str, body: str, timestamp: int) -> str:
    raw = f"{app_id}{timestamp}{body}{secret}"
    signature = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}"


class ShopeeAffiliateClient:
    def __init__(self, app_id: str, secret: str, endpoint: str = DEFAULT_ENDPOINT,
                 timeout: int = 20, max_retries: int = 3, min_interval: float = 0.6):
        if not app_id or not secret:
            raise ShopeeAPIError("SHOPEE_APP_ID / SHOPEE_APP_SECRET belum diisi.")
        self.app_id = str(app_id).strip()
        self.secret = str(secret).strip()
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval
        self._last_call = 0.0

    @classmethod
    def from_env(cls) -> "ShopeeAffiliateClient":
        return cls(
            os.environ.get("SHOPEE_APP_ID", ""),
            os.environ.get("SHOPEE_APP_SECRET", ""),
            endpoint=os.environ.get("SHOPEE_API_ENDPOINT", DEFAULT_ENDPOINT),
        )

    # ------------------------------------------------------------------ core
    def _throttle(self):
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def execute(self, query: str) -> dict:
        payload = {"query": query}
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            ts = int(time.time())
            req = urllib.request.Request(
                self.endpoint,
                data=body.encode("utf-8"),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": build_authorization(self.app_id, self.secret, body, ts),
                    "User-Agent": "daily-shopee-picks/2.0",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                last_error = ShopeeAPIError(f"HTTP {e.code}: {e.read()[:300]!r}")
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                raise last_error
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last_error = ShopeeAPIError(f"Gagal menghubungi Shopee API: {e}")
                time.sleep(2 ** attempt)
                continue

            errors = data.get("errors")
            if errors:
                msg = "; ".join(
                    f"{(err.get('extensions') or {}).get('code', '?')}: {err.get('message', '')}" for err in errors
                )
                # 10030 = rate limit -> back off and retry
                if any((err.get("extensions") or {}).get("code") == 10030 for err in errors):
                    last_error = ShopeeAPIError(f"Rate limit: {msg}")
                    time.sleep(5 * attempt)
                    continue
                raise ShopeeAPIError(msg)
            return data.get("data") or {}
        raise last_error or ShopeeAPIError("Gagal memanggil Shopee API.")

    # --------------------------------------------------------------- helpers
    def product_offers(self, *, keyword=None, list_type=None, match_id=None, product_cat_id=None,
                       sort_type=SORT_ITEM_SOLD_DESC, limit=50, pages=1,
                       is_ams_offer=None, is_key_seller=None) -> list[dict]:
        """Return product offer nodes across `pages` pages."""
        results: list[dict] = []
        for page in range(1, max(1, pages) + 1):
            data = self.execute(build_product_offer_query(
                keyword=keyword,
                listType=list_type,
                matchId=match_id,
                productCatId=product_cat_id,
                sortType=sort_type,
                page=page,
                limit=limit,
                isAMSOffer=is_ams_offer,
                isKeySeller=is_key_seller,
            ))
            conn = data.get("productOfferV2") or {}
            results.extend(conn.get("nodes") or [])
            if not (conn.get("pageInfo") or {}).get("hasNextPage"):
                break
        return results
