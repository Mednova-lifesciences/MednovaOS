BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS crm_reports_invalid (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crm_company_id INTEGER,
    report_type TEXT,
    report_name TEXT,
    report_data TEXT,
    executive_summary TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    quarantined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE crm_reports_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crm_company_id INTEGER NOT NULL,
    report_type TEXT,
    report_name TEXT,
    report_data TEXT,
    executive_summary TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (crm_company_id) REFERENCES crm_companies(id) ON DELETE CASCADE
);

INSERT INTO crm_reports_new (id, crm_company_id, report_type, report_name, report_data, executive_summary, created_at, updated_at)
SELECT id, crm_company_id, report_type, report_name, report_data, executive_summary, created_at, updated_at
FROM crm_reports
WHERE crm_company_id IS NOT NULL;

INSERT OR REPLACE INTO crm_reports_invalid (id, crm_company_id, report_type, report_name, report_data, executive_summary, created_at, updated_at, quarantined_at)
SELECT id, crm_company_id, report_type, report_name, report_data, executive_summary, created_at, updated_at, CURRENT_TIMESTAMP
FROM crm_reports
WHERE crm_company_id IS NULL;

DROP TABLE crm_reports;
ALTER TABLE crm_reports_new RENAME TO crm_reports;

COMMIT;
