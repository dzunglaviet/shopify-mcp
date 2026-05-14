# Shopify MCP

Manage your Shopify store directly from Claude / OpenClaw — orders, customers, products, and inventory — using natural language.

Powered by [shopify-mcp](https://github.com/dzunglaviet/shopify-mcp), a Python MCP server connecting to the Shopify Admin REST API.

## What you can do

**Orders**
- List and filter orders by status, date, tag, payment, or fulfillment state
- View full order details: line items, tracking, refunds
- Add/remove tags, update internal notes
- Cancel orders with reason and optional customer notification
- Create fulfillments with tracking number and carrier

**Customers**
- Search customers by email, phone, name, or tag
- View customer details and order history
- Add/remove tags, update internal notes

**Products & Inventory**
- List and search products by title, vendor, or status
- View variant details, prices, and inventory quantities
- Update inventory levels at any location

## Setup

### 1. Install the server

```bash
git clone https://github.com/dzunglaviet/shopify-mcp
cd shopify-mcp
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
```

### 2. Create a Shopify Custom App

1. Shopify Admin → Settings → Apps → **Develop apps** → Create an app
2. Go to **Configuration → Admin API scopes** and enable:
   - `read_orders`, `write_orders`
   - `read_customers`, `write_customers`
   - `read_products`
   - `read_inventory`, `write_inventory`
   - `read_fulfillments`, `write_fulfillments`
3. Go to **API credentials → Install app** → copy the `shpat_...` token

### 3. Configure `.env`

```bash
SHOPIFY_SHOP_DOMAIN=your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 4. Add to OpenClaw / Claude Code

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

## Example prompts

```
List the last 10 open orders
Find customer with email john@example.com
Show details for order #1042
Add tag "priority" to order 6543210987654
Fulfill order 6543210987654 with GHN tracking ABC123456789
Set inventory for product "Blue T-Shirt size L" to 50 units
```

## Multiple stores

Set `SHOPIFY_STORES` in `.env` as a JSON array, then pass `shop` to any tool:

```bash
SHOPIFY_STORES=[{"shop_domain":"store-a.myshopify.com","access_token":"shpat_aaa"},{"shop_domain":"store-b.myshopify.com","access_token":"shpat_bbb"}]
```

```
List orders from store-b
```

## Source

GitHub: https://github.com/dzunglaviet/shopify-mcp
