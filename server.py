"""
iMat Shopify Skill — MCP Server

Cung cấp tools để theo dõi và quản lý Shopify trực tiếp từ Claude Code / OpenClaw:

  Orders (đơn hàng):
    • shopify_list_orders       — danh sách / lọc đơn hàng
    • shopify_get_order         — chi tiết một đơn hàng
    • shopify_update_order      — thêm tag, ghi chú, cập nhật đơn
    • shopify_cancel_order      — huỷ đơn hàng
    • shopify_fulfill_order     — xác nhận giao hàng (kèm tracking)

  Customers (khách hàng):
    • shopify_list_customers    — danh sách / tìm kiếm khách hàng
    • shopify_get_customer      — chi tiết một khách hàng
    • shopify_update_customer   — ghi chú, tag khách hàng

  Products (sản phẩm):
    • shopify_list_products     — danh sách / tìm kiếm sản phẩm
    • shopify_get_product       — chi tiết sản phẩm và variants
    • shopify_update_inventory  — cập nhật số lượng tồn kho

Cấu hình: xem .env.example và README.md

Thêm vào Claude Code / OpenClaw:
  {
    "mcpServers": {
      "shopify-mcp": {
        "command": "/path/to/venv/bin/python",
        "args": ["server.py"],
        "cwd": "/path/to/shopify-mcp"
      }
    }
  }
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from shopify_api import ShopifyAPI

# ---------------------------------------------------------------------------
# Logging — im lặng, dùng stderr để không xung đột MCP stdout protocol
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("shopify-mcp")

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------

def _load_env(env_file: Path) -> None:
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key not in os.environ:
            os.environ[key] = val

_load_env(Path(__file__).parent / ".env")

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()

def _require(key: str) -> str:
    v = _env(key)
    if not v:
        raise RuntimeError(f"Thiếu biến môi trường '{key}' trong .env")
    return v

# ---------------------------------------------------------------------------
# Shopify client — hỗ trợ nhiều store qua SHOPIFY_STORES JSON
# ---------------------------------------------------------------------------
# Cấu hình qua .env:
#
#   Một store (đơn giản nhất):
#     SHOPIFY_SHOP_DOMAIN=store.myshopify.com
#     SHOPIFY_ACCESS_TOKEN=shpat_...        (static token)
#     hoặc
#     SHOPIFY_CLIENT_ID=...
#     SHOPIFY_CLIENT_SECRET=...
#
#   Nhiều store (JSON array):
#     SHOPIFY_STORES=[{"shop_domain":"a.myshopify.com","access_token":"shpat_..."},...]
# ---------------------------------------------------------------------------

_API_VERSION = _env("SHOPIFY_API_VERSION", "2026-04")
_CACHE_DIR = Path(__file__).parent / "storage"

def _build_stores() -> dict[str, ShopifyAPI]:
    """Trả về dict: shop_domain → ShopifyAPI instance."""
    stores: dict[str, ShopifyAPI] = {}

    stores_json = _env("SHOPIFY_STORES")
    if stores_json:
        try:
            entries = json.loads(stores_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"SHOPIFY_STORES JSON không hợp lệ: {e}") from e
        for entry in entries:
            domain = entry.get("shop_domain", "").strip().lower()
            if not domain:
                continue
            stores[domain] = ShopifyAPI(
                shop_domain=domain,
                access_token=entry.get("access_token", ""),
                client_id=entry.get("client_id", ""),
                client_secret=entry.get("client_secret", ""),
                api_version=_API_VERSION,
                cache_dir=_CACHE_DIR,
            )
    else:
        domain = _env("SHOPIFY_SHOP_DOMAIN")
        if domain:
            domain = domain.lower()
            stores[domain] = ShopifyAPI(
                shop_domain=domain,
                access_token=_env("SHOPIFY_ACCESS_TOKEN"),
                client_id=_env("SHOPIFY_CLIENT_ID"),
                client_secret=_env("SHOPIFY_CLIENT_SECRET"),
                api_version=_API_VERSION,
                cache_dir=_CACHE_DIR,
            )

    if not stores:
        raise RuntimeError(
            "Chưa cấu hình Shopify store. "
            "Thêm SHOPIFY_SHOP_DOMAIN + SHOPIFY_ACCESS_TOKEN vào .env"
        )
    return stores

try:
    _stores = _build_stores()
except Exception as _e:
    logger.error("Lỗi khởi tạo Shopify: %s", _e)
    _stores = {}

def _get_client(shop: str = "") -> tuple[ShopifyAPI, str]:
    """
    Resolve shop domain → ShopifyAPI.
    Nếu shop trống, trả về store đầu tiên.
    """
    if not _stores:
        raise RuntimeError(
            "Chưa cấu hình Shopify. Kiểm tra file .env và khởi động lại MCP server."
        )

    domains = list(_stores.keys())

    if not shop:
        return _stores[domains[0]], domains[0]

    shop_lower = shop.strip().lower()
    # Khớp chính xác trước
    if shop_lower in _stores:
        return _stores[shop_lower], shop_lower
    # Khớp một phần (store prefix)
    matched = [d for d in domains if shop_lower in d]
    if len(matched) == 1:
        return _stores[matched[0]], matched[0]
    if len(matched) > 1:
        raise ValueError(
            f"Tên store '{shop}' khớp nhiều kết quả: {', '.join(matched)}. "
            "Hãy nhập domain đầy đủ."
        )
    raise ValueError(
        f"Không tìm thấy store '{shop}'. "
        f"Các store đã cấu hình: {', '.join(domains)}"
    )


def _list_stores() -> str:
    if not _stores:
        return "Chưa cấu hình store nào."
    return "\n".join(f"  • {d}" for d in _stores)

# ---------------------------------------------------------------------------
# FastMCP setup
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="iMat Shopify Skill",
    instructions=(
        "Quản lý Shopify: theo dõi đơn hàng, khách hàng, sản phẩm và tồn kho. "
        "Hỗ trợ multi-store — dùng tham số 'shop' để chọn store khi có nhiều hơn 1. "
        "Để xem danh sách stores đã cấu hình, gọi shopify_list_orders với shop trống."
    ),
)

# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def _vnd(amount: str) -> str:
    try:
        return f"{float(amount):,.0f}đ"
    except (ValueError, TypeError):
        return str(amount)

def _date(dt: str) -> str:
    return dt[:10] if dt else ""

def _tags(t: str) -> str:
    return t if t else "(không có)"

def _fmt_order(o: dict, detail: bool = False) -> str:
    cust = o.get("customer") or {}
    name = f"{cust.get('first_name','')} {cust.get('last_name','')}".strip() or "(khách vãng lai)"
    ship = o.get("shipping_address") or {}
    phone = ship.get("phone") or cust.get("phone") or ""
    lines = [
        f"Đơn #{o['order_number']}  |  {_date(o.get('created_at',''))}",
        f"  Khách   : {name}  {phone}",
        f"  Tổng    : {_vnd(o.get('total_price','0'))}  ({o.get('financial_status','')}/{o.get('fulfillment_status') or 'unfulfilled'})",
        f"  Trạng   : {o.get('cancel_reason') and 'Đã huỷ - ' + o['cancel_reason'] or o.get('status','open')}",
        f"  Tags    : {_tags(o.get('tags',''))}",
    ]
    if detail:
        lines.append(f"  Ghi chú : {o.get('note') or '(trống)'}")
        lines.append(f"  ID      : {o['id']}")
        items = o.get("line_items", [])
        if items:
            lines.append("  Sản phẩm:")
            for it in items:
                lines.append(
                    f"    - {it['title']} x{it['quantity']}  "
                    f"{_vnd(it.get('price','0'))}/cái  [variant_id={it.get('variant_id')}]"
                )
        fulfillments = o.get("fulfillments", [])
        if fulfillments:
            lines.append("  Giao hàng:")
            for f in fulfillments:
                track = f.get("tracking_number") or ""
                lines.append(
                    f"    - {f.get('status','')}  {f.get('tracking_company','')}  {track}"
                )
    return "\n".join(lines)


def _fmt_customer(c: dict, detail: bool = False) -> str:
    name = f"{c.get('first_name','')} {c.get('last_name','')}".strip() or "(chưa có tên)"
    lines = [
        f"👤 {name}  (ID: {c['id']})",
        f"   Email   : {c.get('email') or '(trống)'}",
        f"   Phone   : {c.get('phone') or '(trống)'}",
        f"   Đơn     : {c.get('orders_count',0)} đơn  |  Chi tiêu: {_vnd(c.get('total_spent','0'))}",
        f"   Tags    : {_tags(c.get('tags',''))}",
    ]
    if detail:
        lines.append(f"   Ghi chú : {c.get('note') or '(trống)'}")
        lines.append(f"   Tham gia: {_date(c.get('created_at',''))}")
        addr = c.get("default_address") or {}
        if addr:
            lines.append(
                f"   Địa chỉ : {addr.get('address1','')} {addr.get('city','')} {addr.get('province','')}"
            )
    return "\n".join(lines)


def _fmt_product(p: dict, detail: bool = False) -> str:
    lines = [
        f"📦 {p['title']}  (ID: {p['id']})",
        f"   Vendor  : {p.get('vendor') or '(trống)'}",
        f"   Loại    : {p.get('product_type') or '(trống)'}",
        f"   Tags    : {_tags(p.get('tags',''))}",
        f"   Status  : {p.get('status','active')}",
    ]
    variants = p.get("variants", [])
    if detail and variants:
        lines.append(f"   Variants ({len(variants)}):")
        for v in variants:
            inv = v.get("inventory_quantity", "?")
            lines.append(
                f"    - {v.get('title','Default')}  "
                f"Giá: {_vnd(v.get('price','0'))}  "
                f"Tồn: {inv}  "
                f"[variant_id={v['id']}  inv_item={v.get('inventory_item_id')}]"
            )
    elif variants:
        prices = sorted({v.get("price", "0") for v in variants})
        inv_total = sum(v.get("inventory_quantity", 0) or 0 for v in variants)
        lines.append(f"   Giá     : {' – '.join(_vnd(p) for p in prices)}")
        lines.append(f"   Tồn kho : {inv_total} (tất cả variants)")
    return "\n".join(lines)


def _error(e: Exception) -> str:
    msg = str(e)
    if "401" in msg:
        return f"❌ Lỗi xác thực Shopify (401). Kiểm tra access_token hoặc client credentials trong .env.\n{msg}"
    if "403" in msg:
        return f"❌ Không có quyền (403). Kiểm tra API scopes của Shopify App.\n{msg}"
    if "404" in msg:
        return f"❌ Không tìm thấy (404). ID không tồn tại hoặc sai store.\n{msg}"
    return f"❌ Lỗi: {msg}"


# ---------------------------------------------------------------------------
# Tools — Orders
# ---------------------------------------------------------------------------

@mcp.tool()
def shopify_list_orders(
    status: str = "open",
    limit: int = 20,
    since_days: int = 0,
    tag: str = "",
    financial_status: str = "",
    fulfillment_status: str = "",
    shop: str = "",
) -> str:
    """
    Lấy danh sách đơn hàng Shopify.

    Args:
        status:             Trạng thái đơn: open | closed | cancelled | any (mặc định: open)
        limit:              Số đơn tối đa trả về (mặc định 20, tối đa 250)
        since_days:         Chỉ lấy đơn trong N ngày gần nhất (0 = không giới hạn)
        tag:                Lọc theo tag Shopify (VD: "SMSend", "VIP")
        financial_status:   Lọc theo thanh toán: paid | pending | refunded | voided | ...
        fulfillment_status: Lọc theo giao hàng: shipped | unshipped | partial | unfulfilled
        shop:               Domain store (để trống nếu chỉ có 1 store)

    Returns:
        Danh sách đơn hàng tóm tắt.
    """
    try:
        client, domain = _get_client(shop)
    except (ValueError, RuntimeError) as e:
        return _error(e)

    try:
        orders = client.list_orders(
            status=status,
            limit=limit,
            since_days=since_days,
            tag=tag,
            financial_status=financial_status,
            fulfillment_status=fulfillment_status,
        )
    except Exception as e:
        return _error(e)

    if not orders:
        return f"Không có đơn hàng nào với bộ lọc đã chọn.\nStore: {domain}"

    header = f"Shopify [{domain}] — {len(orders)} đơn hàng (status={status})\n"
    body = "\n\n".join(_fmt_order(o) for o in orders)
    return header + body


@mcp.tool()
def shopify_get_order(order_id: int, shop: str = "") -> str:
    """
    Xem chi tiết một đơn hàng Shopify.

    Args:
        order_id: ID đơn hàng Shopify (số nguyên dài, không phải order_number).
                  Lấy từ URL: /admin/orders/{order_id} hoặc từ shopify_list_orders.
        shop:     Domain store (để trống nếu chỉ có 1 store)

    Returns:
        Chi tiết đầy đủ: khách hàng, sản phẩm, tags, ghi chú, fulfillment, hoàn tiền.
    """
    try:
        client, domain = _get_client(shop)
    except (ValueError, RuntimeError) as e:
        return _error(e)

    try:
        order = client.get_order(order_id)
    except Exception as e:
        return _error(e)

    lines = [f"Shopify [{domain}]\n", _fmt_order(order, detail=True)]

    refunds = order.get("refunds", [])
    if refunds:
        lines.append(f"\nHoàn tiền ({len(refunds)}):")
        for r in refunds:
            lines.append(f"  - {_date(r.get('created_at',''))}  {r.get('note','')}")

    return "\n".join(lines)


@mcp.tool()
def shopify_update_order(
    order_id: int,
    add_tag: str = "",
    remove_tag: str = "",
    note: str = "",
    shop: str = "",
) -> str:
    """
    Cập nhật đơn hàng: thêm/xoá tag và/hoặc ghi chú.

    Args:
        order_id:   ID đơn hàng Shopify.
        add_tag:    Tag cần thêm vào đơn hàng (VD: "VIP", "priority").
        remove_tag: Tag cần xoá khỏi đơn hàng.
        note:       Ghi chú mới ghi đè lên ghi chú cũ (để trống = không thay đổi).
        shop:       Domain store (để trống nếu chỉ có 1 store)

    Returns:
        Kết quả cập nhật.
    """
    if not add_tag and not remove_tag and not note:
        return "❌ Cần ít nhất một trong: add_tag, remove_tag, note."

    try:
        client, domain = _get_client(shop)
    except (ValueError, RuntimeError) as e:
        return _error(e)

    results = []
    try:
        if add_tag:
            client.add_order_tag(order_id, add_tag)
            results.append(f"✅ Đã thêm tag '{add_tag}'")
        if remove_tag:
            client.remove_order_tag(order_id, remove_tag)
            results.append(f"✅ Đã xoá tag '{remove_tag}'")
        if note:
            client.update_order(order_id, note=note)
            results.append(f"✅ Đã cập nhật ghi chú")

        order = client.get_order(order_id)
        results.append(f"\nTags hiện tại: {_tags(order.get('tags',''))}")
        results.append(f"Ghi chú      : {order.get('note') or '(trống)'}")
    except Exception as e:
        return _error(e)

    return f"Đơn #{order_id} [{domain}]\n" + "\n".join(results)


@mcp.tool()
def shopify_cancel_order(
    order_id: int,
    reason: str = "customer",
    notify_customer: bool = True,
    shop: str = "",
) -> str:
    """
    Huỷ đơn hàng Shopify.

    Args:
        order_id:        ID đơn hàng Shopify.
        reason:          Lý do huỷ: customer | inventory | fraud | declined | other
        notify_customer: Gửi email thông báo cho khách hàng (mặc định: True)
        shop:            Domain store (để trống nếu chỉ có 1 store)

    Returns:
        Kết quả huỷ đơn.
    """
    valid_reasons = {"customer", "inventory", "fraud", "declined", "other"}
    if reason not in valid_reasons:
        return f"❌ reason không hợp lệ: '{reason}'. Chọn một trong: {', '.join(sorted(valid_reasons))}"

    try:
        client, domain = _get_client(shop)
    except (ValueError, RuntimeError) as e:
        return _error(e)

    try:
        order = client.cancel_order(order_id, reason=reason, notify=notify_customer)
    except Exception as e:
        return _error(e)

    return (
        f"✅ Đã huỷ đơn #{order.get('order_number', order_id)} [{domain}]\n"
        f"   Lý do       : {reason}\n"
        f"   Cancel lúc  : {_date(order.get('cancelled_at',''))}\n"
        f"   Hoàn tiền   : {order.get('financial_status','')}"
    )


@mcp.tool()
def shopify_fulfill_order(
    order_id: int,
    tracking_number: str = "",
    tracking_company: str = "",
    tracking_url: str = "",
    notify_customer: bool = True,
    shop: str = "",
) -> str:
    """
    Xác nhận giao hàng cho đơn hàng (tạo fulfillment).

    Quy trình: tự động lấy fulfillment_order_id từ đơn → tạo fulfillment.
    Nếu đơn có nhiều fulfillment orders chờ xử lý, sẽ fulfill từng cái một.

    Args:
        order_id:        ID đơn hàng Shopify.
        tracking_number: Mã vận đơn (tuỳ chọn).
        tracking_company: Tên đơn vị vận chuyển (VD: "GHN", "GHTK", "J&T").
        tracking_url:    Link tra cứu vận đơn (tuỳ chọn).
        notify_customer: Gửi email thông báo giao hàng cho khách (mặc định: True).
        shop:            Domain store (để trống nếu chỉ có 1 store)

    Returns:
        Kết quả tạo fulfillment.
    """
    try:
        client, domain = _get_client(shop)
    except (ValueError, RuntimeError) as e:
        return _error(e)

    try:
        fulfillment_orders = client.get_fulfillment_orders(order_id)
    except Exception as e:
        return _error(e)

    pending = [
        fo for fo in fulfillment_orders
        if fo.get("status") in ("open", "in_progress")
    ]

    if not pending:
        statuses = ", ".join(fo.get("status", "?") for fo in fulfillment_orders)
        return (
            f"⚠️  Không có fulfillment order nào ở trạng thái chờ xử lý.\n"
            f"   Trạng thái hiện tại: {statuses or 'không có fulfillment order'}"
        )

    results = []
    for fo in pending:
        fo_id = fo["id"]
        try:
            fulfillment = client.create_fulfillment(
                fulfillment_order_id=fo_id,
                tracking_number=tracking_number,
                tracking_company=tracking_company,
                tracking_url=tracking_url,
                notify_customer=notify_customer,
            )
            results.append(
                f"  ✅ Fulfillment #{fo_id} → {fulfillment.get('status','?')}"
            )
        except Exception as e:
            results.append(f"  ❌ Fulfillment #{fo_id} thất bại: {e}")

    order = client.get_order(order_id)
    return (
        f"Đơn #{order.get('order_number', order_id)} [{domain}]\n"
        + "\n".join(results)
        + f"\n\nFulfillment status: {order.get('fulfillment_status') or 'unfulfilled'}"
        + (f"\nTracking: {tracking_company} {tracking_number}" if tracking_number else "")
    )


# ---------------------------------------------------------------------------
# Tools — Customers
# ---------------------------------------------------------------------------

@mcp.tool()
def shopify_list_customers(
    query: str = "",
    limit: int = 20,
    since_days: int = 0,
    shop: str = "",
) -> str:
    """
    Tìm kiếm hoặc lấy danh sách khách hàng Shopify.

    Args:
        query:      Từ khoá tìm kiếm. Ví dụ:
                    - "email:nguyenvan@gmail.com"
                    - "phone:0912345678"
                    - "Nguyen Van Minh"        (tên đầy đủ)
                    - "tag:VIP"
                    Để trống để lấy danh sách gần đây.
        limit:      Số khách tối đa (mặc định 20, tối đa 250)
        since_days: Chỉ lấy khách tạo trong N ngày gần nhất (0 = không giới hạn)
        shop:       Domain store (để trống nếu chỉ có 1 store)

    Returns:
        Danh sách khách hàng tóm tắt.
    """
    try:
        client, domain = _get_client(shop)
    except (ValueError, RuntimeError) as e:
        return _error(e)

    try:
        if query:
            customers = client.search_customers(query, limit=limit)
        else:
            customers = client.list_customers(limit=limit, since_days=since_days)
    except Exception as e:
        return _error(e)

    if not customers:
        q_info = f" (query: '{query}')" if query else ""
        return f"Không tìm thấy khách hàng nào{q_info}.\nStore: {domain}"

    header = f"Shopify [{domain}] — {len(customers)} khách hàng\n"
    body = "\n\n".join(_fmt_customer(c) for c in customers)
    return header + body


@mcp.tool()
def shopify_get_customer(customer_id: int, include_orders: bool = False, shop: str = "") -> str:
    """
    Xem chi tiết một khách hàng Shopify.

    Args:
        customer_id:    ID khách hàng (lấy từ shopify_list_customers).
        include_orders: Hiển thị thêm lịch sử 10 đơn hàng gần nhất.
        shop:           Domain store (để trống nếu chỉ có 1 store)

    Returns:
        Chi tiết khách hàng: thông tin liên hệ, lịch sử mua, tags, ghi chú.
    """
    try:
        client, domain = _get_client(shop)
    except (ValueError, RuntimeError) as e:
        return _error(e)

    try:
        customer = client.get_customer(customer_id)
    except Exception as e:
        return _error(e)

    lines = [f"Shopify [{domain}]\n", _fmt_customer(customer, detail=True)]

    if include_orders:
        try:
            orders = client.get_customer_orders(customer_id, limit=10)
            if orders:
                lines.append(f"\nLịch sử đơn hàng ({len(orders)} gần nhất):")
                for o in orders:
                    lines.append("  " + _fmt_order(o).replace("\n", "\n  "))
        except Exception as e:
            lines.append(f"\n⚠️ Không lấy được lịch sử đơn: {e}")

    return "\n".join(lines)


@mcp.tool()
def shopify_update_customer(
    customer_id: int,
    note: str = "",
    add_tag: str = "",
    remove_tag: str = "",
    shop: str = "",
) -> str:
    """
    Cập nhật thông tin khách hàng: ghi chú và/hoặc tags.

    Args:
        customer_id: ID khách hàng Shopify.
        note:        Ghi chú nội bộ mới (ghi đè ghi chú cũ, để trống = không đổi).
        add_tag:     Tag cần thêm (VD: "VIP", "wholesale").
        remove_tag:  Tag cần xoá.
        shop:        Domain store (để trống nếu chỉ có 1 store)

    Returns:
        Kết quả cập nhật và thông tin hiện tại của khách hàng.
    """
    if not note and not add_tag and not remove_tag:
        return "❌ Cần ít nhất một trong: note, add_tag, remove_tag."

    try:
        client, domain = _get_client(shop)
    except (ValueError, RuntimeError) as e:
        return _error(e)

    results = []
    try:
        if add_tag:
            client.add_customer_tag(customer_id, add_tag)
            results.append(f"✅ Đã thêm tag '{add_tag}'")
        if remove_tag:
            client.remove_customer_tag(customer_id, remove_tag)
            results.append(f"✅ Đã xoá tag '{remove_tag}'")
        if note:
            client.update_customer(customer_id, note=note)
            results.append(f"✅ Đã cập nhật ghi chú")

        customer = client.get_customer(customer_id)
        name = f"{customer.get('first_name','')} {customer.get('last_name','')}".strip()
        results.append(f"\n{_fmt_customer(customer, detail=True)}")
    except Exception as e:
        return _error(e)

    return f"Khách hàng #{customer_id} [{domain}]\n" + "\n".join(results)


# ---------------------------------------------------------------------------
# Tools — Products
# ---------------------------------------------------------------------------

@mcp.tool()
def shopify_list_products(
    query: str = "",
    status: str = "active",
    vendor: str = "",
    limit: int = 20,
    shop: str = "",
) -> str:
    """
    Lấy danh sách sản phẩm Shopify.

    Args:
        query:  Tìm theo tên sản phẩm (title).
        status: Trạng thái: active | draft | archived (mặc định: active)
        vendor: Lọc theo nhà cung cấp.
        limit:  Số sản phẩm tối đa (mặc định 20, tối đa 250)
        shop:   Domain store (để trống nếu chỉ có 1 store)

    Returns:
        Danh sách sản phẩm tóm tắt với giá và tồn kho.
    """
    try:
        client, domain = _get_client(shop)
    except (ValueError, RuntimeError) as e:
        return _error(e)

    try:
        products = client.list_products(
            limit=limit,
            title=query,
            status=status,
            vendor=vendor,
        )
    except Exception as e:
        return _error(e)

    if not products:
        return f"Không tìm thấy sản phẩm nào.\nStore: {domain}"

    header = f"Shopify [{domain}] — {len(products)} sản phẩm (status={status})\n"
    body = "\n\n".join(_fmt_product(p) for p in products)
    return header + body


@mcp.tool()
def shopify_get_product(product_id: int, shop: str = "") -> str:
    """
    Xem chi tiết sản phẩm Shopify, bao gồm tất cả variants và tồn kho.

    Args:
        product_id: ID sản phẩm Shopify (lấy từ shopify_list_products).
        shop:       Domain store (để trống nếu chỉ có 1 store)

    Returns:
        Chi tiết sản phẩm: variants, giá, tồn kho từng variant, inventory_item_id.
    """
    try:
        client, domain = _get_client(shop)
    except (ValueError, RuntimeError) as e:
        return _error(e)

    try:
        product = client.get_product(product_id)
    except Exception as e:
        return _error(e)

    lines = [f"Shopify [{domain}]\n", _fmt_product(product, detail=True)]

    # Nếu chỉ có 1 location, hiển thị luôn inventory detail
    try:
        locations = client.get_locations()
        if len(locations) == 1:
            loc = locations[0]
            lines.append(f"\nLocation: {loc['name']} (ID: {loc['id']})")
        elif locations:
            lines.append(f"\nLocations ({len(locations)}):")
            for loc in locations:
                lines.append(f"  • {loc['name']}  (location_id={loc['id']})")
            lines.append("Dùng shopify_update_inventory để cập nhật tồn kho.")
    except Exception:
        pass

    return "\n".join(lines)


@mcp.tool()
def shopify_update_inventory(
    inventory_item_id: int,
    available: int,
    location_id: int = 0,
    shop: str = "",
) -> str:
    """
    Cập nhật số lượng tồn kho cho một variant sản phẩm.

    inventory_item_id và location_id lấy từ shopify_get_product.

    Args:
        inventory_item_id: ID tồn kho của variant (thấy trong shopify_get_product).
        available:         Số lượng mới (tuyệt đối, không phải delta).
        location_id:       ID location (để 0 = tự động dùng location đầu tiên).
        shop:              Domain store (để trống nếu chỉ có 1 store)

    Returns:
        Kết quả cập nhật tồn kho.
    """
    try:
        client, domain = _get_client(shop)
    except (ValueError, RuntimeError) as e:
        return _error(e)

    try:
        if location_id == 0:
            locations = client.get_locations()
            if not locations:
                return "❌ Không tìm thấy location nào trong store."
            location_id = locations[0]["id"]
            loc_name = locations[0]["name"]
        else:
            loc_name = str(location_id)

        result = client.set_inventory_level(location_id, inventory_item_id, available)
    except Exception as e:
        return _error(e)

    return (
        f"✅ Đã cập nhật tồn kho [{domain}]\n"
        f"   inventory_item_id : {inventory_item_id}\n"
        f"   Location          : {loc_name} (ID: {location_id})\n"
        f"   Số lượng mới      : {result.get('available', available)}"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
