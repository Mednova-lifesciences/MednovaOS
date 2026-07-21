from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from sync.checkpoint import SyncCheckpoint
    from sync.greenbook_client import GreenBookClient
    from sync.hash_engine import build_product_hash
    from sync.logger import configure_logging
    from sync.mapper import GreenBookMapper
    from sync.opportunity_engine import OpportunityEngine
    from sync.renewal_engine import RenewalEngine
    from sync.updater import SyncUpdater
    from sync.utils import get_setting
else:
    from .checkpoint import SyncCheckpoint
    from .greenbook_client import GreenBookClient
    from .hash_engine import build_product_hash
    from .logger import configure_logging
    from .mapper import GreenBookMapper
    from .opportunity_engine import OpportunityEngine
    from .renewal_engine import RenewalEngine
    from .updater import SyncUpdater
    from .utils import get_setting

from backend.cloud.sync_to_supabase import sync_sqlite_to_supabase

ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(get_setting("MEDNOVA_DB_PATH") or get_setting("DATABASE_PATH") or ROOT_DIR / "database" / "nafdac_intelligence.db")


class SyncEngine:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or DB_PATH)
        self.logger = configure_logging()
        self.client = GreenBookClient()
        self.batch_size = int(get_setting("SYNC_BATCH_SIZE", "100"))
        self.timeout = int(get_setting("SYNC_TIMEOUT", "30"))
        self.retries = int(get_setting("SYNC_RETRIES", "4"))

    def _build_revenue_pipeline(self, conn: sqlite3.Connection) -> int:
        conn.execute("DROP TABLE IF EXISTS revenue_pipeline")
        conn.execute(
            """
            CREATE TABLE revenue_pipeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                category TEXT,
                products INTEGER NOT NULL DEFAULT 0,
                estimated_value REAL NOT NULL DEFAULT 0,
                recommended_services TEXT,
                status TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        rows = conn.execute(
            """
            SELECT COALESCE(m.manufacturer_name, a.applicant_name, 'Unknown') AS company,
                   COALESCE(c.category_name, 'Unknown') AS category,
                   COUNT(*) AS products,
                   CASE
                       WHEN COUNT(*) > 0 THEN COUNT(*) * 500000.0
                       ELSE 0
                   END AS estimated_value,
                   CASE
                       WHEN COALESCE(c.category_name, 'Unknown') = 'Medical devices' THEN 'Device registration support, renewal monitoring'
                       ELSE 'Registration support, renewal monitoring'
                   END AS recommended_services,
                   'active' AS status
            FROM products p
            LEFT JOIN manufacturers m ON m.id = p.manufacturer_id
            LEFT JOIN applicants a ON a.id = p.applicant_id
            LEFT JOIN categories c ON c.id = p.category_id
            GROUP BY COALESCE(m.manufacturer_name, a.applicant_name, 'Unknown'), COALESCE(c.category_name, 'Unknown')
            ORDER BY products DESC, estimated_value DESC
            """
        ).fetchall()
        for row in rows:
            conn.execute(
                "INSERT INTO revenue_pipeline (company, category, products, estimated_value, recommended_services, status) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["company"],
                    row["category"],
                    int(row["products"] or 0),
                    float(row["estimated_value"] or 0),
                    row["recommended_services"],
                    row["status"],
                ),
            )
        return len(rows)

    def _build_report(self, conn: sqlite3.Connection) -> dict[str, Any]:
        report = {
            "products_imported": int(conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] or 0),
            "manufacturers_created": int(conn.execute("SELECT COUNT(*) FROM manufacturers").fetchone()[0] or 0),
            "renewal_alerts_generated": int(conn.execute("SELECT COUNT(*) FROM renewal_alerts").fetchone()[0] or 0),
            "revenue_opportunities_generated": int(conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] or 0),
            "pipeline_value": float(conn.execute("SELECT COALESCE(SUM(estimated_value), 0) FROM revenue_pipeline").fetchone()[0] or 0),
            "expired_products": int(conn.execute("SELECT COUNT(*) FROM products WHERE expiry_date IS NOT NULL AND date(expiry_date) < date('now')").fetchone()[0] or 0),
            "expiring_in_30_days": int(conn.execute("SELECT COUNT(*) FROM products WHERE expiry_date IS NOT NULL AND date(expiry_date) BETWEEN date('now') AND date('now', '+30 days')").fetchone()[0] or 0),
            "expiring_in_90_days": int(conn.execute("SELECT COUNT(*) FROM products WHERE expiry_date IS NOT NULL AND date(expiry_date) BETWEEN date('now') AND date('now', '+90 days')").fetchone()[0] or 0),
        }
        return report

    def run(self) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        self.logger.info("Synchronization started")
        summary = {
            "status": "success",
            "added": 0,
            "updated": 0,
            "unchanged": 0,
            "removed": 0,
            "duration": 0,
            "errors": 0,
            "stages": [],
            "current_page": 0,
            "pages_remaining": 0,
            "percentage": 0,
        }
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        sync_id = None
        checkpoint = SyncCheckpoint(conn)
        try:
            import importlib.util
            from pathlib import Path

            migration_module_path = Path(__file__).resolve().parents[2] / "database" / "apply_migrations.py"
            spec = importlib.util.spec_from_file_location("mednova_apply_migrations", migration_module_path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            module.apply_migrations(self.db_path)
            conn.execute("BEGIN")
            sync_id = conn.execute(
                "INSERT INTO sync_history (started_at, status, products_added, products_updated, products_removed, duration_seconds, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (started_at.isoformat(), "running", 0, 0, 0, 0, None),
            ).lastrowid
            self.logger.info("Fetching Green Book records")
            fetch_started = time.perf_counter()
            items = self.client.fetch_all()
            fetch_duration_ms = round((time.perf_counter() - fetch_started) * 1000, 2)
            self.logger.info("Processing %s records", len(items))
            updater = SyncUpdater(conn)
            summary["stages"].append({"function": "GreenBookClient.fetch_all", "rows_inserted": len(items), "rows_updated": 0, "duration_ms": fetch_duration_ms})
            checkpoint.save(0, None, max(1, (len(items) + self.batch_size - 1) // self.batch_size), "running")
            active_registrations: set[str] = set()
            total_items = len(items)
            for index, item in enumerate(items, start=1):
                page = (index - 1) // self.batch_size + 1
                try:
                    raw = self.client.extract_product(item)
                    normalized = GreenBookMapper.to_internal_record(raw)
                    registration_number = normalized.get("registration_number")
                    if registration_number:
                        active_registrations.add(registration_number)
                    normalized["content_hash"] = build_product_hash(normalized)
                    action, product_id = updater.upsert_product(normalized)
                    if action == "added":
                        summary["added"] += 1
                    elif action == "updated":
                        summary["updated"] += 1
                    elif action == "unchanged":
                        summary["unchanged"] += 1
                    checkpoint.save(page, str(product_id), max(1, (total_items + self.batch_size - 1) // self.batch_size), "running")
                except Exception as exc:  # pragma: no cover - defensive path
                    self.logger.exception("Failed processing product: %s", exc)
                    summary["errors"] += 1
                    checkpoint.save(page, None, max(1, (total_items + self.batch_size - 1) // self.batch_size), "running")
            summary["removed"] = updater.mark_removed_products(active_registrations)
            summary["stages"].append({"function": "SyncUpdater.mark_removed_products", "rows_inserted": 0, "rows_updated": summary["removed"], "duration_ms": 0.0})
            renewal = RenewalEngine(conn)
            renewal_started = time.perf_counter()
            renewal.refresh()
            renewal_duration_ms = round((time.perf_counter() - renewal_started) * 1000, 2)
            renewal_count = int(conn.execute("SELECT COUNT(*) FROM renewal_alerts").fetchone()[0] or 0)
            summary["stages"].append({"function": "RenewalEngine.refresh", "rows_inserted": renewal_count, "rows_updated": 0, "duration_ms": renewal_duration_ms})
            opportunity_engine = OpportunityEngine(conn)
            opportunity_started = time.perf_counter()
            opportunity_engine.refresh()
            opportunity_duration_ms = round((time.perf_counter() - opportunity_started) * 1000, 2)
            opportunity_count = int(conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] or 0)
            summary["stages"].append({"function": "OpportunityEngine.refresh", "rows_inserted": opportunity_count, "rows_updated": 0, "duration_ms": opportunity_duration_ms})
            pipeline_started = time.perf_counter()
            pipeline_rows = self._build_revenue_pipeline(conn)
            pipeline_duration_ms = round((time.perf_counter() - pipeline_started) * 1000, 2)
            summary["stages"].append({"function": "SyncEngine._build_revenue_pipeline", "rows_inserted": pipeline_rows, "rows_updated": 0, "duration_ms": pipeline_duration_ms})
            manufacturer_stats = updater.get_lookup_stats().get("manufacturers", {})
            summary["manufacturer_normalization_calls"] = int(manufacturer_stats.get("lookups", 0))
            summary["manufacturers_created"] = int(manufacturer_stats.get("inserted", 0))
            summary["stages"].append({"function": "SyncUpdater.ensure_lookup", "rows_inserted": int(manufacturer_stats.get("inserted", 0)), "rows_updated": 0, "duration_ms": 0.0})
            conn.commit()
            checkpoint.clear()
            cloud_summary = sync_sqlite_to_supabase(self.db_path)
            summary["cloud_sync"] = cloud_summary
            if cloud_summary.get("status") != "success":
                summary["status"] = "partial"
            self.logger.info("Synchronization completed: %s", summary)
        except Exception as exc:  # pragma: no cover - defensive path
            conn.rollback()
            self.logger.exception("Synchronization aborted: %s", exc)
            summary["status"] = "failed"
            summary["errors"] += 1
        finally:
            finished_at = datetime.now(timezone.utc)
            duration = int((finished_at - started_at).total_seconds())
            summary["duration"] = duration
            summary["percentage"] = 100 if summary["status"] == "success" else 0
            summary["pages_remaining"] = 0
            summary["current_page"] = 0
            summary.update(self._build_report(conn))
            if sync_id is not None:
                conn.execute(
                    "UPDATE sync_history SET finished_at = ?, status = ?, products_added = ?, products_updated = ?, products_removed = ?, duration_seconds = ?, error_message = ? WHERE id = ?",
                    (finished_at.isoformat(), summary["status"], summary["added"], summary["updated"], summary["removed"], duration, (str(exc) if 'exc' in locals() else None), sync_id),
                )
            conn.commit()
            conn.close()

        self.logger.info("Synchronization finished in %s seconds", duration)
        return summary


def run_sync(db_path: str | Path | None = None) -> dict[str, Any]:
    engine = SyncEngine(db_path=db_path)
    return engine.run()


if __name__ == "__main__":
    summary = run_sync()
    print("Synchronization Complete")
    print()
    print(f"Products imported: {summary.get('products_imported', 0)}")
    print(f"Manufacturers created: {summary.get('manufacturers_created', 0)}")
    print(f"Renewal alerts generated: {summary.get('renewal_alerts_generated', 0)}")
    print(f"Revenue opportunities generated: {summary.get('revenue_opportunities_generated', 0)}")
    print(f"Pipeline value: ₦{summary.get('pipeline_value', 0):,.0f}")
    print(f"Expired products: {summary.get('expired_products', 0)}")
    print(f"Products expiring in 30 days: {summary.get('expiring_in_30_days', 0)}")
    print(f"Products expiring in 90 days: {summary.get('expiring_in_90_days', 0)}")
