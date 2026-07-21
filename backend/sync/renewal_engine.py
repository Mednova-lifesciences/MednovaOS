from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from .utils import iso_now


class RenewalEngine:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def refresh(self) -> None:
        self.conn.execute("DELETE FROM renewal_alerts")
        rows = self.conn.execute("SELECT id, expiry_date FROM products WHERE expiry_date IS NOT NULL").fetchall()
        today = datetime.now().date()
        for product_id, expiry_date in rows:
            try:
                expiry = datetime.fromisoformat(expiry_date).date()
            except ValueError:
                continue
            days_remaining = (expiry - today).days
            if days_remaining < 0:
                alert_level = "EXPIRED"
            elif days_remaining <= 30:
                alert_level = "RED"
            elif days_remaining <= 60:
                alert_level = "YELLOW"
            elif days_remaining <= 90:
                alert_level = "YELLOW"
            elif expiry.year == today.year:
                alert_level = "GREEN"
            else:
                alert_level = "GREEN"
            self.conn.execute(
                "INSERT INTO renewal_alerts (product_id, expiry_date, days_remaining, alert_level, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (product_id, expiry_date, days_remaining, alert_level, iso_now(), iso_now()),
            )
