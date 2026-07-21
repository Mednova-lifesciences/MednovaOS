PRAGMA foreign_keys = ON;

INSERT OR IGNORE INTO categories (nafdac_category_id, category_name) VALUES
    ('CAT-001', 'Prescription Medicine'),
    ('CAT-002', 'Over-the-Counter'),
    ('CAT-003', 'Biological'),
    ('CAT-004', 'Vaccine'),
    ('CAT-005', 'Herbal Medicine'),
    ('CAT-006', 'Cosmetic'),
    ('CAT-007', 'Medical Device'),
    ('CAT-008', 'Diagnostic'),
    ('CAT-009', 'Veterinary'),
    ('CAT-010', 'Nutraceutical');

INSERT OR IGNORE INTO dosage_forms (nafdac_form_id, form_name) VALUES
    ('FORM-001', 'Tablet'),
    ('FORM-002', 'Capsule'),
    ('FORM-003', 'Syrup'),
    ('FORM-004', 'Suspension'),
    ('FORM-005', 'Injection'),
    ('FORM-006', 'Cream'),
    ('FORM-007', 'Ointment'),
    ('FORM-008', 'Gel'),
    ('FORM-009', 'Solution'),
    ('FORM-010', 'Drops'),
    ('FORM-011', 'Inhaler'),
    ('FORM-012', 'Powder'),
    ('FORM-013', 'Patch');

INSERT OR IGNORE INTO routes (nafdac_route_id, route_name) VALUES
    ('ROUTE-001', 'Oral'),
    ('ROUTE-002', 'Intravenous'),
    ('ROUTE-003', 'Intramuscular'),
    ('ROUTE-004', 'Subcutaneous'),
    ('ROUTE-005', 'Topical'),
    ('ROUTE-006', 'Inhalation'),
    ('ROUTE-007', 'Ophthalmic'),
    ('ROUTE-008', 'Otic'),
    ('ROUTE-009', 'Rectal'),
    ('ROUTE-010', 'Vaginal'),
    ('ROUTE-011', 'Nasal'),
    ('ROUTE-012', 'Transdermal'),
    ('ROUTE-013', 'Intrathecal');
