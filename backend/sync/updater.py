from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .utils import iso_now, safe_text


class SyncUpdater:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.lookup_stats: dict[str, dict[str, int]] = {}

    def ensure_lookup(self, table: str, lookup_field: str, value: str | None, lookup_id_field: str) -> int | None:
        if not value:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        stats = self.lookup_stats.setdefault(table, {"lookups": 0, "inserted": 0, "updated": 0})
        stats["lookups"] += 1
        cursor = self.conn.execute(f"SELECT id FROM {table} WHERE {lookup_field} = ?", (normalized,))
        row = cursor.fetchone()
        if row:
            return int(row[0])
        self.conn.execute(
            f"INSERT INTO {table} ({lookup_field}, created_at, updated_at) VALUES (?, ?, ?)",
            (normalized, iso_now(), iso_now()),
        )
        stats["inserted"] += 1
        return int(self.conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def get_lookup_stats(self) -> dict[str, dict[str, int]]:
        return self.lookup_stats

    def upsert_product(self, record: dict[str, Any]) -> tuple[str, int]:
        now = iso_now()
        registration_number = safe_text(record.get("registration_number"))
        if not registration_number:
            return ("skipped", 0)

        existing = self.conn.execute(
            "SELECT id, registration_number, product_name, generic_name, active_ingredient, strength, dosage_form_id, route_id, category_id, description, pack_size, composition, approval_date, expiry_date, status, applicant_id, manufacturer_id, source_last_updated FROM products WHERE registration_number = ?",
            (registration_number,),
        ).fetchone()

        manufacturer_id = self.ensure_lookup("manufacturers", "manufacturer_name", record.get("manufacturer_name"), "id")
        applicant_id = self.ensure_lookup("applicants", "applicant_name", record.get("applicant_name"), "id")
        category_id = self.ensure_lookup("categories", "category_name", record.get("category_name"), "id")
        route_id = self.ensure_lookup("routes", "route_name", record.get("route_name"), "id")
        dosage_form_id = self.ensure_lookup("dosage_forms", "form_name", record.get("dosage_form_name"), "id")

        if existing:
            product_id = int(existing[0])
            changes = []
            fields = [
                ("product_name", existing[1], record.get("product_name")),
                ("generic_name", existing[2], record.get("generic_name")),
                ("active_ingredient", existing[3], record.get("active_ingredient")),
                ("strength", existing[4], record.get("strength")),
                ("dosage_form_id", existing[5], dosage_form_id),
                ("route_id", existing[6], route_id),
                ("category_id", existing[7], category_id),
                ("description", existing[8], record.get("description")),
                ("pack_size", existing[9], record.get("pack_size")),
                ("composition", existing[10], record.get("composition")),
                ("approval_date", existing[11], record.get("approval_date")),
                ("expiry_date", existing[12], record.get("expiry_date")),
                ("status", existing[13], record.get("status")),
                ("applicant_id", existing[14], applicant_id),
                ("manufacturer_id", existing[15], manufacturer_id),
                ("source_last_updated", existing[16], record.get("source_last_updated")),
            ]
            for field_name, old_value, new_value in fields:
                if str(old_value or "") != str(new_value or ""):
                    self.conn.execute(
                        "INSERT INTO product_changes (product_id, field_name, old_value, new_value, changed_at) VALUES (?, ?, ?, ?, ?)",
                        (product_id, field_name, str(old_value or ""), str(new_value or ""), now),
                    )
                    changes.append(field_name)
            if not changes:
                return ("unchanged", product_id)

            self.conn.execute(
                """
                UPDATE products
                SET product_name = ?, generic_name = ?, active_ingredient = ?, strength = ?,
                    dosage_form_id = ?, route_id = ?, category_id = ?, description = ?, pack_size = ?,
                    composition = ?, approval_date = ?, expiry_date = ?, status = ?, applicant_id = ?,
                    manufacturer_id = ?, source_last_updated = ?, updated_at = ?, synced_at = ?
                WHERE id = ?
                """,
                (
                    safe_text(record.get("product_name")),
                    safe_text(record.get("generic_name")),
                    safe_text(record.get("active_ingredient")),
                    safe_text(record.get("strength")),
                    dosage_form_id,
                    route_id,
                    category_id,
                    safe_text(record.get("description")),
                    safe_text(record.get("pack_size")),
                    safe_text(record.get("composition")),
                    safe_text(record.get("approval_date")),
                    safe_text(record.get("expiry_date")),
                    safe_text(record.get("status")),
                    applicant_id,
                    manufacturer_id,
                    safe_text(record.get("source_last_updated")),
                    now,
                    now,
                    product_id,
                ),
            )
            return ("updated", product_id)

        self.conn.execute(
            """
            INSERT INTO products (
                nafdac_product_id, registration_number, product_name, generic_name, active_ingredient,
                strength, dosage_form_id, route_id, category_id, description, pack_size, composition,
                approval_date, expiry_date, status, applicant_id, manufacturer_id, source_last_updated,
                synced_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                safe_text(record.get("source_product_id")),
                registration_number,
                safe_text(record.get("product_name")),
                safe_text(record.get("generic_name")),
                safe_text(record.get("active_ingredient")),
                safe_text(record.get("strength")),
                dosage_form_id,
                route_id,
                category_id,
                safe_text(record.get("description")),
                safe_text(record.get("pack_size")),
                safe_text(record.get("composition")),
                safe_text(record.get("approval_date")),
                safe_text(record.get("expiry_date")),
                safe_text(record.get("status")),
                applicant_id,
                manufacturer_id,
                safe_text(record.get("source_last_updated")),
                now,
                now,
                now,
            ),
        )
        product_id = int(self.conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        return ("added", product_id)

    def update_renewal_alerts(self) -> None:
        self.conn.execute("DELETE FROM renewal_alerts")
        rows = self.conn.execute("SELECT id, expiry_date FROM products WHERE expiry_date IS NOT NULL").fetchall()
        for product_id, expiry_date in rows:
            try:
                expiry = datetime.fromisoformat(expiry_date)
            except ValueError:
                continue
            days_remaining = (expiry.date() - datetime.now().date()).days
            if days_remaining < 0:
                alert_level = "EXPIRED"
            elif days_remaining < 30:
                alert_level = "RED"
            elif days_remaining < 90:
                alert_level = "YELLOW"
            else:
                alert_level = "GREEN"
            self.conn.execute(
                "INSERT INTO renewal_alerts (product_id, expiry_date, days_remaining, alert_level, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (product_id, expiry_date, days_remaining, alert_level, iso_now(), iso_now()),
            )

    def mark_removed_products(self, active_registration_numbers: set[str]) -> int:
        rows = self.conn.execute("SELECT id, registration_number FROM products WHERE registration_number IS NOT NULL").fetchall()
        removed = 0
        for product_id, registration_number in rows:
            if registration_number in active_registration_numbers:
                continue
            self.conn.execute("UPDATE products SET status = COALESCE(status, 'Unknown') || ' | removed_from_source', updated_at = ? WHERE id = ?", (iso_now(), product_id))
            removed += 1
        return removed
