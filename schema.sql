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
    low_stock_threshold INTEGER NOT NULL DEFAULT 10
);

CREATE TABLE medicine_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    qty_in_base_units INTEGER NOT NULL,
    price REAL NOT NULL,
    is_sellable INTEGER NOT NULL DEFAULT 1,
    UNIQUE(medicine_id, unit_name)
);

CREATE TABLE sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    timestamp TEXT NOT NULL,
    total REAL NOT NULL,
    voided INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    subtotal REAL NOT NULL
);

CREATE TABLE photo_tokens (
    token TEXT PRIMARY KEY,
    photo_path TEXT,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
