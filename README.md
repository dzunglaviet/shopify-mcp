# iMat Shopify Skill

MCP server độc lập cho phép Claude Code / OpenClaw theo dõi và quản lý Shopify trực tiếp.

## Tools có sẵn

### Đơn hàng (Orders)

| Tool | Mô tả |
|------|-------|
| `shopify_list_orders` | Danh sách đơn hàng, lọc theo status / tag / ngày / thanh toán / giao hàng |
| `shopify_get_order` | Chi tiết đơn hàng: sản phẩm, tracking, hoàn tiền |
| `shopify_update_order` | Thêm / xoá tag, cập nhật ghi chú |
| `shopify_cancel_order` | Huỷ đơn hàng (kèm lý do, tuỳ chọn thông báo khách) |
| `shopify_fulfill_order` | Xác nhận giao hàng (tạo fulfillment + mã vận đơn) |

### Khách hàng (Customers)

| Tool | Mô tả |
|------|-------|
| `shopify_list_customers` | Danh sách hoặc tìm kiếm khách hàng |
| `shopify_get_customer` | Chi tiết khách hàng + lịch sử đơn hàng |
| `shopify_update_customer` | Thêm / xoá tag, cập nhật ghi chú nội bộ |

### Sản phẩm & Tồn kho (Products)

| Tool | Mô tả |
|------|-------|
| `shopify_list_products` | Danh sách sản phẩm, lọc theo tên / vendor / status |
| `shopify_get_product` | Chi tiết sản phẩm: variants, giá, tồn kho, inventory_item_id |
| `shopify_update_inventory` | Cập nhật số lượng tồn kho |

---

## Cài đặt

### Bước 1 — Chuẩn bị môi trường

```bash
cd shopify-mcp
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### Bước 2 — Tạo Shopify App

1. Shopify Admin → Settings → Apps → **Develop apps** → Create an app
2. Đặt tên: `iMat Shopify Skill`
3. **Configuration → Admin API scopes** — bật các quyền sau:

| Scope | Mục đích |
|-------|----------|
| `read_orders`, `write_orders` | Xem và cập nhật đơn hàng |
| `read_customers`, `write_customers` | Xem và cập nhật khách hàng |
| `read_products` | Xem sản phẩm và variants |
| `read_inventory`, `write_inventory` | Xem và cập nhật tồn kho |
| `read_fulfillments`, `write_fulfillments` | Tạo fulfillment / xác nhận giao hàng |

4. **API credentials → Install app** → copy `shpat_...`

### Bước 3 — Cấu hình `.env`

```bash
cp .env.example .env
nano .env
```

Điền `SHOPIFY_SHOP_DOMAIN` và `SHOPIFY_ACCESS_TOKEN`.

### Bước 4 — Thêm vào Claude Code / OpenClaw

Thêm vào `~/.claude/settings.json` (global) hoặc `.claude/settings.json` (project):

```json
{
  "mcpServers": {
    "shopify-mcp": {
      "command": "/path/to/shopify-mcp/venv/bin/python",
      "args": ["server.py"],
      "cwd": "/path/to/shopify-mcp"
    }
  }
}
```

> Thay `/path/to/shopify-mcp` bằng đường dẫn tuyệt đối đến thư mục này.

### Bước 5 — Kiểm tra

Trong Claude Code / OpenClaw, thử:

```
Liệt kê 5 đơn hàng open gần nhất
```

Claude sẽ gọi `shopify_list_orders` và trả kết quả ngay.

---

## Multi-store

Để quản lý nhiều store, dùng `SHOPIFY_STORES` dạng JSON array trong `.env`:

```bash
SHOPIFY_STORES=[{"shop_domain":"store1.myshopify.com","access_token":"shpat_aaa"},{"shop_domain":"store2.myshopify.com","access_token":"shpat_bbb"}]
```

Khi dùng tool, chỉ định store bằng tham số `shop`:

```
Liệt kê đơn hàng của store2
```

Nếu không truyền `shop`, mặc định dùng store đầu tiên.

---

## Ví dụ hỏi Claude

```
Cho tôi xem 10 đơn hàng open của hôm nay
Tìm khách hàng có email: nguyenvan@gmail.com
Chi tiết đơn hàng ID 6543210987654
Thêm tag "priority" vào đơn 6543210987654
Xác nhận giao hàng đơn 6543210987654, tracking GHN123456789
Cập nhật tồn kho variant áo đỏ size L còn 50 cái
```

---

## Cấu trúc file

```
shopify-mcp/
├── server.py         ← MCP server (entry point)
├── shopify_api.py    ← Shopify REST API client
├── requirements.txt
├── .env.example
├── .env              ← (tạo thủ công, không commit)
├── README.md
└── storage/          ← (tự tạo) cache OAuth token
```
