CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'staff'))
);

CREATE TABLE companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    phone TEXT,
    address TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE medicines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    packaging_type TEXT NOT NULL CHECK(packaging_type IN ('box_file', 'bottled_other')),
    photo_path TEXT,
    stock_in_base_units INTEGER NOT NULL DEFAULT 0,
    low_stock_threshold INTEGER NOT NULL DEFAULT 10,
    max_discount_percent REAL NOT NULL DEFAULT 0 CHECK(max_discount_percent >= 0 AND max_discount_percent <= 100),
    cost_price_per_base_unit REAL NOT NULL DEFAULT 0 CHECK(cost_price_per_base_unit >= 0),
    mrp_per_base_unit REAL NOT NULL DEFAULT 0 CHECK(mrp_per_base_unit >= 0),
    company_id INTEGER REFERENCES companies(id),
    packing TEXT
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
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    code TEXT
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

CREATE TABLE stock_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    qty_in_base_units INTEGER NOT NULL,
    base_units_received INTEGER NOT NULL,
    cost_currency TEXT NOT NULL DEFAULT 'NPR' CHECK(cost_currency IN ('NPR', 'INR')),
    cost_price_original REAL NOT NULL CHECK(cost_price_original >= 0),
    cost_price_per_base_unit REAL NOT NULL CHECK(cost_price_per_base_unit >= 0),
    mrp_per_base_unit REAL NOT NULL CHECK(mrp_per_base_unit >= 0),
    purchase_bill_id INTEGER REFERENCES purchase_bills(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    batch_number TEXT,
    expiry_date TEXT,
    mrp_currency TEXT NOT NULL DEFAULT 'NPR' CHECK(mrp_currency IN ('NPR', 'INR')),
    mrp_original REAL
);

CREATE TABLE purchase_returns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_bill_id INTEGER NOT NULL REFERENCES purchase_bills(id),
    return_date TEXT NOT NULL,
    reason TEXT,
    total_amount REAL NOT NULL DEFAULT 0 CHECK(total_amount >= 0),
    recorded_by_user_id INTEGER NOT NULL REFERENCES users(id),
    voided INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE purchase_return_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_return_id INTEGER NOT NULL REFERENCES purchase_returns(id),
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    qty_in_base_units INTEGER NOT NULL,
    base_units_returned INTEGER NOT NULL,
    cost_price_per_base_unit REAL NOT NULL,
    amount REAL NOT NULL,
    batch_number TEXT
);

CREATE TABLE stock_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    qty_in_base_units INTEGER NOT NULL,
    base_units_delta INTEGER NOT NULL,
    reason TEXT NOT NULL CHECK(reason IN ('damaged', 'lost', 'found', 'correction', 'other')),
    note TEXT,
    recorded_by_user_id INTEGER NOT NULL REFERENCES users(id),
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
    patient_name TEXT,
    subtotal_before_discount REAL NOT NULL DEFAULT 0,
    discount_mode TEXT NOT NULL DEFAULT 'none' CHECK(discount_mode IN ('none', 'item', 'bill')),
    bill_discount_percent REAL NOT NULL DEFAULT 0,
    discount_amount REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL,
    voided INTEGER NOT NULL DEFAULT 0,
    doctor_name TEXT,
    payment_method TEXT NOT NULL DEFAULT 'cash' CHECK(payment_method IN ('cash', 'online')),
    tender_amount REAL,
    change_amount REAL
);

CREATE TABLE sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    qty_in_base_units INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    cost_price_per_base_unit REAL NOT NULL,
    mrp_per_base_unit REAL NOT NULL,
    gross_unit_price REAL NOT NULL,
    discount_percent REAL NOT NULL DEFAULT 0,
    unit_price REAL NOT NULL,
    subtotal REAL NOT NULL
);

CREATE TABLE sale_returns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    return_date TEXT NOT NULL,
    reason TEXT,
    total_amount REAL NOT NULL DEFAULT 0 CHECK(total_amount >= 0),
    recorded_by_user_id INTEGER NOT NULL REFERENCES users(id),
    voided INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE sale_return_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_return_id INTEGER NOT NULL REFERENCES sale_returns(id),
    sale_item_id INTEGER NOT NULL REFERENCES sale_items(id),
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    qty_in_base_units INTEGER NOT NULL,
    base_units_returned INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    amount REAL NOT NULL
);

CREATE TABLE photo_tokens (
    token TEXT PRIMARY KEY,
    photo_path TEXT,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX idx_vendors_code ON vendors(code);
CREATE INDEX idx_purchase_bills_bill_date ON purchase_bills(bill_date);
CREATE INDEX idx_stock_receipts_purchase_bill_id ON stock_receipts(purchase_bill_id);
