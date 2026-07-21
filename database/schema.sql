PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS manufacturers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nafdac_manufacturer_id TEXT,
    manufacturer_name TEXT NOT NULL,
    country TEXT,
    address TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (nafdac_manufacturer_id)
);

CREATE TABLE IF NOT EXISTS applicants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nafdac_applicant_id TEXT,
    applicant_name TEXT NOT NULL,
    address TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (nafdac_applicant_id)
);

CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_name TEXT NOT NULL,
    synonym TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ingredient_name)
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nafdac_category_id TEXT,
    category_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (nafdac_category_id),
    UNIQUE (category_name)
);

CREATE TABLE IF NOT EXISTS dosage_forms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nafdac_form_id TEXT,
    form_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (nafdac_form_id),
    UNIQUE (form_name)
);

CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nafdac_route_id TEXT,
    route_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (nafdac_route_id),
    UNIQUE (route_name)
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nafdac_product_id TEXT,
    registration_number TEXT,
    product_name TEXT NOT NULL,
    generic_name TEXT,
    active_ingredient TEXT,
    strength TEXT,
    dosage_form_id INTEGER,
    route_id INTEGER,
    category_id INTEGER,
    atc_code TEXT,
    description TEXT,
    pack_size TEXT,
    composition TEXT,
    approval_date TEXT,
    expiry_date TEXT,
    status TEXT,
    applicant_id INTEGER,
    manufacturer_id INTEGER,
    source_last_updated TEXT,
    synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dosage_form_id) REFERENCES dosage_forms(id),
    FOREIGN KEY (route_id) REFERENCES routes(id),
    FOREIGN KEY (category_id) REFERENCES categories(id),
    FOREIGN KEY (applicant_id) REFERENCES applicants(id),
    FOREIGN KEY (manufacturer_id) REFERENCES manufacturers(id),
    UNIQUE (registration_number),
    UNIQUE (nafdac_product_id)
);

CREATE TABLE IF NOT EXISTS product_ingredients (
    product_id INTEGER NOT NULL,
    ingredient_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (product_id, ingredient_id),
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    status TEXT NOT NULL,
    products_added INTEGER NOT NULL DEFAULT 0,
    products_updated INTEGER NOT NULL DEFAULT 0,
    products_removed INTEGER NOT NULL DEFAULT 0,
    duration_seconds INTEGER,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS product_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS renewal_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    expiry_date TEXT,
    days_remaining INTEGER,
    alert_level TEXT NOT NULL CHECK (alert_level IN ('GREEN', 'YELLOW', 'RED', 'EXPIRED')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS search_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text TEXT NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    response_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (query_text)
);

CREATE INDEX IF NOT EXISTS idx_products_registration_number ON products(registration_number);
CREATE INDEX IF NOT EXISTS idx_products_product_name ON products(product_name);
CREATE INDEX IF NOT EXISTS idx_products_expiry_date ON products(expiry_date);
CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
CREATE INDEX IF NOT EXISTS idx_products_manufacturer_id ON products(manufacturer_id);
CREATE INDEX IF NOT EXISTS idx_products_applicant_id ON products(applicant_id);
CREATE INDEX IF NOT EXISTS idx_products_active_ingredient ON products(active_ingredient);
CREATE INDEX IF NOT EXISTS idx_products_approval_date ON products(approval_date);
CREATE INDEX IF NOT EXISTS idx_products_category_id ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_dosage_form_id ON products(dosage_form_id);
CREATE INDEX IF NOT EXISTS idx_products_route_id ON products(route_id);
CREATE INDEX IF NOT EXISTS idx_renewal_alerts_product_id ON renewal_alerts(product_id);
CREATE INDEX IF NOT EXISTS idx_product_changes_product_id ON product_changes(product_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_product_id ON watchlist(product_id);
