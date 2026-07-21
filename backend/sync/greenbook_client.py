from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests
from bs4 import BeautifulSoup

from .utils import get_setting, safe_text

logger = logging.getLogger("mednova_sync")


class GreenBookClient:
    def __init__(self) -> None:
        self.base_url = get_setting("GREENBOOK_BASE_URL", "https://greenbook.nafdac.gov.ng/").rstrip("/")
        self.timeout = int(get_setting("GREENBOOK_TIMEOUT", "30"))
        self.max_retries = int(get_setting("GREENBOOK_MAX_RETRIES", "4"))
        self.backoff_base = float(get_setting("GREENBOOK_BACKOFF_BASE", "1.5"))
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MedNovaOS/1.0",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.base_url}/",
        })

    def fetch_all(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        try:
            page_size = int(get_setting("GREENBOOK_PAGE_SIZE", "100"))
            start = 0
            while True:
                payload = self._fetch_page(start=start, length=page_size)
                if not isinstance(payload, dict):
                    break
                batch = payload.get("data") or []
                if not isinstance(batch, list) or not batch:
                    break
                records.extend(batch)
                total = int(payload.get("recordsTotal") or payload.get("recordsFiltered") or 0)
                if not total or len(records) >= total or len(batch) < page_size:
                    return records
                start += page_size
                time.sleep(float(get_setting("GREENBOOK_THROTTLE_SECONDS", "0.25")))
        except Exception as exc:  # pragma: no cover - defensive path
            logger.warning("Falling back to HTML scraping after API failure: %s", exc)
            html = self._fetch_html_page()
            parsed_rows = self._parse_html_rows(html)
            if parsed_rows:
                return parsed_rows
        return records

    def _fetch_page(self, start: int, length: int) -> dict[str, Any]:
        params = {
            "draw": str((start // max(length, 1)) + 1),
            "columns[0][data]": "product_name",
            "columns[0][name]": "product_name",
            "columns[0][searchable]": "true",
            "columns[0][orderable]": "true",
            "columns[0][search][value]": "",
            "columns[0][search][regex]": "false",
            "start": start,
            "length": length,
            "search[value]": "",
            "search[regex]": "false",
            "order[0][column]": "0",
            "order[0][dir]": "asc",
            "search_ingredient": "",
        }
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(self.base_url, params=params, timeout=self.timeout)
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                logger.info("Fetched Green Book page start=%s length=%s", start, length)
                return payload
            except requests.RequestException as exc:  # pragma: no cover - network path
                last_error = exc
                if attempt < self.max_retries:
                    delay = self.backoff_base * (2**attempt)
                    logger.warning("Green Book request failed (attempt %s/%s): %s", attempt + 1, self.max_retries + 1, exc)
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"Green Book request failed after retries: {exc}") from exc

        if last_error:
            raise RuntimeError(f"Green Book request failed: {last_error}") from last_error
        raise RuntimeError("Green Book request failed with no response")

    def _fetch_html_page(self) -> str:
        response = self.session.get(self.base_url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def _parse_html_rows(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        rows: list[dict[str, Any]] = []
        for table in soup.select("table"):
            for tr in table.select("tr"):
                cells = [cell.get_text(" ", strip=True) for cell in tr.select("th, td")]
                if not cells:
                    continue
                if len(cells) < 3:
                    continue
                rows.append({
                    "product_name": cells[0] if cells else None,
                    "active_ingredient": cells[1] if len(cells) > 1 else None,
                    "registration_number": cells[2] if len(cells) > 2 else None,
                })
        return rows

    def extract_product(self, item: dict[str, Any]) -> dict[str, Any]:
        raw = item.get("data") if isinstance(item.get("data"), dict) else item
        if isinstance(raw, dict):
            data = raw
        else:
            data = {}

        ingredient = data.get("ingredient") if isinstance(data.get("ingredient"), dict) else {}
        form = data.get("form") if isinstance(data.get("form"), dict) else {}
        route = data.get("route") if isinstance(data.get("route"), dict) else {}
        applicant = data.get("applicant") if isinstance(data.get("applicant"), dict) else {}
        product_category = data.get("product_category") if isinstance(data.get("product_category"), dict) else {}
        manufacturer = data.get("manufacturer") if isinstance(data.get("manufacturer"), dict) else {}

        def first_text(*values: Any) -> str | None:
            for value in values:
                if isinstance(value, dict):
                    continue
                if value is None:
                    continue
                text = safe_text(value)
                if text:
                    return text
            return None

        registration_number = safe_text(data.get("registration_number") or data.get("registrationNumber") or data.get("registration_no") or data.get("registrationNo") or data.get("NAFDAC"))
        if not registration_number:
            registration_number = safe_text(data.get("product_id"))

        manufacturer = first_text(
            data.get("manufacturer"),
            data.get("manufacturer_name"),
            data.get("manufacturerName"),
            manufacturer.get("name"),
            data.get("manufacturer_name"),
            applicant.get("name"),
        )

        return {
            "product_id": safe_text(data.get("product_id") or data.get("id") or data.get("productId") or item.get("id")),
            "registration_number": registration_number,
            "product_name": safe_text(data.get("product_name") or data.get("productName") or data.get("name")),
            "composition": safe_text(data.get("composition") or data.get("composition_text") or data.get("formulation")),
            "active_ingredient": first_text(data.get("active_ingredient"), data.get("activeIngredient"), ingredient.get("ingredient_name"), ingredient.get("name"), data.get("ingredient_name")),
            "strength": first_text(data.get("strength"), data.get("strength_value"), data.get("potency")),
            "dosage_form": first_text(data.get("dosage_form"), data.get("dosageForm"), form.get("name"), data.get("form_name"), data.get("form")),
            "category": first_text(data.get("category"), data.get("product_category"), data.get("productCategory"), product_category.get("name"), data.get("category_name")),
            "route": first_text(data.get("route"), data.get("route_of_administration"), data.get("routeOfAdministration"), route.get("name"), data.get("route_name")),
            "manufacturer": manufacturer,
            "applicant": first_text(data.get("applicant"), data.get("applicant_name"), data.get("applicantName"), applicant.get("name")),
            "approval_date": first_text(data.get("approval_date"), data.get("approvalDate"), data.get("approved_on")),
            "expiry_date": first_text(data.get("expiry_date"), data.get("expiryDate"), data.get("expiry")),
            "status": first_text(data.get("status"), data.get("product_status"), data.get("state")),
            "description": first_text(data.get("description"), data.get("details"), data.get("remarks"), data.get("product_description")),
            "pack_size": first_text(data.get("pack_size"), data.get("packSize"), data.get("pack")),
            "source_last_updated": first_text(data.get("source_last_updated"), data.get("updated_at"), data.get("last_updated"), data.get("created_at")),
        }
