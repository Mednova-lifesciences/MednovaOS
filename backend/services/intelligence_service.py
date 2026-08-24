from __future__ import annotations

from typing import Any, Optional
import os
import re
import json
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from backend.database.repositories import IntelligenceRepository
from backend.logging_utils import get_logger
from backend.models import Intelligence
from backend.utils import now_iso
from backend.services.company_service import CompanyService
from backend.services.pipeline_service import PipelineService
from backend.services.outreach_service import OutreachService
from urllib.parse import urlparse

logger = get_logger("intelligence_service")


class IntelligenceService:
    def __init__(self, intelligence_repo: Optional[IntelligenceRepository] = None):
        self.intelligence_repo = intelligence_repo or IntelligenceRepository()
        self.company_service = CompanyService()
        self.pipeline_service = PipelineService()
        self.outreach_service = OutreachService()
        self.last_tavily_error: str | None = None

    def _build_company_search_query(self, company: dict) -> str:
        name = (company.get("company_name") or "Company").strip()
        website = (company.get("website") or "").strip()
        if website:
            domain = urlparse(website).netloc or website.replace("http://", "").replace("https://", "")
            return f"{name} site:{domain}"
        return name

    def _call_tavily_search(self, query: str) -> dict | None:
        api_key = (os.getenv("TAVILY_API_KEY") or "").strip()
        if not api_key:
            logger.warning("Tavily API key missing; skipping tavily search for query: %s", query)
            return None

        url = "https://api.tavily.com/search"
        payload = {
            # Do NOT log the API key
            "query": query,
            "search_depth": "advanced",
            "max_results": 10,
            "include_answer": True,
            "include_raw_content": True,
            "include_images": False,
        }

        try:
            logger.info("Sending Tavily request for query: %s", (query[:200] + "...") if len(query) > 200 else query)
            response = requests.post(url, json={**payload, "api_key": api_key}, timeout=15)
            logger.info("Tavily response status: %s for query: %s", response.status_code, query)
            try:
                body_text = response.text or ""
                logger.debug("Tavily response body (truncated): %s", (body_text[:1000] + "...") if len(body_text) > 1000 else body_text)
            except Exception:
                logger.debug("Could not read Tavily response body for logging")

            if response.status_code == 200:
                try:
                    data = response.json()
                    results_count = len(data.get("results", [])) if isinstance(data, dict) else 0
                    logger.info("Tavily returned %d contacts for query: %s", results_count, query)
                    self.last_tavily_error = None
                    return data
                except ValueError:
                    logger.error("Failed to parse JSON from Tavily response for query: %s", query)
                    self.last_tavily_error = "Could not parse response from provider."
                    return None
            else:
                logger.error("Tavily returned non-200 status %s for query: %s", response.status_code, query)
                self.last_tavily_error = "The discovery provider returned an unexpected status."
                return None
        except requests.Timeout as exc:
            logger.exception("Tavily request timed out for query: %s -- %s", query, exc)
            self.last_tavily_error = "The contact discovery provider could not be reached."
            return None
        except requests.RequestException as exc:
            logger.exception("Tavily request failed for query: %s -- %s", query, exc)
            self.last_tavily_error = "The contact discovery provider encountered an error."
            return None

    def search_tavily(self, query: str) -> dict | None:
        """Shared Tavily search implementation for public use."""
        return self._call_tavily_search(query)

    def search_company_contacts(self, company_id: int) -> tuple[str, dict | None]:
        company = self.company_service.get_company(company_id)
        if not company:
            raise LookupError("company not found")

        company_dict = company if isinstance(company, dict) else (company.__dict__ if hasattr(company, "__dict__") else {})
        search_query = self._build_company_search_query(company_dict)
        return search_query, self._call_tavily_search(search_query)

    def _parse_tavily_insights(self, tavily_response: dict | None) -> dict:
        if not tavily_response:
            return {"answer": "", "results": [], "news": [], "source_count": 0}
        return {
            "answer": tavily_response.get("answer", ""),
            "results": tavily_response.get("results", [])[:5],
            "news": [r for r in tavily_response.get("results", []) if "news" in r.get("source", "").lower()][:3],
            "source_count": len(tavily_response.get("results", [])),
        }

    def _fetch_text(self, url: str) -> str | None:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, timeout=8, headers=headers)
            if response.ok:
                return response.text
        except requests.RequestException:
            return None
        return None

    def _extract_named_entities(self, text: str, company_name: str) -> list[str]:
        tokens = []
        low = text.lower()
        if "regulatory" in low or "regulation" in low:
            tokens.append("Regulatory Affairs")
        if "quality" in low or "gmp" in low or "iso" in low:
            tokens.append("Quality Systems")
        if "clinical" in low or "trial" in low:
            tokens.append("Clinical Operations")
        if "manufactur" in low:
            tokens.append("Manufacturing Support")
        if "data" in low or "digital" in low:
            tokens.append("Digital Transformation")
        if "medical" in low or "medical writing" in low:
            tokens.append("Medical Writing")
        if "pharmacovigilance" in low or "safety" in low:
            tokens.append("Pharmacovigilance")
        if company_name.lower() in low and "launch" in low:
            tokens.append("Launch Readiness")
        return list(dict.fromkeys(tokens))

    def get_intelligence(self, company_id: int) -> Intelligence | None:
        logger.info("Getting intelligence for company: id=%s", company_id)
        return self.intelligence_repo.get_by_company_id(company_id)

    def upsert_intelligence(self, company_id: int, payload: dict[str, Any]) -> Intelligence | dict:
        logger.info("Upserting intelligence for company: id=%s", company_id)
        payload["crm_company_id"] = company_id
        payload["updated_at"] = now_iso()
        return self.intelligence_repo.upsert_by_company_id(payload)

    def compute_intelligence(self, company_id: int, force_refresh: bool = False) -> dict:
        # Build tavily search query
        company = self.company_service.get_company(company_id)
        if not company:
            raise LookupError("company not found")

        company_dict = company if isinstance(company, dict) else (company.__dict__ if hasattr(company, '__dict__') else {})

        # find website from contacts
        details = self.company_service.get_company_detail(company_id) or {}
        contacts = details.get("contacts") or []
        website = ""
        for c in contacts:
            candidate = (c.get("website") or "") if isinstance(c, dict) else getattr(c, 'website', '')
            candidate = (candidate or "").strip()
            if candidate:
                website = candidate
                break

        search_query = self._build_company_search_query({**company_dict, "website": website})

        # check tavily cache
        cached = None
        try:
            cached_row = self.intelligence_repo.get_tavily_cache(company_id, search_query)
            if cached_row:
                refreshed = datetime.fromisoformat((cached_row.get("last_refreshed_at") or "").replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - refreshed).days
                ttl = int(cached_row.get("ttl_days") or 7)
                if not force_refresh and age_days < ttl:
                    cached = json.loads(cached_row.get("search_results_json") or "{}")
        except Exception:
            cached = None

        if cached is None:
            results = self._call_tavily_search(search_query)
            if results:
                try:
                    self.intelligence_repo.upsert_tavily_cache(company_id, search_query, results)
                except Exception:
                    pass
            tavily_intel = results or {}
        else:
            tavily_intel = cached

        tavily_insights = self._parse_tavily_insights(tavily_intel)

        # collect CRM signals
        contacts_list = details.get("contacts") or []
        tasks_list = details.get("tasks") or []
        deals_list = self.pipeline_service.list_deals(company_id, page=1, per_page=8).get("items", [])

        # website analysis
        site_text = ""
        site_title = ""
        site_meta = ""
        site_headings = []
        social_links = []
        raw_site = None
        if website:
            raw_site = self._fetch_text(website if website.startswith("http") else f"https://{website}")
        if raw_site:
            soup = BeautifulSoup(raw_site, "html.parser")
            site_text = " ".join(soup.stripped_strings)
            site_title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()
            site_meta = (soup.find("meta", attrs={"name": "description"}) or {}).get("content", "") if soup.find("meta", attrs={"name": "description"}) else ""
            site_headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"])[:10] if h.get_text(" ", strip=True)]
            site_links = [link.get("href", "") for link in soup.find_all("a") if link.get("href")]
            social_links = [l for l in site_links if any(token in l.lower() for token in ["linkedin", "twitter", "facebook", "youtube", "instagram"]) ]

        profile_text = " ".join([company_dict.get("portfolio_summary", "") or "", site_text, site_title, site_meta, " ".join(site_headings)])
        services = self._extract_named_entities(profile_text, company_dict.get("company_name", "")) or ["Regulatory Affairs", "Quality Systems", "Clinical Operations"]

        intelligence = {
            "company_profile": {
                "name": company_dict.get("company_name"),
                "country": company_dict.get("country"),
                "website": website or "",
                "description": (company_dict.get("portfolio_summary") or "").strip(),
                "leadership": [c.get("full_name") for c in contacts_list if isinstance(c, dict)][:4],
            },
            "services": services,
            "tavily_insights": tavily_insights,
            "website_analysis": {
                "website": website or "",
                "navigation": [h for h in site_headings[:6] if h],
                "trust_indicators": ["HTTPS" if website and website.startswith("https") else "Website available"],
                "seo_quality": "strong" if site_title and site_meta else "moderate",
                "accessibility": "good" if site_headings else "needs review",
            },
            "business_opportunity": {
                "recommended_services": services,
                "priority_score": max(60, min(99, int(company_dict.get("opportunity_score") or 0) + 8 + len(services) * 3)),
                "explanation": "Derived from CRM signals and public sources.",
            },
            "generated_at": now_iso(),
            "refresh_status": "ready",
            "cache_ttl_days": 7,
        }

        # persist intelligence via repository
        try:
            payload = {
                "crm_company_id": company_id,
                "data": intelligence,
                "search_status": "ready",
                "last_refresh": now_iso(),
                "updated_at": now_iso(),
            }
            self.intelligence_repo.upsert_by_company_id(payload)
        except Exception:
            logger.exception("Failed to persist intelligence for company %s", company_id)

        return intelligence

    def refresh_intelligence(self, company_id: int) -> Intelligence | dict:
        logger.info("Refreshing intelligence for company: id=%s", company_id)
        intelligence_data = self.compute_intelligence(company_id, force_refresh=True)
        return intelligence_data
