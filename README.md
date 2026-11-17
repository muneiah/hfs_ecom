# Kanak: jewellery store

A complete small e-commerce site: product catalogue, accounts, shopping bag, checkout, order history, and an admin area for products, stock, offers and orders. Built with Flask and SQLite. The only dependency is Flask.

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

On first start it creates `store.db` with 5 categories, 17 sample products, 2 sample offers and an admin account:

- Admin login: `admin@example.com` / `admin123`
- Change it straight away: log in, then Admin > Change my password.
- Or set your own before the first start: `ADMIN_EMAIL=you@shop.in ADMIN_PASSWORD=... python app.py`

To start fresh, stop the app and delete `store.db`.

## Upgrading a store you are already running

Replace the project files and start the app. Your existing `store.db` is upgraded automatically, and nothing is lost. Make a copy of `store.db` first, as you would before any upgrade.

- Every existing product gets an actual price equal to its current price, so nothing shows a discount until you set one.
- Existing orders are unchanged and show no discount.
- No sample offers are added to an existing store. Create your own under Admin > Offers.

## Prices and discounts on products

Each product has two prices, set in Admin > Products:

- **Actual price (MRP):** the original price, shown struck through.
- **Selling price:** what the customer pays. It can't be higher than the actual price.

When the selling price is lower, the store shows the struck-through MRP, the percentage off and "You save" on the product page. Leave the actual price blank for a product with no discount. The form previews the percentage as you type.

Shoppers can also use the **On sale** filter and sort by **Biggest discount**.

## Offers on order totals

Admin > Offers controls discounts on the whole order. Each offer has:

| Field | What it does |
|---|---|
| Offer name | Shown to customers in their bag and on their order |
| Type | Percent off (1 to 90) or a flat rupee amount off |
| Minimum order | The subtotal needed to qualify. A flat discount needs a minimum above its amount, so an order can never become free |
| Largest discount | Optional cap for percent offers, for example 5% up to ₹2,000 |
| Coupon code | Leave blank and the offer applies automatically. Enter a code and customers must type it in their bag |
| Last valid day | Optional. The offer works through the end of that day |
| Offer is on | Turn an offer off and on without deleting it |

How offers behave:

- **One offer per order:** whichever saves the customer the most, out of all automatic offers and the coupon they entered. Offers never stack.
- **Automatic offers** are announced in the top bar of the store (up to two). Coupon codes are not advertised.
- The minimum order is measured on the subtotal **after** product discounts.
- **Free delivery** is judged on that same subtotal **before** the order offer, so an offer can never make a customer pay delivery they would otherwise not pay.
- The bag tells customers how much more to add to reach the next automatic offer, and explains why a coupon isn't applied.
- The discount is worked out again at the moment of checkout, so a changed price or a switched-off offer can't be used after the fact.
- Each order stores the offer name and amount, so editing or deleting an offer later never changes past orders.
- The Offers page shows how many orders used each offer and the total given, not counting cancelled orders.

The two sample offers are 5% off orders of ₹10,000 or more (up to ₹2,000, automatic) and `WELCOME200` for ₹200 off orders of ₹2,000 or more. Edit or delete them freely.

## What else is in it

**Storefront**
- Home page, catalogue with category filter, search, sorting and pages
- Product page with stock warnings, quantity picker and related pieces
- Bag that survives login, with quantity limits tied to stock
- Register, log in, change password, order history, cancel a pending order

**Checkout**
- Indian address form (10-digit mobile, 6-digit pincode)
- Pay on delivery, or a demo online payment that charges nothing
- Stock is checked and deducted in one locked step, so two people can't buy the last piece
- Free delivery above ₹5,000, ₹99 below (edit `FREE_SHIPPING_ABOVE` and `SHIPPING_FEE` in `app.py`)

**Admin** (`/admin`, admin accounts only)
- Dashboard: orders, pending count, sales, offer discounts given, low stock with quick stock edit
- Products: add, edit, prices, photo upload, hide or show, delete, inline stock update
- Orders: filter by status, view details and the discount breakdown, move through Pending, Confirmed, Shipped, Delivered
- Cancelling an order returns its items to stock. Cancelled orders stay cancelled.
- Cash on delivery orders are marked paid when you mark them Delivered
- Offers, categories and a read-only customer list

Deleting a product never breaks past orders, because each order keeps its own copy of the name and prices.

## Settings

Environment variables, all optional:

| Variable | Purpose |
|---|---|
| `STORE_NAME` | Name shown in the header and page titles (default Kanak) |
| `SECRET_KEY` | Session signing key. If unset, one is generated and saved to `.secret_key` |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Admin account created on first start |
| `DB_PATH` | Where the database file lives |
| `HTTPS=1` | Marks cookies as secure. Set this when serving over HTTPS |
| `PORT`, `HOST` | Default 5000 on 127.0.0.1 |

Product photos are saved in `static/uploads/`. Products without a photo show a drawn placeholder.

## Before you take real orders

This is a working foundation, not a finished business. Decide on these first:

1. **Real payments.** "Online payment (demo)" is a stand-in. No card details are collected or stored anywhere. To accept money online, add a payment gateway such as Razorpay or PayU in the `checkout` route, and mark the order paid only after the gateway confirms it.
2. **Production server.** `python app.py` is for development. Run it with a real server, for example `pip install gunicorn` then `gunicorn -w 2 app:app`, behind HTTPS (nginx or Caddy), and set `HTTPS=1` and a fixed `SECRET_KEY`.
3. **Backups.** Copy `store.db` and `static/uploads/` regularly. Everything lives in those two places.
4. **Not included:** order emails or SMS, password reset by email, GST invoices, returns handling, product variants (sizes), multiple photos per product, limits on how many times a coupon can be used. These are the usual next additions.
5. **Check the wording.** Delivery, payment and offer text on the pages describes what the code does today. Update it if your policies differ.
6. **Scale.** SQLite handles a small shop comfortably. If you grow to heavy traffic, move to PostgreSQL.

## Layout

```
app.py               all routes, database setup, upgrade steps and sample data
templates/           storefront pages
templates/admin/     admin pages
static/style.css     all styling
static/uploads/      product photos you upload
```
