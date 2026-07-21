PRAGMA foreign_keys = OFF;

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

CREATE TABLE IF NOT EXISTS crm_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crm_company_id INTEGER NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT,
    department TEXT,
    email TEXT,
    phone TEXT,
    source TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_url TEXT,
    discovered_at TEXT,
    confidence_score REAL,
    verification_status TEXT,
    website TEXT,
    linkedin_url TEXT,
    notes TEXT,
    FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS crm_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crm_company_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    task_type TEXT NOT NULL DEFAULT 'follow-up',
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT NOT NULL DEFAULT 'medium',
    due_date TEXT,
    assigned_to TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE
);

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

CREATE TABLE IF NOT EXISTS crm_outreach_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crm_company_id INTEGER NOT NULL,
    crm_contact_id INTEGER,
    template_key TEXT,
    template_name TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    recipient TEXT,
    recipient_name TEXT,
    sender_name TEXT,
    sender_email TEXT,
    from_email TEXT,
    company_name TEXT,
    contact_name TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    direction TEXT NOT NULL DEFAULT 'outbound',
    message_id TEXT,
    error_message TEXT,
    client_request_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TEXT,
    FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE,
    FOREIGN KEY (crm_contact_id) REFERENCES crm_contacts(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_crm_contacts_company_id ON crm_contacts(crm_company_id);
CREATE INDEX IF NOT EXISTS idx_crm_tasks_company_id ON crm_tasks(crm_company_id);
CREATE INDEX IF NOT EXISTS idx_crm_tasks_status ON crm_tasks(status);
CREATE INDEX IF NOT EXISTS idx_crm_tasks_due_date ON crm_tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_crm_activities_company_id ON crm_activities(crm_company_id);
CREATE INDEX IF NOT EXISTS idx_crm_notes_company_id ON crm_notes(crm_company_id);
CREATE INDEX IF NOT EXISTS idx_crm_deals_company_id ON crm_deals(crm_company_id);
CREATE INDEX IF NOT EXISTS idx_crm_deals_stage ON crm_deals(stage);
CREATE INDEX IF NOT EXISTS idx_crm_deals_owner ON crm_deals(owner);
CREATE INDEX IF NOT EXISTS idx_crm_outreach_company ON crm_outreach_emails(crm_company_id);
CREATE INDEX IF NOT EXISTS idx_crm_outreach_status ON crm_outreach_emails(status);
CREATE INDEX IF NOT EXISTS idx_crm_outreach_created ON crm_outreach_emails(created_at);

-- Add missing columns to existing tables if they were created by earlier migrations.
ALTER TABLE crm_contacts ADD COLUMN source_url TEXT;
ALTER TABLE crm_contacts ADD COLUMN discovered_at TEXT;
ALTER TABLE crm_contacts ADD COLUMN confidence_score REAL;
ALTER TABLE crm_contacts ADD COLUMN verification_status TEXT;
ALTER TABLE crm_contacts ADD COLUMN website TEXT;
ALTER TABLE crm_contacts ADD COLUMN linkedin_url TEXT;
ALTER TABLE crm_contacts ADD COLUMN notes TEXT;

ALTER TABLE crm_outreach_emails ADD COLUMN template_key TEXT;
ALTER TABLE crm_outreach_emails ADD COLUMN template_name TEXT;
ALTER TABLE crm_outreach_emails ADD COLUMN recipient_name TEXT;
ALTER TABLE crm_outreach_emails ADD COLUMN sender_name TEXT;
ALTER TABLE crm_outreach_emails ADD COLUMN sender_email TEXT;
ALTER TABLE crm_outreach_emails ADD COLUMN from_email TEXT;
ALTER TABLE crm_outreach_emails ADD COLUMN company_name TEXT;
ALTER TABLE crm_outreach_emails ADD COLUMN contact_name TEXT;
ALTER TABLE crm_outreach_emails ADD COLUMN message_id TEXT;
ALTER TABLE crm_outreach_emails ADD COLUMN error_message TEXT;
ALTER TABLE crm_outreach_emails ADD COLUMN client_request_id TEXT;

PRAGMA foreign_keys = ON;
