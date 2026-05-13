"""
Shopify Admin REST API client cho Shopify Skill.

Hỗ trợ:
  - Static access token (shpat_...)
  - OAuth client credentials (client_id + client_secret, tự refresh)

Retry với exponential backoff cho lỗi mạng, tự refresh token khi gặp 401.
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Union

import requests

logger = logging.getLogger(__name__)

_TRANSIENT = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

_TOKEN_REFRESH_BUFFER = 300  # làm mới trước 5 phút khi hết hạn


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

class _OAuthToken:
    """Quản lý OAuth client-credentials token với cache file."""

    def __init__(self, shop_domain: str, client_id: str, client_secret: str, cache_dir: Path) -> None:
        self._domain = shop_domain
        self._client_id = client_id
        self._client_secret = client_secret
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = cache_dir / f"token_{shop_domain.replace('.', '_')}.json"

    def get(self) -> str:
        cached = self._load()
        if cached and cached["expires_at"] > time.time() + _TOKEN_REFRESH_BUFFER:
            return cached["access_token"]
        return self._fetch()

    def refresh(self) -> str:
        return self._fetch()

    def _fetch(self) -> str:
        url = f"https://{self._domain}/admin/oauth/access_token"
        resp = requests.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Shopify OAuth thất bại HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        token = data.get("access_token", "")
        if not token:
            raise RuntimeError("Shopify OAuth: không có access_token trong response")
        expires_at = int(time.time()) + int(data.get("expires_in", 86399))
        payload = {"access_token": token, "expires_at": expires_at}
        self._cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._cache.chmod(0o600)
        return token

    def _load(self) -> Optional[dict]:
        try:
            if self._cache.is_file():
                d = json.loads(self._cache.read_text(encoding="utf-8"))
                if "access_token" in d and "expires_at" in d:
                    return d
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class ShopifyAPI:
    """
    Client gọi Shopify Admin REST API.

    Khởi tạo:
        # Static token
        api = ShopifyAPI("store.myshopify.com", access_token="shpat_...")

        # OAuth
        api = ShopifyAPI("store.myshopify.com",
                         client_id="...", client_secret="...")
    """

    def __init__(
        self,
        shop_domain: str,
        access_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        api_version: str = "2026-04",
        timeout: int = 15,
        max_retries: int = 3,
        cache_dir: Optional[Path] = None,
    ) -> None:
        self.shop_domain = shop_domain.strip().lower()
        self.base_url = f"https://{self.shop_domain}/admin/api/{api_version}"
        self.timeout = timeout
        self.max_retries = max_retries

        self._oauth: Optional[_OAuthToken] = None
        self._static_token = ""

        if client_id and client_secret:
            _cache = cache_dir or (Path(__file__).parent / "storage")
            self._oauth = _OAuthToken(self.shop_domain, client_id, client_secret, _cache)
            token = self._oauth.get()
        elif access_token:
            self._static_token = access_token
            token = access_token
        else:
            raise ValueError(
                f"Store '{shop_domain}': cần access_token hoặc client_id+client_secret"
            )

        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Shopify-Access-Token": token,
        })

    # -----------------------------------------------------------------------
    # Orders
    # -----------------------------------------------------------------------

    def list_orders(
        self,
        status: str = "any",
        limit: int = 50,
        since_days: int = 0,
        tag: str = "",
        financial_status: str = "",
        fulfillment_status: str = "",
    ) -> list:
        """
        Lấy danh sách đơn hàng.
        status: open | closed | cancelled | any
        financial_status: paid | pending | refunded | ...
        fulfillment_status: shipped | partial | unshipped | unfulfilled
        """
        params: dict = {"status": status, "limit": min(limit, 250)}
        if since_days > 0:
            since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            params["created_at_min"] = since
        if tag:
            params["tag"] = tag
        if financial_status:
            params["financial_status"] = financial_status
        if fulfillment_status:
            params["fulfillment_status"] = fulfillment_status
        return self._get("/orders.json", params)["orders"]

    def get_order(self, order_id: int) -> dict:
        """Lấy chi tiết một đơn hàng theo ID."""
        return self._get(f"/orders/{order_id}.json")["order"]

    def update_order(self, order_id: int, **fields) -> dict:
        """Cập nhật đơn hàng (tags, note, email, ...)."""
        return self._put(f"/orders/{order_id}.json", {"order": {"id": order_id, **fields}})["order"]

    def add_order_tag(self, order_id: int, tag: str) -> None:
        """Thêm tag vào đơn hàng (idempotent)."""
        order = self.get_order(order_id)
        existing = [t.strip() for t in order.get("tags", "").split(",") if t.strip()]
        if tag not in existing:
            existing.append(tag)
            self.update_order(order_id, tags=", ".join(existing))

    def remove_order_tag(self, order_id: int, tag: str) -> None:
        """Xoá tag khỏi đơn hàng."""
        order = self.get_order(order_id)
        existing = [t.strip() for t in order.get("tags", "").split(",") if t.strip()]
        new_tags = [t for t in existing if t != tag]
        if len(new_tags) != len(existing):
            self.update_order(order_id, tags=", ".join(new_tags))

    def cancel_order(self, order_id: int, reason: str = "customer", notify: bool = True) -> dict:
        """
        Huỷ đơn hàng.
        reason: customer | inventory | fraud | declined | other
        """
        return self._post(
            f"/orders/{order_id}/cancel.json",
            {"reason": reason, "email": notify},
        )["order"]

    def close_order(self, order_id: int) -> dict:
        """Đóng/lưu trữ đơn hàng."""
        return self._post(f"/orders/{order_id}/close.json")["order"]

    def reopen_order(self, order_id: int) -> dict:
        """Mở lại đơn hàng đã đóng."""
        return self._post(f"/orders/{order_id}/open.json")["order"]

    def get_fulfillment_orders(self, order_id: int) -> list:
        """Lấy fulfillment orders của một đơn hàng."""
        return self._get(f"/orders/{order_id}/fulfillment_orders.json")["fulfillment_orders"]

    def create_fulfillment(
        self,
        fulfillment_order_id: int,
        tracking_number: str = "",
        tracking_company: str = "",
        tracking_url: str = "",
        notify_customer: bool = True,
    ) -> dict:
        """Tạo fulfillment (giao hàng) cho một fulfillment_order_id."""
        payload: dict = {
            "fulfillment": {
                "line_items_by_fulfillment_order": [
                    {"fulfillment_order_id": fulfillment_order_id}
                ],
                "notify_customer": notify_customer,
            }
        }
        if tracking_number or tracking_company:
            tracking: dict = {}
            if tracking_number:
                tracking["number"] = tracking_number
            if tracking_company:
                tracking["company"] = tracking_company
            if tracking_url:
                tracking["url"] = tracking_url
            payload["fulfillment"]["tracking_info"] = tracking
        return self._post("/fulfillments.json", payload)["fulfillment"]

    def get_refunds(self, order_id: int) -> list:
        """Lấy danh sách hoàn tiền của đơn hàng."""
        return self._get(f"/orders/{order_id}/refunds.json")["refunds"]

    # -----------------------------------------------------------------------
    # Customers
    # -----------------------------------------------------------------------

    def list_customers(self, limit: int = 50, since_days: int = 0) -> list:
        """Lấy danh sách khách hàng gần đây."""
        params: dict = {"limit": min(limit, 250)}
        if since_days > 0:
            since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            params["created_at_min"] = since
        return self._get("/customers.json", params)["customers"]

    def get_customer(self, customer_id: int) -> dict:
        """Lấy chi tiết một khách hàng theo ID."""
        return self._get(f"/customers/{customer_id}.json")["customer"]

    def search_customers(self, query: str, limit: int = 50) -> list:
        """
        Tìm kiếm khách hàng.
        Ví dụ query: "email:nguyenvan@gmail.com", "phone:0912345678",
                     "first_name:Minh", "tag:VIP"
        """
        return self._get(
            "/customers/search.json",
            {"query": query, "limit": min(limit, 250)},
        )["customers"]

    def update_customer(self, customer_id: int, **fields) -> dict:
        """Cập nhật thông tin khách hàng (note, tags, email, phone, ...)."""
        return self._put(
            f"/customers/{customer_id}.json",
            {"customer": {"id": customer_id, **fields}},
        )["customer"]

    def add_customer_tag(self, customer_id: int, tag: str) -> None:
        """Thêm tag vào khách hàng (idempotent)."""
        customer = self.get_customer(customer_id)
        existing = [t.strip() for t in customer.get("tags", "").split(",") if t.strip()]
        if tag not in existing:
            existing.append(tag)
            self.update_customer(customer_id, tags=", ".join(existing))

    def remove_customer_tag(self, customer_id: int, tag: str) -> None:
        """Xoá tag khỏi khách hàng."""
        customer = self.get_customer(customer_id)
        existing = [t.strip() for t in customer.get("tags", "").split(",") if t.strip()]
        new_tags = [t for t in existing if t != tag]
        if len(new_tags) != len(existing):
            self.update_customer(customer_id, tags=", ".join(new_tags))

    def get_customer_orders(self, customer_id: int, limit: int = 10) -> list:
        """Lấy lịch sử đơn hàng của một khách hàng."""
        return self._get(
            f"/customers/{customer_id}/orders.json",
            {"limit": min(limit, 250), "status": "any"},
        )["orders"]

    # -----------------------------------------------------------------------
    # Products
    # -----------------------------------------------------------------------

    def list_products(
        self,
        limit: int = 50,
        title: str = "",
        status: str = "active",
        vendor: str = "",
        product_type: str = "",
    ) -> list:
        """
        Lấy danh sách sản phẩm.
        status: active | draft | archived
        """
        params: dict = {"limit": min(limit, 250), "status": status}
        if title:
            params["title"] = title
        if vendor:
            params["vendor"] = vendor
        if product_type:
            params["product_type"] = product_type
        return self._get("/products.json", params)["products"]

    def get_product(self, product_id: int) -> dict:
        """Lấy chi tiết sản phẩm (gồm variants và options)."""
        return self._get(f"/products/{product_id}.json")["product"]

    def update_product(self, product_id: int, **fields) -> dict:
        """Cập nhật sản phẩm (title, body_html, status, tags, vendor, ...)."""
        return self._put(
            f"/products/{product_id}.json",
            {"product": {"id": product_id, **fields}},
        )["product"]

    def update_variant_price(self, variant_id: int, price: str) -> dict:
        """Cập nhật giá của một variant."""
        return self._put(
            f"/variants/{variant_id}.json",
            {"variant": {"id": variant_id, "price": price}},
        )["variant"]

    # -----------------------------------------------------------------------
    # Inventory
    # -----------------------------------------------------------------------

    def get_locations(self) -> list:
        """Lấy tất cả địa điểm kho hàng."""
        return self._get("/locations.json")["locations"]

    def get_inventory_levels(self, inventory_item_id: int) -> list:
        """Lấy mức tồn kho của một item trên tất cả location."""
        return self._get(
            "/inventory_levels.json",
            {"inventory_item_ids": inventory_item_id},
        )["inventory_levels"]

    def set_inventory_level(
        self, location_id: int, inventory_item_id: int, available: int
    ) -> dict:
        """Đặt số lượng tồn kho tuyệt đối tại một location."""
        return self._post(
            "/inventory_levels/set.json",
            {
                "location_id": location_id,
                "inventory_item_id": inventory_item_id,
                "available": available,
            },
        )["inventory_level"]

    def adjust_inventory_level(
        self, location_id: int, inventory_item_id: int, adjustment: int
    ) -> dict:
        """Điều chỉnh tồn kho tương đối (+ để tăng, - để giảm)."""
        return self._post(
            "/inventory_levels/adjust.json",
            {
                "location_id": location_id,
                "inventory_item_id": inventory_item_id,
                "available_adjustment": adjustment,
            },
        )["inventory_level"]

    # -----------------------------------------------------------------------
    # Internal HTTP helpers
    # -----------------------------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: Optional[dict] = None) -> dict:
        return self._request("POST", path, body=body)

    def _put(self, path: str, body: Optional[dict] = None) -> dict:
        return self._request("PUT", path, body=body)

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        params: Optional[dict] = None,
        _token_refreshed: bool = False,
    ) -> dict:
        url = self.base_url + path
        delay = 2

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.request(
                    method, url,
                    json=body,
                    params=params,
                    timeout=self.timeout,
                )

                if resp.status_code == 401 and self._oauth and not _token_refreshed:
                    logger.warning("401 — refreshing OAuth token")
                    self._session.headers["X-Shopify-Access-Token"] = self._oauth.refresh()
                    return self._request(method, path, body, params, _token_refreshed=True)

                # Rate limiting
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", delay))
                    logger.warning("Rate limited — chờ %.1fs", retry_after)
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()
                return resp.json() if resp.content else {}

            except _TRANSIENT as e:
                if attempt == self.max_retries:
                    raise
                logger.warning("Transient error (attempt %d/%d), retry in %ds: %s", attempt, self.max_retries, delay, e)
                time.sleep(delay)
                delay *= 2

            except requests.exceptions.HTTPError as e:
                logger.error("HTTP error: %s", e)
                raise

        raise RuntimeError(f"Shopify request thất bại: {method} {path}")
