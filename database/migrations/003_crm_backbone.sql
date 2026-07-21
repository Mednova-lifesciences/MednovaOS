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

CREATE INDEX IF NOT EXISTS idx_crm_contacts_company_id ON crm_contacts(crm_company_id);
CREATE INDEX IF NOT EXISTS idx_crm_tasks_company_id ON crm_tasks(crm_company_id);
CREATE INDEX IF NOT EXISTS idx_crm_tasks_status ON crm_tasks(status);
CREATE INDEX IF NOT EXISTS idx_crm_tasks_due_date ON crm_tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_crm_activities_company_id ON crm_activities(crm_company_id);
CREATE INDEX IF NOT EXISTS idx_crm_notes_company_id ON crm_notes(crm_company_id);
