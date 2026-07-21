CREATE TABLE IF NOT EXISTS crm_companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    country TEXT,
    opportunity_score INTEGER DEFAULT 0,
    portfolio_summary TEXT,
    source TEXT,
    report_context TEXT,
    greenbook_products_json TEXT,
    registration_numbers TEXT,
    dosage_forms TEXT,
    therapeutic_areas TEXT,
    registration_dates TEXT,
    opportunity_status TEXT DEFAULT 'New',
    pipeline_stage TEXT DEFAULT 'Lead',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (company_name)
);

CREATE TABLE IF NOT EXISTS crm_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crm_company_id INTEGER NOT NULL,
    activity_type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS crm_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crm_company_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE
);
