"""Kanak - a complete small e-commerce site for jewellery.

Flask + SQLite, no other dependencies.
Run:  python app.py   then open http://127.0.0.1:5000
"""
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import date
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# --------------------------------------------------------------------------
# Configuration (edit these, or set environment variables)
# --------------------------------------------------------------------------
BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "store.db"))
UPLOAD_DIR = os.path.join(BASE, "static", "uploads")
STORE_NAME = os.environ.get("STORE_NAME", "Hari's Fancy Store")
FREE_SHIPPING_ABOVE = 2500      # rupees
SHIPPING_FEE = 99               # rupees
MAX_QTY_PER_LINE = 10
PER_PAGE = 12
ORDER_STATUSES = ["Pending", "Confirmed", "Shipped", "Delivered", "Cancelled"]
PAYMENT_LABELS = {"demo": "Online payment (demo)"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024  # 3 MB uploads
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
if os.environ.get("HTTPS") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True


def _load_secret():
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    path = os.path.join(BASE, ".secret_key")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w") as f:
        f.write(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


app.secret_key = _load_secret()

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  slug TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  material TEXT NOT NULL DEFAULT '',
  mrp INTEGER NOT NULL DEFAULT 0,
  price INTEGER NOT NULL CHECK (price >= 0),
  stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
  image TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'Pending',
  mrp_total INTEGER NOT NULL DEFAULT 0,
  subtotal INTEGER NOT NULL,
  discount INTEGER NOT NULL DEFAULT 0,
  discount_label TEXT NOT NULL DEFAULT '',
  offer_id INTEGER,
  shipping INTEGER NOT NULL,
  total INTEGER NOT NULL,
  ship_name TEXT NOT NULL,
  ship_phone TEXT NOT NULL,
  ship_address TEXT NOT NULL,
  ship_city TEXT NOT NULL,
  ship_state TEXT NOT NULL,
  ship_pincode TEXT NOT NULL,
  payment_method TEXT NOT NULL,
  payment_status TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  mrp INTEGER NOT NULL DEFAULT 0,
  price INTEGER NOT NULL,
  qty INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS offers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  code TEXT UNIQUE,                 -- NULL means the offer applies automatically
  kind TEXT NOT NULL CHECK (kind IN ('percent', 'flat')),
  value INTEGER NOT NULL CHECK (value > 0),
  min_subtotal INTEGER NOT NULL DEFAULT 0,
  max_discount INTEGER,             -- cap for percent offers, NULL = no cap
  expires_on TEXT,                  -- YYYY-MM-DD, valid through that day; NULL = never
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_products_cat ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
"""

SEED_CATEGORIES = [("Rings", "rings"), ("Necklaces", "necklaces"),
                   ("Earrings", "earrings"), ("Bracelets", "bracelets"),
                   ("Anklets", "anklets")]

# (name, category slug, material, price, stock, description)
SEED_PRODUCTS = [
    ("Solitaire Band", "rings", "Gold", 18900, 6,
     "A slim 18k gold band with a single faceted stone, made for stacking or wearing alone."),
    ("Twin Leaf Ring", "rings", "Rose gold", 9400, 12,
     "Two small leaves meet at the centre of this open rose gold ring. Adjustable by a size."),
    ("Moonstone Ring", "rings", "Silver", 3200, 15,
     "Sterling silver with a polished moonstone cabochon that shifts blue in daylight."),
    ("Heirloom Signet", "rings", "Gold", 24500, 3,
     "A wide, flat-top signet in 22k gold. Sized for everyday wear, with room for engraving."),
    ("Temple Line Necklace", "necklaces", "Gold", 38500, 4,
     "Handworked 22k gold necklace inspired by temple borders, finished with a hook clasp."),
    ("Pearl Strand", "necklaces", "Silver", 6800, 9,
     "Freshwater pearls knotted by hand on silk, closing with a sterling silver clasp."),
    ("Ruby Drop Pendant", "necklaces", "Gold", 21200, 5,
     "A teardrop ruby in a gold bezel on a fine 18 inch chain."),
    ("Everyday Chain", "necklaces", "Silver", 2400, 30,
     "A light sterling silver box chain. Plain on purpose, so it works under any pendant."),
    ("Jhumka Classic", "earrings", "Gold", 14800, 8,
     "Bell-shaped gold jhumkas with a pearl drop and a secure screw back."),
    ("Tiny Hoops", "earrings", "Gold", 5200, 20,
     "12 mm gold hoops, light enough to sleep in."),
    ("Emerald Studs", "earrings", "Rose gold", 11600, 2,
     "Round emerald studs set in rose gold. Each stone is chosen to match its pair."),
    ("Silver Chandbali", "earrings", "Silver", 3900, 14,
     "Crescent chandbalis in oxidised silver with small hanging beads."),
    ("Kada Bangle", "bracelets", "Gold", 42000, 3,
     "A solid 22k gold kada with a plain, softly rounded finish."),
    ("Thread of Beads", "bracelets", "Rose gold", 7400, 11,
     "Rose gold beads on a slim chain with a lobster clasp, adjustable to two lengths."),
    ("Link Cuff", "bracelets", "Silver", 4600, 16,
     "Chunky sterling silver links with a toggle clasp."),
    ("Charm Anklet", "anklets", "Silver", 2800, 25,
     "A sterling silver anklet with three tiny bells. Sold singly, 10 inches with extender."),
    ("Gold Payal", "anklets", "Gold", 16900, 0,
     "Fine gold payal with delicate ghungroo. Currently sold out."),
]

# Actual price (MRP) for the sample products above, whose listed price is the selling price.
# Products missing here have no discount.
SEED_MRP = {
    "Solitaire Band": 21000, "Twin Leaf Ring": 11000, "Moonstone Ring": 3800,
    "Temple Line Necklace": 42000, "Pearl Strand": 8500, "Everyday Chain": 2900,
    "Jhumka Classic": 16000, "Emerald Studs": 13500, "Silver Chandbali": 4900,
    "Thread of Beads": 9250, "Charm Anklet": 3500, "Gold Payal": 18500,
}

# (name, code or None for automatic, kind, value, min order, max discount)
SEED_OFFERS = [
    ("Festive saving", None, "percent", 5, 10000, 2000),
    ("Welcome offer", "WELCOME200", "flat", 200, 2000, None),
]


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def add_column(db, table, column, ddl):
    have = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
    if column not in have:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def migrate(db):
    """Bring a database made by an earlier version up to date. Safe to run on every start."""
    add_column(db, "products", "mrp", "INTEGER NOT NULL DEFAULT 0")
    add_column(db, "orders", "mrp_total", "INTEGER NOT NULL DEFAULT 0")
    add_column(db, "orders", "discount", "INTEGER NOT NULL DEFAULT 0")
    add_column(db, "orders", "discount_label", "TEXT NOT NULL DEFAULT ''")
    add_column(db, "orders", "offer_id", "INTEGER")
    add_column(db, "order_items", "mrp", "INTEGER NOT NULL DEFAULT 0")
    # Old rows had one price. Treat it as both actual and selling price (no discount).
    db.execute("UPDATE products SET mrp = price WHERE mrp < price")
    db.execute("UPDATE order_items SET mrp = price WHERE mrp < price")
    db.execute("UPDATE orders SET mrp_total = subtotal WHERE mrp_total < subtotal")


def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    db = get_db()
    db.executescript(SCHEMA)
    migrate(db)
    if db.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0] == 0:
        email = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
        password = os.environ.get("ADMIN_PASSWORD", "admin123")
        db.execute(
            "INSERT INTO users(name,email,password_hash,is_admin) VALUES(?,?,?,1)",
            ("Store admin", email, generate_password_hash(password)))
        print(f"\n  Admin account created: {email} / {password}")
        print("  Change this password before going live (Admin > Change my password).\n")
    if db.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        db.executemany("INSERT INTO categories(name,slug) VALUES(?,?)", SEED_CATEGORIES)
        cats = {r["slug"]: r["id"] for r in db.execute("SELECT id,slug FROM categories")}
        for name, slug, material, price, stock, desc in SEED_PRODUCTS:
            db.execute(
                "INSERT INTO products(name,description,category_id,material,mrp,price,stock)"
                " VALUES(?,?,?,?,?,?,?)",
                (name, desc, cats[slug], material, SEED_MRP.get(name, price), price, stock))
        db.executemany(
            "INSERT INTO offers(name,code,kind,value,min_subtotal,max_discount) VALUES(?,?,?,?,?,?)",
            SEED_OFFERS)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def inr(n):
    """Format whole rupees with Indian digit grouping: 1,23,456."""
    n = int(n or 0)
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + "₹" + s


def order_no(oid):
    return f"KN{1000 + int(oid)}"


def img_url(p):
    if p["image"]:
        return url_for("static", filename="uploads/" + p["image"])
    return url_for("art", pid=p["id"])


def date_fmt(s):
    return (s or "")[:16].replace("T", " ")


app.jinja_env.filters.update(inr=inr, order_no=order_no, img=img_url, date=date_fmt)


def safe_next(target, default):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return default


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "category"


def pct_off(p):
    """Whole-number percentage between MRP and selling price (0 when there is no discount)."""
    mrp, price = p["mrp"], p["price"]
    return round((mrp - price) * 100 / mrp) if mrp > price else 0


def offer_expired(o):
    return bool(o["expires_on"]) and o["expires_on"] < date.today().isoformat()


def offer_status(o):
    if not o["active"]:
        return "Off"
    return "Expired" if offer_expired(o) else "Active"


def offer_saving(o, subtotal):
    """Rupees this offer takes off `subtotal`; 0 when it doesn't apply."""
    if not o["active"] or offer_expired(o) or subtotal <= 0 or subtotal < o["min_subtotal"]:
        return 0
    if o["kind"] == "percent":
        saving = subtotal * o["value"] // 100
        if o["max_discount"]:
            saving = min(saving, o["max_discount"])
    else:
        saving = o["value"]
    return max(0, min(saving, subtotal))


def offer_short(o):
    return f"{o['value']}% off" if o["kind"] == "percent" else f"{inr(o['value'])} off"


def offer_text(o):
    """Plain-language description, e.g. '5% off on orders of ₹10,000 or more (up to ₹2,000)'."""
    when = f"on orders of {inr(o['min_subtotal'])} or more" if o["min_subtotal"] else "on every order"
    cap = f" (up to {inr(o['max_discount'])})" if o["kind"] == "percent" and o["max_discount"] else ""
    return f"{offer_short(o)} {when}{cap}"


app.jinja_env.filters.update(off=pct_off, offer_status=offer_status,
                             offer_short=offer_short, offer_text=offer_text)


def build_cart():
    """Price the session bag: product discounts, the best order offer, delivery and total.

    Only ONE order offer applies, the one that saves the most among all automatic offers and
    the coupon the customer entered. Free delivery is judged on the subtotal before the order
    offer, so an offer can never make an order cost more.
    """
    cart = {"lines": [], "mrp_total": 0, "subtotal": 0, "product_savings": 0, "offer": None,
            "discount": 0, "shipping": 0, "total": 0, "saved": 0, "coupon": "",
            "coupon_applied": False, "coupon_note": "", "next_offer": None, "next_gap": 0}
    bag = session.get("bag") or {}
    if not bag:
        return cart
    db = get_db()
    ids = [int(i) for i in bag]
    marks = ",".join("?" * len(ids))
    rows = db.execute(
        f"SELECT * FROM products WHERE active=1 AND id IN ({marks})", ids).fetchall()
    subtotal = mrp_total = 0
    for r in rows:
        qty = int(bag.get(str(r["id"]), 0))
        total = qty * r["price"]
        line_mrp = qty * max(r["mrp"], r["price"])
        subtotal += total
        mrp_total += line_mrp
        cart["lines"].append({"p": r, "qty": qty, "total": total, "mrp_total": line_mrp,
                              "ok": r["stock"] >= qty})
    if not cart["lines"]:
        return cart

    code = (session.get("coupon") or "").upper()
    cart["coupon"] = code
    offers = db.execute(
        "SELECT * FROM offers WHERE active=1 AND (code IS NULL OR code=?)", (code,)).fetchall()
    best, best_save, coupon_row, coupon_save = None, 0, None, 0
    for o in offers:
        save = offer_saving(o, subtotal)
        if o["code"]:
            coupon_row, coupon_save = o, save
        elif save > best_save:
            best, best_save = o, save
    if coupon_row is not None:
        if coupon_save and coupon_save >= best_save:
            best, best_save = coupon_row, coupon_save
            cart["coupon_applied"] = True
        elif offer_expired(coupon_row):
            cart["coupon_note"] = f"{code} has expired."
        elif subtotal < coupon_row["min_subtotal"]:
            cart["coupon_note"] = (f"Add {inr(coupon_row['min_subtotal'] - subtotal)} more "
                                   f"to use {code}.")
        else:
            cart["coupon_note"] = f"{code} saves less than the offer already applied, so it isn't used."
    elif code:
        cart["coupon_note"] = f"{code} is not a valid code."

    for o in offers:  # nearest automatic offer the customer hasn't reached yet
        if (not o["code"] and not offer_expired(o) and o["min_subtotal"] > subtotal
                and offer_saving(o, o["min_subtotal"]) > best_save
                and (cart["next_offer"] is None or o["min_subtotal"] < cart["next_offer"]["min_subtotal"])):
            cart["next_offer"] = o
    if cart["next_offer"]:
        cart["next_gap"] = cart["next_offer"]["min_subtotal"] - subtotal

    shipping = 0 if subtotal >= FREE_SHIPPING_ABOVE else SHIPPING_FEE
    cart.update(subtotal=subtotal, mrp_total=mrp_total, product_savings=mrp_total - subtotal,
                offer=best, discount=best_save, shipping=shipping,
                total=subtotal - best_save + shipping,
                saved=(mrp_total - subtotal) + best_save)
    return cart


def sniff_image(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save_upload(file):
    """Save an uploaded product image; returns filename or None."""
    if not file or not file.filename:
        return None
    secure_filename(file.filename)
    data = file.read()
    ext = sniff_image(data)
    if not ext:
        raise ValueError("Upload a PNG, JPG or WebP image.")
    name = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(data)
    return name


def remove_upload(name):
    if name:
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(name)))
        except OSError:
            pass


# ---- auth ----------------------------------------------------------------
@app.before_request
def load_user():
    g.user = None
    uid = session.get("user_id")
    if uid:
        g.user = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if g.user is None:
            session.pop("user_id", None)


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("csrf")
        if not token or not secrets.compare_digest(token, request.form.get("csrf", "")):
            abort(400, "Your session expired. Go back, reload the page and try again.")


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


# A global (not a context-processor value) so imported macros can call it too.
app.jinja_env.globals["csrf_token"] = csrf_token


@app.context_processor
def inject():
    bag = session.get("bag") or {}
    return {
        "store_name": STORE_NAME,
        "user": g.get("user"),
        "bag_count": sum(int(q) for q in bag.values()),
        "nav_categories": get_db().execute(
            "SELECT * FROM categories ORDER BY id").fetchall(),
        # Automatic offers are advertised in the top bar; coupon codes stay private.
        "top_offers": [offer_text(o) for o in get_db().execute(
            "SELECT * FROM offers WHERE active=1 AND code IS NULL "
            "AND (expires_on IS NULL OR expires_on >= ?) ORDER BY min_subtotal LIMIT 2",
            (date.today().isoformat(),))],
        "statuses": ORDER_STATUSES,
        "free_ship": FREE_SHIPPING_ABOVE,
        "ship_fee": SHIPPING_FEE,
        "pay_labels": PAYMENT_LABELS,
    }


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not g.user:
            flash("Log in to continue.", "info")
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return f(*a, **kw)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not g.user:
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        if not g.user["is_admin"]:
            abort(403)
        return f(*a, **kw)
    return wrapper


def start_session(user_id):
    bag = session.get("bag")
    session.clear()  # new session id on login prevents fixation
    if bag:
        session["bag"] = bag
    session["user_id"] = user_id
    session["csrf"] = secrets.token_hex(16)


FAILS = {}  # (ip, email) -> [count, first_ts]


def throttled(key):
    rec = FAILS.get(key)
    if rec and time.time() - rec[1] > 600:
        FAILS.pop(key, None)
        return False
    return bool(rec and rec[0] >= 5)


# --------------------------------------------------------------------------
# Storefront
# --------------------------------------------------------------------------
@app.route("/")
def home():
    db = get_db()
    new = db.execute("SELECT * FROM products WHERE active=1 ORDER BY id DESC LIMIT 8").fetchall()
    cats = db.execute(
        "SELECT c.*, COUNT(p.id) AS n FROM categories c "
        "LEFT JOIN products p ON p.category_id=c.id AND p.active=1 GROUP BY c.id ORDER BY c.id"
    ).fetchall()
    return render_template("home.html", new=new, cats=cats)


@app.route("/shop")
def shop():
    db = get_db()
    where, params = ["p.active=1"], []
    cat = request.args.get("cat", "")
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "new")
    sale = request.args.get("sale") == "1"
    if sale:
        where.append("p.mrp > p.price")
    if cat:
        where.append("c.slug=?")
        params.append(cat)
    if q:
        where.append("(p.name LIKE ? OR p.description LIKE ? OR p.material LIKE ?)")
        params += [f"%{q}%"] * 3
    order = {"price_asc": "p.price ASC", "price_desc": "p.price DESC",
             "discount": "(p.mrp - p.price) * 1.0 / MAX(p.mrp, 1) DESC, p.id DESC"}.get(sort, "p.id DESC")
    base = "FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE " + " AND ".join(where)
    total = db.execute("SELECT COUNT(*) " + base, params).fetchone()[0]
    page = max(1, request.args.get("page", 1, type=int))
    pages = max(1, -(-total // PER_PAGE))
    page = min(page, pages)
    items = db.execute(
        f"SELECT p.* {base} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [PER_PAGE, (page - 1) * PER_PAGE]).fetchall()
    args = {k: v for k, v in (("cat", cat), ("q", q), ("sort", sort),
                              ("sale", "1" if sale else "")) if v}
    return render_template("shop.html", items=items, total=total, page=page, pages=pages,
                           cat=cat, q=q, sort=sort, sale=sale, args=args)


@app.route("/product/<int:pid>")
def product(pid):
    db = get_db()
    p = db.execute(
        "SELECT p.*, c.name AS cat_name, c.slug AS cat_slug FROM products p "
        "LEFT JOIN categories c ON c.id=p.category_id WHERE p.id=? AND p.active=1", (pid,)).fetchone()
    if not p:
        abort(404)
    related = db.execute(
        "SELECT * FROM products WHERE active=1 AND category_id IS ? AND id!=? ORDER BY id DESC LIMIT 4",
        (p["category_id"], pid)).fetchall()
    return render_template("product.html", p=p, related=related, max_qty=min(p["stock"], MAX_QTY_PER_LINE))


# Placeholder artwork so the demo looks complete before real photos are uploaded.
STONES = ["#0E4A4F", "#9B1C3A", "#2E4B9B", "#3F7D55", "#6B3F8F"]
METALS = {"gold": "#C9962F", "rose gold": "#C98A7A", "silver": "#9AA5AD"}


@app.route("/art/<int:pid>.svg")
def art(pid):
    p = get_db().execute(
        "SELECT p.id, p.material, c.slug FROM products p "
        "LEFT JOIN categories c ON c.id=p.category_id WHERE p.id=?", (pid,)).fetchone()
    if not p:
        abort(404)
    metal = METALS.get((p["material"] or "").lower(), "#C9962F")
    stone = STONES[p["id"] % len(STONES)]
    slug = p["slug"] or "rings"
    shapes = {
        "rings": f'<ellipse cx="200" cy="238" rx="82" ry="92" fill="none" stroke="{metal}" stroke-width="18"/>'
                 f'<polygon points="200,92 238,132 200,176 162,132" fill="{stone}"/>'
                 f'<polygon points="200,92 238,132 162,132" fill="#fff" opacity=".25"/>',
        "necklaces": f'<path d="M92 104 Q200 360 308 104" fill="none" stroke="{metal}" stroke-width="7" stroke-linecap="round"/>'
                     f'<polygon points="200,252 228,284 200,326 172,284" fill="{stone}"/>'
                     f'<polygon points="200,252 228,284 172,284" fill="#fff" opacity=".25"/>',
        "earrings": "".join(
            f'<circle cx="{x}" cy="120" r="12" fill="{metal}"/>'
            f'<path d="M{x} 138 C{x-34} 190 {x-34} 250 {x} 276 C{x+34} 250 {x+34} 190 {x} 138Z" fill="{stone}"/>'
            f'<path d="M{x} 138 C{x-34} 190 {x-34} 250 {x} 276" fill="none" stroke="{metal}" stroke-width="6"/>'
            for x in (140, 260)),
        "bracelets": f'<ellipse cx="200" cy="200" rx="112" ry="84" fill="none" stroke="{metal}" stroke-width="22"/>'
                     + "".join(f'<circle cx="{200+112*c:.0f}" cy="{200+84*s:.0f}" r="9" fill="{stone}"/>'
                               for c, s in ((0, -1), (0.87, -0.5), (0.87, 0.5), (0, 1), (-0.87, 0.5), (-0.87, -0.5))),
        "anklets": f'<path d="M70 150 Q200 330 330 150" fill="none" stroke="{metal}" stroke-width="6" stroke-linecap="round" stroke-dasharray="2 12"/>'
                   f'<path d="M70 150 Q200 330 330 150" fill="none" stroke="{metal}" stroke-width="4"/>'
                   + "".join(f'<circle cx="{x}" cy="{y}" r="14" fill="{stone}"/>'
                             for x, y in ((140, 238), (200, 252), (260, 238))),
    }
    body = shapes.get(slug, shapes["rings"])
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">'
           f'<rect width="400" height="400" fill="#E6ECEB"/>{body}</svg>')
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


# ---- bag -------------------------------------------------------------------
@app.route("/bag")
def bag():
    return render_template("bag.html", cart=build_cart())


@app.post("/bag/coupon")
def bag_coupon():
    code = re.sub(r"\s+", "", request.form.get("code", "")).upper()
    if not code:
        flash("Enter a coupon code.", "error")
        return redirect(url_for("bag"))
    cart = build_cart()
    if not cart["lines"]:
        flash("Add something to your bag before using a coupon.", "info")
        return redirect(url_for("bag"))
    offer = get_db().execute("SELECT * FROM offers WHERE active=1 AND code=?", (code,)).fetchone()
    if not offer:
        flash(f"{code} is not a valid code.", "error")
    elif offer_expired(offer):
        flash(f"{code} has expired.", "error")
    elif cart["subtotal"] < offer["min_subtotal"]:
        flash(f"{code} needs an order of {inr(offer['min_subtotal'])} or more. "
              f"Add {inr(offer['min_subtotal'] - cart['subtotal'])} more.", "error")
    else:
        session["coupon"] = code
        cart = build_cart()
        if cart["coupon_applied"]:
            flash(f"{code} applied. You save {inr(cart['discount'])}.", "ok")
        else:
            flash(f"{code} saves less than the offer already on your bag, so that offer stays.", "info")
    return redirect(url_for("bag"))


@app.post("/bag/coupon/remove")
def bag_coupon_remove():
    session.pop("coupon", None)
    return redirect(url_for("bag"))


@app.post("/bag/add")
def bag_add():
    pid = request.form.get("product_id", type=int)
    qty = max(1, min(request.form.get("qty", 1, type=int) or 1, MAX_QTY_PER_LINE))
    back = safe_next(request.form.get("next"), url_for("bag"))
    p = get_db().execute("SELECT * FROM products WHERE id=? AND active=1", (pid,)).fetchone()
    if not p or p["stock"] < 1:
        flash("That piece is sold out.", "error")
        return redirect(back)
    bag_ = dict(session.get("bag") or {})
    cur = int(bag_.get(str(pid), 0))
    new = min(cur + qty, p["stock"], MAX_QTY_PER_LINE)
    if new == cur:
        flash(f"You already have all {p['stock']} available in your bag.", "info")
    else:
        bag_[str(pid)] = new
        session["bag"] = bag_
        flash(f"Added {p['name']} to your bag.", "ok")
    return redirect(back)


@app.post("/bag/update")
def bag_update():
    pid = request.form.get("product_id", type=int)
    qty = request.form.get("qty", type=int)
    bag_ = dict(session.get("bag") or {})
    if str(pid) in bag_ and qty is not None:
        if qty <= 0:
            bag_.pop(str(pid))
        else:
            p = get_db().execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()
            cap = min(p["stock"], MAX_QTY_PER_LINE) if p else 0
            bag_[str(pid)] = max(1, min(qty, cap)) if cap else 1
            if qty > cap:
                flash(f"Only {cap} available.", "info")
        session["bag"] = bag_
    return redirect(url_for("bag"))


@app.post("/bag/remove")
def bag_remove():
    pid = request.form.get("product_id", type=int)
    bag_ = dict(session.get("bag") or {})
    bag_.pop(str(pid), None)
    session["bag"] = bag_
    return redirect(url_for("bag"))


# ---- accounts --------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        err = None
        if not name:
            err = "Enter your name."
        elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            err = "Enter a valid email address."
        elif len(pw) < 8:
            err = "Use a password with at least 8 characters."
        elif get_db().execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            err = "An account with this email already exists. Log in instead."
        if err:
            flash(err, "error")
            return render_template("register.html", name=name, email=email), 400
        cur = get_db().execute("INSERT INTO users(name,email,password_hash) VALUES(?,?,?)",
                               (name, email, generate_password_hash(pw)))
        start_session(cur.lastrowid)
        flash(f"Welcome, {name}.", "ok")
        return redirect(safe_next(request.args.get("next"), url_for("home")))
    return render_template("register.html", name="", email="")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        key = (request.remote_addr, email)
        if throttled(key):
            flash("Too many attempts. Wait ten minutes and try again.", "error")
            return render_template("login.html", email=email), 429
        u = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if u and check_password_hash(u["password_hash"], pw):
            FAILS.pop(key, None)
            start_session(u["id"])
            dest = url_for("admin_dashboard") if u["is_admin"] else url_for("home")
            return redirect(safe_next(request.args.get("next"), dest))
        rec = FAILS.setdefault(key, [0, time.time()])
        rec[0] += 1
        flash("Email or password is incorrect.", "error")
        return render_template("login.html", email=email), 401
    return render_template("login.html", email="")


@app.post("/logout")
def logout():
    session.clear()  # also empties the bag, which is right for shared computers
    flash("You are logged out.", "info")
    return redirect(url_for("home"))


@app.route("/account")
@login_required
def account():
    orders = get_db().execute(
        "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (g.user["id"],)).fetchall()
    return render_template("account.html", orders=orders)


@app.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        cur_pw = request.form.get("current", "")
        new_pw = request.form.get("new", "")
        if not check_password_hash(g.user["password_hash"], cur_pw):
            flash("Your current password is incorrect.", "error")
        elif len(new_pw) < 8:
            flash("Use a new password with at least 8 characters.", "error")
        else:
            get_db().execute("UPDATE users SET password_hash=? WHERE id=?",
                             (generate_password_hash(new_pw), g.user["id"]))
            flash("Password changed.", "ok")
            return redirect(url_for("account"))
    return render_template("password.html")


# ---- checkout & orders -----------------------------------------------------
PHONE_RE = re.compile(r"^[6-9]\d{9}$")
PIN_RE = re.compile(r"^\d{6}$")


class OutOfStock(Exception):
    pass


@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    cart = build_cart()
    if not cart["lines"]:
        flash("Your bag is empty.", "info")
        return redirect(url_for("bag"))
    form = {k: request.form.get(k, "").strip() for k in
            ("name", "phone", "address", "city", "state", "pincode", "payment")}
    if request.method == "GET":
        form["name"] = g.user["name"]
        form["payment"] = "cod"
    else:
        err = None
        if not form["name"]:
            err = "Enter the name for delivery."
        elif not PHONE_RE.match(form["phone"]):
            err = "Enter a 10-digit mobile number."
        elif len(form["address"]) < 6:
            err = "Enter the full delivery address."
        elif not form["city"] or not form["state"]:
            err = "Enter the city and state."
        elif not PIN_RE.match(form["pincode"]):
            err = "Enter a 6-digit pincode."
        elif form["payment"] not in PAYMENT_LABELS:
            err = "Choose a payment method."
        if err:
            flash(err, "error")
        else:
            db = get_db()
            db.execute("BEGIN IMMEDIATE")
            try:
                cart = build_cart()  # re-price (products AND offer) inside the lock
                if not cart["lines"]:
                    raise OutOfStock("Your bag is empty.")
                for ln in cart["lines"]:
                    cur = db.execute(
                        "UPDATE products SET stock=stock-? WHERE id=? AND active=1 AND stock>=?",
                        (ln["qty"], ln["p"]["id"], ln["qty"]))
                    if cur.rowcount == 0:
                        raise OutOfStock(f"{ln['p']['name']} no longer has enough stock. Update your bag.")
                paid = "Paid" if form["payment"] == "demo" else "Unpaid"
                offer = cart["offer"]
                label = ""
                if offer:
                    label = offer["name"] + (f" ({offer['code']})" if offer["code"] else "")
                cur = db.execute(
                    "INSERT INTO orders(user_id,mrp_total,subtotal,discount,discount_label,offer_id,"
                    "shipping,total,ship_name,ship_phone,ship_address,ship_city,ship_state,"
                    "ship_pincode,payment_method,payment_status) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (g.user["id"], cart["mrp_total"], cart["subtotal"], cart["discount"], label,
                     offer["id"] if offer else None, cart["shipping"], cart["total"],
                     form["name"], form["phone"], form["address"], form["city"], form["state"],
                     form["pincode"], form["payment"], paid))
                oid = cur.lastrowid
                db.executemany(
                    "INSERT INTO order_items(order_id,product_id,name,mrp,price,qty) VALUES(?,?,?,?,?,?)",
                    [(oid, l["p"]["id"], l["p"]["name"], max(l["p"]["mrp"], l["p"]["price"]),
                      l["p"]["price"], l["qty"]) for l in cart["lines"]])
                db.execute("COMMIT")
            except OutOfStock as e:
                db.execute("ROLLBACK")
                flash(str(e), "error")
                return redirect(url_for("bag"))
            except Exception:
                db.execute("ROLLBACK")
                raise
            session.pop("bag", None)
            session.pop("coupon", None)
            flash("Order placed. Thank you.", "ok")
            return redirect(url_for("order_view", oid=oid))
    return render_template("checkout.html", cart=cart, f=form)


def cancel_order(db, oid):
    """Cancel an order and return its stock. Caller decides who may do this."""
    db.execute("BEGIN IMMEDIATE")
    try:
        o = db.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()
        if not o or o["status"] == "Cancelled":
            db.execute("ROLLBACK")
            return False
        for it in db.execute("SELECT product_id, qty FROM order_items WHERE order_id=?", (oid,)):
            if it["product_id"]:
                db.execute("UPDATE products SET stock=stock+? WHERE id=?", (it["qty"], it["product_id"]))
        db.execute("UPDATE orders SET status='Cancelled' WHERE id=?", (oid,))
        db.execute("COMMIT")
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise


@app.route("/orders/<int:oid>")
@login_required
def order_view(oid):
    db = get_db()
    o = db.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (oid, g.user["id"])).fetchone()
    if not o:
        abort(404)
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (oid,)).fetchall()
    return render_template("order.html", o=o, items=items)


@app.post("/orders/<int:oid>/cancel")
@login_required
def order_cancel(oid):
    db = get_db()
    o = db.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (oid, g.user["id"])).fetchone()
    if not o:
        abort(404)
    if o["status"] != "Pending":
        flash("This order has already been confirmed. Contact the store to change it.", "error")
    elif cancel_order(db, oid):
        flash("Order cancelled.", "ok")
    return redirect(url_for("order_view", oid=oid))


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------
LOW_STOCK = 3


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    one = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    stats = {
        "orders": one("SELECT COUNT(*) FROM orders"),
        "pending": one("SELECT COUNT(*) FROM orders WHERE status='Pending'"),
        "revenue": one("SELECT COALESCE(SUM(total),0) FROM orders WHERE status!='Cancelled'"),
        "products": one("SELECT COUNT(*) FROM products WHERE active=1"),
        "customers": one("SELECT COUNT(*) FROM users WHERE is_admin=0"),
        "discounts": one("SELECT COALESCE(SUM(discount),0) FROM orders WHERE status!='Cancelled'"),
    }
    low = db.execute("SELECT * FROM products WHERE active=1 AND stock<=? ORDER BY stock, name",
                     (LOW_STOCK,)).fetchall()
    recent = db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 8").fetchall()
    return render_template("admin/dashboard.html", s=stats, low=low, recent=recent, low_at=LOW_STOCK)


@app.route("/admin/products")
@admin_required
def admin_products():
    q = request.args.get("q", "").strip()
    sql = ("SELECT p.*, c.name AS cat_name FROM products p LEFT JOIN categories c ON c.id=p.category_id")
    params = []
    if q:
        sql += " WHERE p.name LIKE ?"
        params.append(f"%{q}%")
    rows = get_db().execute(sql + " ORDER BY p.id DESC", params).fetchall()
    return render_template("admin/products.html", rows=rows, q=q)


def read_product_form():
    f = request.form
    data = {
        "name": f.get("name", "").strip(),
        "description": f.get("description", "").strip(),
        "category_id": f.get("category_id", type=int),
        "material": f.get("material", "").strip(),
        "mrp": f.get("mrp", type=int),
        "price": f.get("price", type=int),
        "stock": f.get("stock", type=int),
        "active": 1 if f.get("active") else 0,
    }
    err = None
    if not data["name"]:
        err = "Enter a product name."
    elif data["price"] is None or data["price"] < 0:
        err = "Enter the selling price in whole rupees."
    elif data["mrp"] is not None and data["mrp"] < data["price"]:
        err = "The selling price can't be higher than the actual price (MRP)."
    elif data["stock"] is None or data["stock"] < 0:
        err = "Enter the stock as a whole number, 0 or more."
    if err is None and data["mrp"] is None:
        data["mrp"] = data["price"]  # no actual price given means no discount
    return data, err


@app.route("/admin/products/new", methods=["GET", "POST"])
@admin_required
def admin_product_new():
    db = get_db()
    cats = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    if request.method == "POST":
        data, err = read_product_form()
        image = None
        if not err:
            try:
                image = save_upload(request.files.get("image"))
            except ValueError as e:
                err = str(e)
        if err:
            flash(err, "error")
            return render_template("admin/product_form.html", p=data, cats=cats, is_new=True), 400
        db.execute(
            "INSERT INTO products(name,description,category_id,material,mrp,price,stock,image,active) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (data["name"], data["description"], data["category_id"], data["material"],
             data["mrp"], data["price"], data["stock"], image, data["active"]))
        flash("Product added.", "ok")
        return redirect(url_for("admin_products"))
    return render_template("admin/product_form.html", p={"active": 1, "stock": 1}, cats=cats, is_new=True)


@app.route("/admin/products/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def admin_product_edit(pid):
    db = get_db()
    cur_p = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not cur_p:
        abort(404)
    cats = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    if request.method == "POST":
        data, err = read_product_form()
        image = None
        if not err:
            try:
                image = save_upload(request.files.get("image"))
            except ValueError as e:
                err = str(e)
        if err:
            flash(err, "error")
            data["id"], data["image"] = pid, cur_p["image"]
            return render_template("admin/product_form.html", p=data, cats=cats, is_new=False), 400
        if image:
            remove_upload(cur_p["image"])
        elif request.form.get("remove_image"):
            remove_upload(cur_p["image"])
            image = ""
        new_image = (image or None) if image is not None else cur_p["image"]
        db.execute(
            "UPDATE products SET name=?,description=?,category_id=?,material=?,mrp=?,price=?,stock=?,"
            "image=?,active=? WHERE id=?",
            (data["name"], data["description"], data["category_id"], data["material"],
             data["mrp"], data["price"], data["stock"], new_image, data["active"], pid))
        flash("Product saved.", "ok")
        return redirect(url_for("admin_products"))
    return render_template("admin/product_form.html", p=cur_p, cats=cats, is_new=False)


@app.post("/admin/products/<int:pid>/stock")
@admin_required
def admin_product_stock(pid):
    stock = request.form.get("stock", type=int)
    if stock is None or stock < 0:
        flash("Enter the stock as a whole number, 0 or more.", "error")
    else:
        get_db().execute("UPDATE products SET stock=? WHERE id=?", (stock, pid))
        flash("Stock updated.", "ok")
    return redirect(safe_next(request.form.get("next"), url_for("admin_products")))


@app.post("/admin/products/<int:pid>/toggle")
@admin_required
def admin_product_toggle(pid):
    get_db().execute("UPDATE products SET active = 1 - active WHERE id=?", (pid,))
    return redirect(url_for("admin_products"))


@app.post("/admin/products/<int:pid>/delete")
@admin_required
def admin_product_delete(pid):
    db = get_db()
    p = db.execute("SELECT image FROM products WHERE id=?", (pid,)).fetchone()
    if p:
        db.execute("DELETE FROM products WHERE id=?", (pid,))  # past orders keep their own copy of name/price
        remove_upload(p["image"])
        flash("Product deleted. Past orders keep their details.", "ok")
    return redirect(url_for("admin_products"))


@app.route("/admin/orders")
@admin_required
def admin_orders():
    status = request.args.get("status", "")
    sql = "SELECT o.*, u.name AS cust, u.email FROM orders o JOIN users u ON u.id=o.user_id"
    params = []
    if status in ORDER_STATUSES:
        sql += " WHERE o.status=?"
        params.append(status)
    rows = get_db().execute(sql + " ORDER BY o.id DESC", params).fetchall()
    return render_template("admin/orders.html", rows=rows, status=status)


@app.route("/admin/orders/<int:oid>")
@admin_required
def admin_order(oid):
    db = get_db()
    o = db.execute("SELECT o.*, u.name AS cust, u.email FROM orders o JOIN users u ON u.id=o.user_id "
                   "WHERE o.id=?", (oid,)).fetchone()
    if not o:
        abort(404)
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (oid,)).fetchall()
    return render_template("admin/order.html", o=o, items=items)


@app.post("/admin/orders/<int:oid>/status")
@admin_required
def admin_order_status(oid):
    db = get_db()
    new = request.form.get("status", "")
    o = db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not o or new not in ORDER_STATUSES:
        abort(400)
    if o["status"] == "Cancelled":
        flash("A cancelled order can't be reopened. Ask the customer to place a new order.", "error")
    elif new == "Cancelled":
        cancel_order(db, oid)
        flash("Order cancelled and stock returned.", "ok")
    else:
        db.execute("UPDATE orders SET status=? WHERE id=?", (new, oid))
        if new == "Delivered" and o["payment_method"] == "cod":
            db.execute("UPDATE orders SET payment_status='Paid' WHERE id=?", (oid,))
        flash(f"Order marked {new.lower()}.", "ok")
    return redirect(url_for("admin_order", oid=oid))


@app.route("/admin/categories", methods=["GET", "POST"])
@admin_required
def admin_categories():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Enter a category name.", "error")
        else:
            try:
                db.execute("INSERT INTO categories(name,slug) VALUES(?,?)", (name, slugify(name)))
                flash("Category added.", "ok")
            except sqlite3.IntegrityError:
                flash("A category with that name already exists.", "error")
        return redirect(url_for("admin_categories"))
    rows = db.execute("SELECT c.*, COUNT(p.id) AS n FROM categories c "
                      "LEFT JOIN products p ON p.category_id=c.id GROUP BY c.id ORDER BY c.name").fetchall()
    return render_template("admin/categories.html", rows=rows)


@app.post("/admin/categories/<int:cid>/delete")
@admin_required
def admin_category_delete(cid):
    db = get_db()
    n = db.execute("SELECT COUNT(*) FROM products WHERE category_id=?", (cid,)).fetchone()[0]
    if n:
        flash("Move or delete the products in this category first.", "error")
    else:
        db.execute("DELETE FROM categories WHERE id=?", (cid,))
        flash("Category deleted.", "ok")
    return redirect(url_for("admin_categories"))


@app.route("/admin/customers")
@admin_required
def admin_customers():
    rows = get_db().execute(
        "SELECT u.*, COUNT(o.id) AS orders, COALESCE(SUM(CASE WHEN o.status!='Cancelled' THEN o.total END),0) AS spent "
        "FROM users u LEFT JOIN orders o ON o.user_id=u.id WHERE u.is_admin=0 GROUP BY u.id ORDER BY u.id DESC"
    ).fetchall()
    return render_template("admin/customers.html", rows=rows)


# ---- offers (order-level discounts) -----------------------------------------
CODE_RE = re.compile(r"^[A-Z0-9]{3,20}$")


@app.route("/admin/offers")
@admin_required
def admin_offers():
    rows = get_db().execute(
        "SELECT o.*, "
        "(SELECT COUNT(*) FROM orders x WHERE x.offer_id=o.id AND x.status!='Cancelled') AS used, "
        "(SELECT COALESCE(SUM(x.discount),0) FROM orders x "
        " WHERE x.offer_id=o.id AND x.status!='Cancelled') AS given "
        "FROM offers o ORDER BY o.active DESC, o.id DESC").fetchall()
    return render_template("admin/offers.html", rows=rows)


def read_offer_form():
    f = request.form
    kind = f.get("kind", "")
    data = {
        "name": f.get("name", "").strip(),
        "kind": kind,
        "value": f.get("value", type=int),
        "min_subtotal": f.get("min_subtotal", type=int),
        "max_discount": f.get("max_discount", type=int),
        "code": re.sub(r"\s+", "", f.get("code", "")).upper() or None,
        "expires_on": f.get("expires_on", "").strip() or None,
        "active": 1 if f.get("active") else 0,
    }
    if data["min_subtotal"] is None:
        data["min_subtotal"] = 0
    err = None
    if not data["name"] or len(data["name"]) > 60:
        err = "Enter an offer name of up to 60 characters. Customers see this name."
    elif kind not in ("percent", "flat"):
        err = "Choose percent off or a flat amount off."
    elif data["value"] is None or data["value"] < 1:
        err = "Enter the discount as a whole number, 1 or more."
    elif kind == "percent" and data["value"] > 90:
        err = "A percentage offer can be 90% at most."
    elif data["min_subtotal"] < 0:
        err = "The minimum order can't be negative."
    elif kind == "flat" and data["min_subtotal"] <= data["value"]:
        err = ("For a flat discount, set a minimum order higher than the discount, "
               "so an order can never become free.")
    elif data["max_discount"] is not None and data["max_discount"] < 1:
        err = "The maximum discount must be 1 or more, or left blank."
    elif data["code"] and not CODE_RE.match(data["code"]):
        err = "Use 3 to 20 letters or numbers for the coupon code, with no spaces or symbols."
    elif data["expires_on"]:
        try:
            date.fromisoformat(data["expires_on"])
        except ValueError:
            err = "Enter the last valid day as a real date."
    if kind != "percent":
        data["max_discount"] = None
    return data, err


@app.route("/admin/offers/new", methods=["GET", "POST"])
@admin_required
def admin_offer_new():
    if request.method == "POST":
        data, err = read_offer_form()
        if not err:
            try:
                get_db().execute(
                    "INSERT INTO offers(name,code,kind,value,min_subtotal,max_discount,expires_on,active)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (data["name"], data["code"], data["kind"], data["value"], data["min_subtotal"],
                     data["max_discount"], data["expires_on"], data["active"]))
                flash("Offer added.", "ok")
                return redirect(url_for("admin_offers"))
            except sqlite3.IntegrityError:
                err = "Another offer already uses this coupon code."
        flash(err, "error")
        return render_template("admin/offer_form.html", o=data, is_new=True), 400
    return render_template("admin/offer_form.html", is_new=True,
                           o={"kind": "percent", "active": 1, "min_subtotal": 0})


@app.route("/admin/offers/<int:oid>/edit", methods=["GET", "POST"])
@admin_required
def admin_offer_edit(oid):
    db = get_db()
    cur_o = db.execute("SELECT * FROM offers WHERE id=?", (oid,)).fetchone()
    if not cur_o:
        abort(404)
    if request.method == "POST":
        data, err = read_offer_form()
        if not err:
            try:
                db.execute(
                    "UPDATE offers SET name=?,code=?,kind=?,value=?,min_subtotal=?,max_discount=?,"
                    "expires_on=?,active=? WHERE id=?",
                    (data["name"], data["code"], data["kind"], data["value"], data["min_subtotal"],
                     data["max_discount"], data["expires_on"], data["active"], oid))
                flash("Offer saved.", "ok")
                return redirect(url_for("admin_offers"))
            except sqlite3.IntegrityError:
                err = "Another offer already uses this coupon code."
        flash(err, "error")
        return render_template("admin/offer_form.html", o=data, is_new=False), 400
    return render_template("admin/offer_form.html", o=cur_o, is_new=False)


@app.post("/admin/offers/<int:oid>/toggle")
@admin_required
def admin_offer_toggle(oid):
    get_db().execute("UPDATE offers SET active = 1 - active WHERE id=?", (oid,))
    return redirect(url_for("admin_offers"))


@app.post("/admin/offers/<int:oid>/delete")
@admin_required
def admin_offer_delete(oid):
    get_db().execute("DELETE FROM offers WHERE id=?", (oid,))  # past orders keep their own offer label
    flash("Offer deleted. Past orders keep their details.", "ok")
    return redirect(url_for("admin_offers"))


# ---- errors ------------------------------------------------------------------
@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
def error_page(e):
    msgs = {400: ("Something went wrong", getattr(e, "description", "")),
            403: ("You can't open this page", "This area is for store admins."),
            404: ("Page not found", "The page may have moved, or the piece may no longer be on sale."),
            413: ("That file is too large", "Upload an image under 3 MB.")}
    title, text = msgs[e.code]
    return render_template("error.html", title=title, text=text), e.code


with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 10000)),
            debug=os.environ.get("FLASK_DEBUG") == "1")
