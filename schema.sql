CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'staff'))
);

CREATE TABLE medicines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    packaging_type TEXT NOT NULL CHECK(packaging_type IN ('box_file', 'bottled_other')),
    photo_path TEXT,
    stock_in_base_units INTEGER NOT NULL DEFAULT 0,
    low_stock_threshold INTEGER NOT NULL DEFAULT 10,
    max_discount_percent REAL NOT NULL DEFAULT 0 CHECK(max_discount_percent >= 0 AND max_discount_percent <= 100)
);

CREATE TABLE medicine_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    qty_in_base_units INTEGER NOT NULL,
    is_sellable INTEGER NOT NULL DEFAULT 1,
    UNIQUE(medicine_id, unit_name)
);

CREATE TABLE vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    phone TEXT,
    address TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE purchase_bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    bill_date TEXT NOT NULL,
    vendor_bill_reference TEXT,
    bill_image_path TEXT,
    total_amount REAL NOT NULL DEFAULT 0 CHECK(total_amount >= 0),
    recorded_by_user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE medicine_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    expiry_date TEXT NOT NULL,
    cost_price_per_base_unit REAL NOT NULL CHECK(cost_price_per_base_unit >= 0),
    mrp_per_base_unit REAL NOT NULL CHECK(mrp_per_base_unit >= 0),
    quantity_received INTEGER NOT NULL DEFAULT 0,
    quantity_remaining INTEGER NOT NULL DEFAULT 0,
    purchase_bill_id INTEGER REFERENCES purchase_bills(id),
    cost_currency TEXT NOT NULL DEFAULT 'NPR' CHECK(cost_currency IN ('NPR', 'INR')),
    cost_price_original REAL NOT NULL CHECK(cost_price_original >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE purchase_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_bill_id INTEGER NOT NULL REFERENCES purchase_bills(id),
    amount REAL NOT NULL CHECK(amount > 0),
    paid_at TEXT NOT NULL,
    note TEXT,
    recorded_by_user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    timestamp TEXT NOT NULL,
    subtotal_before_discount REAL NOT NULL DEFAULT 0,
    discount_mode TEXT NOT NULL DEFAULT 'none' CHECK(discount_mode IN ('none', 'item', 'bill')),
    bill_discount_percent REAL NOT NULL DEFAULT 0,
    discount_amount REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL,
    voided INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    qty_in_base_units INTEGER NOT NULL,
    batch_id INTEGER NOT NULL REFERENCES medicine_batches(id),
    quantity INTEGER NOT NULL,
    cost_price_per_base_unit REAL NOT NULL,
    mrp_per_base_unit REAL NOT NULL,
    gross_unit_price REAL NOT NULL,
    discount_percent REAL NOT NULL DEFAULT 0,
    unit_price REAL NOT NULL,
    subtotal REAL NOT NULL
);

CREATE TABLE photo_tokens (
    token TEXT PRIMARY KEY,
    photo_path TEXT,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
