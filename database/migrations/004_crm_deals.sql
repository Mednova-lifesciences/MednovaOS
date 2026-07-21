CREATE TABLE IF NOT EXISTS crm_deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crm_company_id INTEGER NOT NULL,
    crm_contact_id INTEGER,
    title TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'lead',
    value NUMERIC NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    probability INTEGER NOT NULL DEFAULT 0,
    expected_close_at TEXT,
    owner TEXT,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE,
    FOREIGN KEY (crm_contact_id) REFERENCES crm_contacts(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_crm_deals_company_id ON crm_deals(crm_company_id);
CREATE INDEX IF NOT EXISTS idx_crm_deals_stage ON crm_deals(stage);
CREATE INDEX IF NOT EXISTS idx_crm_deals_owner ON crm_deals(owner);
