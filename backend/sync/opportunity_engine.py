from __future__ import annotations

import sqlite3
from typing import Any

from .utils import iso_now


class OpportunityEngine:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def refresh(self) -> None:
        self.conn.execute("DELETE FROM opportunities")
        rows = self.conn.execute(
            """
            SELECT p.id, p.product_name, p.registration_number, p.expiry_date, p.status,
                   c.category_name, a.applicant_name, m.manufacturer_name
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN applicants a ON a.id = p.applicant_id
            LEFT JOIN manufacturers m ON m.id = p.manufacturer_id
            """
        ).fetchall()
        for row in rows:
            product_id = int(row[0])
            product_name = row[1]
            registration_number = row[2]
            expiry_date = row[3]
            status = row[4]
            category_name = row[5]
            applicant_name = row[6]
            manufacturer_name = row[7]
            if status and status.lower() == "inactive":
                self._upsert_opportunity(product_id, "Registration inactive", f"{product_name} is inactive", "inactive")
            if expiry_date:
                self._upsert_opportunity(product_id, "Expiring registration", f"{product_name} expires on {expiry_date}", "expiring")
            if manufacturer_name:
                self._upsert_opportunity(product_id, "Manufacturer renewal watch", f"Renewal watch for {manufacturer_name}", "manufacturer")
            if applicant_name and category_name:
                self._upsert_opportunity(product_id, "New approval opportunity", f"{applicant_name} has {category_name} product {product_name}", "approval")

    def _upsert_opportunity(self, product_id: int, title: str, description: str, category: str) -> None:
        existing = self.conn.execute(
            "SELECT id FROM opportunities WHERE product_id = ? AND title = ?",
            (product_id, title),
        ).fetchone()
        now = iso_now()
        if existing:
            self.conn.execute(
                "UPDATE opportunities SET description = ?, category = ?, updated_at = ? WHERE id = ?",
                (description, category, now, int(existing[0])),
            )
        else:
            self.conn.execute(
                "INSERT INTO opportunities (product_id, title, description, category, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (product_id, title, description, category, now, now),
            )
