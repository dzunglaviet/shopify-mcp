# Shopify MCP

A Model Context Protocol (MCP) server that connects Claude / OpenClaw directly to your Shopify store. Manage orders, customers, products, and inventory through natural language — no dashboard switching required.

> Supports **multiple stores** and both **static access tokens** and **OAuth client credentials**.

---

## Tools

### Orders

| Tool | Description |
|------|-------------|
| `shopify_list_orders` | List orders with filters: status, tag, date range, financial status, fulfillment status |
| `shopify_get_order` | Full order details: line items, fulfillments, refunds, notes |
| `shopify_update_order` | Add or remove tags, update internal note |
| `shopify_cancel_order` | Cancel an order with reason; optionally notify the customer |
| `shopify_fulfill_order` | Create a fulfillment with tracking number and carrier |

### Customers

| Tool | Description |
|------|-------------|
| `shopify_list_customers` | List recent customers or search by email, phone, name, or tag |
| `shopify_get_customer` | Customer details with optional order history |
| `shopify_update_customer` | Add or remove tags, update internal note |

### Products & Inventory

| Tool | Description |
|------|-------------|
| `shopify_list_products` | List products with filters: title, vendor, status |
| `shopify_get_product` | Product details: all variants, prices, inventory quantities, `inventory_item_id` |
| `shopify_update_inventory` | Set absolute inventory quantity at a location |

---

## Requirements

- Python 3.9+
- A Shopify store with a [Custom App](https://help.shopify.com/en/manual/apps/app-types/custom-apps)

### Shopify API Scopes

Grant the following scopes when configuring your Custom App:

| Scope | Used by |
|-------|---------|
| `read_orders`, `write_orders` | List, update, cancel orders |
| `read_customers`, `write_customers` | List, search, update customers |
| `read_products` | List and inspect products/variants |
| `read_inventory`, `write_inventory` | Read and update inventory levels |
| `read_fulfillments`, `write_fulfillments` | Create fulfillments |

---

## Installation

```bash
git clone <repo-url> shopify-mcp
cd shopify-mcp
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

---

## Configuration

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

### Single store — static token

```bash
SHOPIFY_SHOP_DOMAIN=your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SHOPIFY_API_VERSION=2026-04
```

### Single store — OAuth (auto-refresh)

```bash
SHOPIFY_SHOP_DOMAIN=your-store.myshopify.com
SHOPIFY_CLIENT_ID=your_client_id
SHOPIFY_CLIENT_SECRET=your_client_secret
SHOPIFY_API_VERSION=2026-04
```

### Multiple stores

```bash
SHOPIFY_STORES=[{"shop_domain":"store-a.myshopify.com","access_token":"shpat_aaa"},{"shop_domain":"store-b.myshopify.com","client_id":"xxx","client_secret":"yyy"}]
SHOPIFY_API_VERSION=2026-04
```

When using multiple stores, pass the `shop` parameter to any tool to target a specific store. Omitting `shop` defaults to the first configured store.

---

## Adding to Claude Code / OpenClaw

Add to `~/.claude/settings.json` (global) or `.claude/settings.json` (project):

```json
{
  "mcpServers": {
    "shopify-mcp": {
      "command": "/absolute/path/to/shopify-mcp/venv/bin/python",
      "args": ["server.py"],
      "cwd": "/absolute/path/to/shopify-mcp"
    }
  }
}
```

Restart Claude Code / OpenClaw after saving.

---

## Usage examples

```
List the last 10 open orders
Show me order #1042
Find customer with email: john@example.com
Add tag "wholesale" to customer 123456
Get product details for product ID 789012
Cancel order 6543210987654 — customer changed their mind
Fulfill order 6543210987654 with GHN tracking number ABC123456789
Set inventory for inventory_item_id 11223344 to 50 units
```

---

## How it works

```
Claude / OpenClaw
      │  MCP (stdio)
      ▼
  server.py  ──►  shopify_api.py  ──►  Shopify Admin REST API
                      │
                   storage/           ← OAuth token cache (chmod 600)
```

- **No daemon required** — the MCP server is a lightweight process started on demand by the MCP host.
- **Rate limiting** — automatically waits on `429 Too Many Requests` using Shopify's `Retry-After` header.
- **Token refresh** — OAuth tokens are cached locally and refreshed 5 minutes before expiry. On a `401`, the token is force-refreshed and the request retried once.
- **Retries** — transient network errors are retried up to 3 times with exponential backoff.

---

## File structure

```
shopify-mcp/
├── server.py         ← MCP server entry point (11 tools)
├── shopify_api.py    ← Shopify Admin REST API client
├── requirements.txt
├── .env.example
└── storage/          ← auto-created; stores OAuth token cache
```

---

## License

MIT
