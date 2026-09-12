"""
Universal Company Career Portal Scanner & Multi-Job Application Engine.
Supports:
- SAP SuccessFactors / Deloitte Portals (e.g. southasiacareers.deloitte.com)
- Workday Career Portals (e.g. *.myworkdayjobs.com)
- Generic company career pages with search forms
Automatically queries candidate keywords (DevOps/Cloud/SRE), extracts open roles,
filters for qualification, and applies to eligible roles with Fill-and-Review gating.
"""

from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
import urllib.parse
from playwright.sync_api import Page
from rich.panel import Panel
from rich.table import Table

from config_loader import load_config, get_resume_path
from database import JobDatabase
from utils.ats_filler import ExternalATSHandler
from utils.browser import BrowserManager
from utils.job_filter import is_title_relevant, has_blacklisted_skills, calculate_cv_skills_match
from utils.logger import console, logger


class CompanyPortalScanner:
    def __init__(
        self,
        company_url: str,
        config: Optional[Dict[str, Any]] = None,
        db: Optional[JobDatabase] = None,
        headless: bool = False,
        company_override: Optional[str] = None,
    ):
        self.raw_url = company_url.strip()
        self.config = config or load_config()
        self.db = db or JobDatabase()
        self.headless = headless

        self.resume_path = get_resume_path(self.config)
        self.ats_handler = ExternalATSHandler(self.config)
        self.company_name = company_override or self._infer_company_name(self.raw_url)

    def _infer_company_name(self, url: str) -> str:
        """Infers readable company name from domain or path."""
        parsed = urllib.parse.urlparse(url.lower())
        host = parsed.netloc

        if "deloitte" in host or "deloitte" in url.lower():
            return "Deloitte"
        if "myworkdayjobs" in host:
            parts = host.split(".")
            if len(parts) >= 3 and parts[0] not in ("wd1", "wd2", "wd3", "wd4", "wd5"):
                return parts[0].capitalize()

        # Check domain main label
        parts = host.split(".")
        if len(parts) >= 2:
            main_label = parts[-2]
            if main_label not in ("com", "co", "org", "net", "careers", "jobs"):
                return main_label.capitalize()

        return "Company"

    @staticmethod
    def is_search_portal(page: Page, url: str) -> bool:
        """
        Determines whether a given page is a career search portal
        (containing keyword search inputs, search buttons, or job directories)
        rather than a direct single-job application posting.
        """
        def safe_count(locator_str: str) -> int:
            try:
                c = page.locator(locator_str).count()
                if isinstance(c, (int, float)):
                    return int(c)
                return 0
            except Exception:
                return 0

        url_lower = url.lower()
        if any(marker in url_lower for marker in ("/go/", "/search", "/careers/search", "myworkdayjobs.com")):
            if safe_count("input[name='q'], input.keywordsearch-q, input#keyword, input[data-automation-id='keywordSearchInput']") > 0:
                return True

        # Check for search input elements in the DOM
        has_search_input = (
            safe_count(
                "input[name='q'], input.keywordsearch-q, input#keyword, "
                "input[data-automation-id='keywordSearchInput'], "
                "input[type='text'][placeholder*='keyword' i], "
                "input[type='text'][placeholder*='Search' i], "
                "input[type='search']"
            ) > 0
        )

        has_search_button = (
            safe_count(
                "input.keywordsearch-button, input[value='Search Jobs'], "
                "button:has-text('Search Jobs'), button:has-text('Search jobs'), "
                "button[data-automation-id='searchButton'], button:has-text('Search')"
            ) > 0
        )

        has_results_table = (
            safe_count(
                "table#searchresults, tr.data-row, div[data-automation-id='jobPosting'], "
                "a.jobTitle-link, a[data-automation-id='jobTitle']"
            ) > 0
        )

        return has_search_input and (has_search_button or has_results_table)

    def _dismiss_cookie_banner(self, page: Page):
        """Dismisses common corporate cookie consent modals."""
        try:
            btn = page.locator(
                "#cookie-accept, button#cookie-accept, button#onetrust-accept-btn-handler, "
                "button[data-automation-id*='cookie'], button:has-text('Accept All Cookies'), "
                "button:has-text('Accept All'), button:has-text('Accept')"
            ).first
            if btn.count() > 0 and btn.is_visible():
                btn.click()
                time.sleep(1.0)
        except Exception:
            pass

    def scan_jobs(
        self,
        keywords: Optional[List[str]] = None,
        target_location: str = "India",
        limit_per_keyword: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Navigates to the company career portal, performs search queries for each keyword,
        and extracts structured job postings.
        """
        if not keywords:
            cfg_kw = self.config.get("search", {}).get("keywords", ["DevOps Engineer"])
            keywords = cfg_kw if isinstance(cfg_kw, list) else [cfg_kw]

        discovered_jobs: List[Dict[str, Any]] = []
        seen_job_ids = set()

        browser_mgr = BrowserManager("company_portal", headless=self.headless)
        try:
            page = browser_mgr.start()
            page.set_default_timeout(35000)

            for kw in keywords:
                logger.step(f"Searching {self.company_name} career portal for: '{kw}'...")
                try:
                    page.goto(self.raw_url, wait_until="domcontentloaded")
                    time.sleep(2.5)
                    self._dismiss_cookie_banner(page)

                    # 1. Fill keyword input
                    q_input = page.locator(
                        "input[name='q'], input.keywordsearch-q, input#keyword, "
                        "input[data-automation-id='keywordSearchInput'], "
                        "input[type='text'][placeholder*='keyword' i], "
                        "input[type='text'][placeholder*='Search' i], "
                        "input[type='search']"
                    ).first

                    if q_input.count() > 0 and q_input.is_visible():
                        q_input.fill(kw)
                        time.sleep(0.5)

                    # 2. Fill location input if available and specified
                    if target_location and target_location.lower() != "all":
                        loc_input = page.locator(
                            "input[name='locationsearch'], input.keywordsearch-locationsearch, "
                            "input#location, input[type='text'][placeholder*='location' i]"
                        ).first
                        if loc_input.count() > 0 and loc_input.is_visible():
                            cur_loc = loc_input.input_value()
                            if not cur_loc:
                                loc_input.fill(target_location)
                                time.sleep(0.5)

                    # 3. Click Search button or press Enter
                    search_btn = page.locator(
                        "input.keywordsearch-button, input[value='Search Jobs'], "
                        "button:has-text('Search Jobs'), button:has-text('Search jobs'), "
                        "button[data-automation-id='searchButton'], button:has-text('Search')"
                    ).first

                    if search_btn.count() > 0 and search_btn.is_visible():
                        search_btn.click()
                    elif q_input.count() > 0:
                        q_input.press("Enter")

                    time.sleep(4.0)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass

                    BrowserManager.smooth_scroll(page, scrolls=2, distance=400)

                    # 4. Extract job listings
                    # A) SAP SuccessFactors / Deloitte style (table#searchresults, a.jobTitle-link, a[href*='/job/'])
                    job_links = page.locator(
                        "a.jobTitle-link, table#searchresults tr.data-row a, a[data-automation-id='jobTitle'], a[href*='/job/']"
                    ).all()

                    logger.info(f"Found {len(job_links)} listings for '{kw}' on {self.company_name} portal.")

                    for a_elem in job_links[:limit_per_keyword]:
                        try:
                            title = a_elem.inner_text(timeout=1000).strip()
                            # Discard table header links or non-job links
                            if not title or title.lower() in ("title", "location", "date", "reset", "apply", "view jobs"):
                                continue

                            href = a_elem.get_attribute("href", timeout=1000) or ""
                            if not href or href.startswith("#") or "javascript:" in href:
                                continue

                            full_url = urllib.parse.urljoin(page.url, href)

                            # Extract unique Job ID
                            job_id = ""
                            m = re.search(r"/(\d{5,10})/?", href)
                            if m:
                                job_id = m.group(1)
                            if not job_id:
                                m = re.search(r"[_\-/]([R|JR|REQ]*\d+)\??", href, re.IGNORECASE)
                                if m:
                                    job_id = m.group(1)
                            if not job_id:
                                job_id = re.sub(r"\W+", "_", f"{self.company_name}_{title}")[:30]

                            if job_id in seen_job_ids:
                                continue

                            # Extract location
                            loc_text = ""
                            parent_row = a_elem.locator("xpath=ancestor::tr[1]").first
                            if parent_row.count() > 0:
                                loc_cell = parent_row.locator("td.colLocation, span.jobLocation").first
                                if loc_cell.count() > 0:
                                    loc_text = loc_cell.inner_text(timeout=500).strip()
                            if not loc_text:
                                loc_text = target_location

                            seen_job_ids.add(job_id)
                            discovered_jobs.append({
                                "id": job_id,
                                "title": title,
                                "company": self.company_name,
                                "location": loc_text,
                                "posted_date": "Recently",
                                "url": full_url,
                            })

                        except Exception:
                            continue

                except Exception as e:
                    logger.warning(f"Error searching '{kw}' on {self.company_name}: {e}")
                    continue

        finally:
            browser_mgr.close()

        filtered = self.filter_jobs(discovered_jobs, keywords, target_location)
        return filtered

    def filter_jobs(
        self,
        jobs: List[Dict[str, Any]],
        keywords: List[str],
        target_location: str = "India",
    ) -> List[Dict[str, Any]]:
        """Filters discovered jobs for relevance, excluded skills, and deduplication against database."""
        configured_keywords = self.config.get("search", {}).get("keywords", [])
        combined_targets = list(dict.fromkeys(keywords + (configured_keywords if isinstance(configured_keywords, list) else [configured_keywords])))

        exclude_skills = self.config.get("search", {}).get("exclude_skills", ["sap", "salesforce"])
        cv_skills = self.config.get("profile", {}).get("cv_skills", None)

        processed_jobs = []
        for job in jobs:
            title = job["title"]
            loc = job["location"]
            job_id = job["id"]
            job_url = job["url"]

            # 1. Skill Blacklist
            if has_blacklisted_skills([title], blacklisted_skills=exclude_skills):
                job["status"] = "Excluded Skill"
                job["eligible"] = False
                processed_jobs.append(job)
                continue

            # 2. Relevance check
            if not is_title_relevant(title, combined_targets):
                job["status"] = "Irrelevant Role"
                job["eligible"] = False
                processed_jobs.append(job)
                continue

            # 3. Location check
            if target_location and target_location.lower() != "all":
                loc_lower = loc.lower()
                is_loc_match = (
                    target_location.lower() in loc_lower
                    or "remote" in loc_lower
                    or "hybrid" in loc_lower
                    or "bengaluru" in loc_lower
                    or "mumbai" in loc_lower
                    or "hyderabad" in loc_lower
                    or "delhi" in loc_lower
                    or "pune" in loc_lower
                    or "noida" in loc_lower
                    or not loc
                )
                if not is_loc_match:
                    job["status"] = f"Location Mismatch ({loc})"
                    job["eligible"] = False
                    processed_jobs.append(job)
                    continue

            # 4. Check if already applied or skipped in DB
            already_applied = self.db.is_url_or_company_applied(
                job_url=job_url, company=self.company_name, title=title
            )
            if already_applied:
                job["status"] = "Already Applied"
                job["eligible"] = False
            else:
                job["status"] = "Eligible"
                job["eligible"] = True

            # Calculate CV skills match
            match_count, matched_skills = calculate_cv_skills_match([title], cv_skills=cv_skills)
            job["skill_match_count"] = match_count
            job["matched_skills"] = matched_skills

            processed_jobs.append(job)

        return processed_jobs

    def display_jobs_table(self, jobs: List[Dict[str, Any]]):
        """Renders an interactive Rich table summarizing discovered positions."""
        table = Table(title=f"{self.company_name} Career Portal - Discovered Matching Roles", border_style="cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("Job ID", style="cyan", width=12)
        table.add_column("Job Title", style="bold green", min_width=28)
        table.add_column("Location", style="yellow", min_width=16)
        table.add_column("Status", style="bold", width=16)

        for i, j in enumerate(jobs, 1):
            status_style = "green" if j.get("eligible") else "dim red"
            table.add_row(
                str(i),
                j.get("id", "")[:12],
                j.get("title", ""),
                j.get("location", ""),
                f"[{status_style}]{j.get('status', 'Eligible')}[/{status_style}]",
            )

        console.print(table)

    def apply_to_jobs(
        self,
        jobs: List[Dict[str, Any]],
        max_applications: int = 10,
    ) -> int:
        """
        Navigates to each eligible job's actual posting page, clicks Apply,
        fills the application with candidate profile & resume, and pauses on Fill-and-Review.
        """
        eligible_jobs = [j for j in jobs if j.get("eligible")]
        if not eligible_jobs:
            logger.info(f"No eligible unapplied positions found at {self.company_name}.")
            return 0

        logger.info(
            f"Starting automated application process for {len(eligible_jobs)} eligible jobs at {self.company_name}."
        )

        applied_count = 0
        cl_path = self.config.get("profile", {}).get("cover_letter_path", "Ansh_Mishra_Cover_Letter.pdf")
        resolved_cl = Path(cl_path)
        if not resolved_cl.is_absolute():
            resolved_cl = Path(__file__).parent.parent.resolve() / resolved_cl

        browser_mgr = BrowserManager("portal_apply", headless=self.headless)
        try:
            page = browser_mgr.start()
            for job in eligible_jobs[:max_applications]:
                job_id = job["id"]
                title = job["title"]
                url = job["url"]
                loc = job["location"]

                logger.step(f"Navigating to job posting: {title} ({url})...")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=35000)
                    time.sleep(2.5)
                    self._dismiss_cookie_banner(page)

                    # Click 'Apply now' / 'Apply' CTA if present on the posting description
                    # STRICT SELECTOR: prioritize real apply buttons and NEVER match advisory/terms links!
                    apply_btn = page.locator(
                        "a.dialogApplyBtn, "
                        "a[href*='/talentcommunity/apply/'], "
                        "a:has-text('Apply now »'), button:has-text('Apply now »'), "
                        "a.btn-apply, a.applyButton, button.applyButton, "
                        "a:has-text('Apply for this job'), button:has-text('Apply for this job'), "
                        "a:has-text('Apply Online'), button:has-text('Apply Online'), "
                        "a:has-text('Apply now'):not(:has-text('know before')), "
                        "button:has-text('Apply now')"
                    ).first

                    def safe_count(loc) -> int:
                        try:
                            c = loc.count() if hasattr(loc, "count") else 0
                            return int(c) if isinstance(c, (int, float)) else 0
                        except Exception:
                            return 0

                    if safe_count(apply_btn) > 0 and apply_btn.is_visible():
                        logger.step(f"Clicking Apply button on '{title}' posting...")
                        apply_btn.click()
                        time.sleep(3.0)
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=12000)
                        except Exception:
                            pass

                    # Close any accidental advisory popup tabs
                    try:
                        for p in list(page.context.pages):
                            if p != page and any(m in p.url.lower() for m in ("terms-disclaimers", "advisory", "about:blank")):
                                p.close()
                    except Exception:
                        pass

                    # Execute full ATS auto-filling and Fill-and-Review confirmation
                    success = self.ats_handler.apply_external(
                        page=page,
                        job_title=title,
                        company=self.company_name,
                        resume_path=self.resume_path,
                        cover_letter_path=resolved_cl if resolved_cl.exists() else None,
                    )

                    if success:
                        applied_count += 1
                        self.db.record_application(
                            job_id=job_id,
                            platform="direct",
                            title=title,
                            company=self.company_name,
                            location=loc,
                            job_url=url,
                            status="applied",
                            reason=f"Applied via {self.company_name} Career Portal",
                        )
                        logger.success(f"Successfully recorded application for '{title}' at {self.company_name}!")
                    else:
                        logger.warning(f"Application for '{title}' was skipped or not submitted.")
                        # Record as skipped to avoid re-opening
                        self.db.record_application(
                            job_id=job_id,
                            platform="direct",
                            title=title,
                            company=self.company_name,
                            location=loc,
                            job_url=url,
                            status="skipped",
                            reason=f"Skipped on {self.company_name} Career Portal",
                        )

                except Exception as e:
                    logger.error(f"Failed application attempt for '{title}': {e}")
                    continue

        finally:
            browser_mgr.close()

        return applied_count
