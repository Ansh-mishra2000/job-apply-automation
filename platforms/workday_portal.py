"""
Workday Career Portal Scanner & Automated Application Engine.
Allows direct ingestion of any company's Workday careers URL (e.g. Invesco, Accenture, Adobe, Nvidia),
discovers matching open positions for candidate profiles, and executes automated applications
with Fill-and-Review mode.
"""

from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
import urllib.parse
from rich.panel import Panel
from rich.table import Table

from config_loader import load_config, get_resume_path
from database import JobDatabase
from utils.ats_filler import ExternalATSHandler
from utils.browser import BrowserManager
from utils.job_filter import is_title_relevant, has_blacklisted_skills, calculate_cv_skills_match
from utils.logger import console, logger


class WorkdayPortalScanner:
    def __init__(
        self,
        company_url: str,
        config: Optional[Dict[str, Any]] = None,
        db: Optional[JobDatabase] = None,
        headless: bool = False,
    ):
        self.raw_url = company_url.strip()
        self.config = config or load_config()
        self.db = db or JobDatabase()
        self.headless = headless

        self.resume_path = get_resume_path(self.config)
        self.ats_handler = ExternalATSHandler(self.config)
        self.company_name = self._infer_company_name(self.raw_url)

    def _infer_company_name(self, url: str) -> str:
        """Infers readable company name from Workday domain or path."""
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower()
        # Typical: invesco.wd1.myworkdayjobs.com -> 'invesco'
        parts = host.split(".")
        if len(parts) >= 3 and "myworkdayjobs" in host:
            sub = parts[0]
            if sub not in ("wd1", "wd2", "wd3", "wd4", "wd5"):
                return sub.capitalize()
        # Fallback: check path segment
        path_segs = [s for s in parsed.path.split("/") if s and s.lower() not in ("en-us", "en", "jobs")]
        if path_segs:
            return path_segs[0].capitalize()
        return "Company"

    def extract_search_url(self, base_url: str, keyword: str) -> str:
        """Constructs direct Workday search URL for a given keyword."""
        parsed = urllib.parse.urlparse(base_url)
        q_params = urllib.parse.parse_qs(parsed.query)
        q_params["q"] = [keyword]
        new_query = urllib.parse.urlencode(q_params, doseq=True)
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

    def _dismiss_cookie_banner(self, page):
        """Dismisses common Workday cookie consent modals."""
        try:
            btn = page.locator(
                "button#onetrust-accept-btn-handler, button[data-automation-id*='cookie'], button:has-text('Accept All'), button:has-text('Accept')"
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
        Navigates to the Workday career portal, performs keyword queries,
        and extracts structured job postings.
        """
        if not keywords:
            keywords = self.config.get("search", {}).get("keywords", ["DevOps Engineer"])

        discovered_jobs: List[Dict[str, Any]] = []
        seen_job_ids = set()

        browser_mgr = BrowserManager("workday", headless=self.headless)
        try:
            page = browser_mgr.start()
            page.set_default_timeout(25000)

            for kw in keywords:
                logger.step(f"Searching {self.company_name} Workday portal for: '{kw}'...")
                search_url = self.extract_search_url(self.raw_url, kw)

                try:
                    page.goto(search_url, wait_until="domcontentloaded")
                    time.sleep(3.0)
                    self._dismiss_cookie_banner(page)

                    # Wait for results or loading spinner to finish
                    try:
                        page.wait_for_selector(
                            "[data-automation-id='loadingSpinner']", state="detached", timeout=6000
                        )
                    except Exception:
                        pass

                    # If the search input exists, ensure keyword is entered
                    search_input = page.locator(
                        "input[data-automation-id='keywordSearchInput'], input[type='text'][placeholder*='Search'], input[aria-label*='Search']"
                    ).first
                    if search_input.count() > 0 and search_input.is_visible():
                        cur_val = search_input.input_value()
                        if kw.lower() not in cur_val.lower():
                            search_input.fill(kw)
                            search_input.press("Enter")
                            time.sleep(3.5)
                            try:
                                page.wait_for_selector(
                                    "[data-automation-id='loadingSpinner']", state="detached", timeout=6000
                                )
                            except Exception:
                                pass

                    BrowserManager.smooth_scroll(page, scrolls=2, distance=400)

                    # Extract job card elements
                    card_locators = page.locator("a[data-automation-id='jobTitle']").all()
                    if not card_locators:
                        card_locators = page.locator("li.css-1q2dra3 a, div[data-automation-id='jobPosting'] a").all()

                    logger.info(f"Found {len(card_locators)} raw listings for '{kw}' on {self.company_name}.")

                    for title_elem in card_locators[:limit_per_keyword]:
                        try:
                            title = title_elem.inner_text(timeout=1000).strip()
                            if not title:
                                continue

                            href = title_elem.get_attribute("href", timeout=1000) or ""
                            full_url = urllib.parse.urljoin(self.raw_url, href)

                            # Extract Job ID
                            job_id = ""
                            if href:
                                m = re.search(r"[_\-/]([R|JR|REQ]*\d+)\??", href, re.IGNORECASE)
                                if m:
                                    job_id = m.group(1)
                            if not job_id:
                                m = re.search(r"\b([R|JR|REQ]\d+)\b", title)
                                if m:
                                    job_id = m.group(1)
                            if not job_id:
                                job_id = re.sub(r"\W+", "_", f"{self.company_name}_{title}")[:30]

                            if job_id in seen_job_ids:
                                continue

                            # Find parent container for location & posted info
                            parent_item = title_elem.locator("xpath=ancestor::li[1] | ancestor::div[@data-automation-id='jobPosting'][1]").first
                            location_text = ""
                            posted_date = ""

                            if parent_item.count() > 0:
                                loc_elem = parent_item.locator(
                                    "[data-automation-id='jobPostingLocation'], [data-automation-id='locations'], dd.css-129m7dg"
                                ).first
                                if loc_elem.count() > 0:
                                    location_text = loc_elem.inner_text(timeout=800).strip()

                                posted_elem = parent_item.locator(
                                    "[data-automation-id='postedOn'], span:has-text('Posted')"
                                ).first
                                if posted_elem.count() > 0:
                                    posted_date = posted_elem.inner_text(timeout=800).strip()

                            seen_job_ids.add(job_id)
                            discovered_jobs.append({
                                "id": job_id,
                                "title": title,
                                "company": self.company_name,
                                "location": location_text or target_location,
                                "posted_date": posted_date or "Recently",
                                "url": full_url,
                            })

                        except Exception:
                            continue

                except Exception as e:
                    logger.warning(f"Error scanning keyword '{kw}' on {self.company_name}: {e}")
                    continue

        finally:
            browser_mgr.close()

        # Filter jobs for relevance, location, and exclusions
        filtered = self.filter_jobs(discovered_jobs, keywords, target_location)
        return filtered

    def filter_jobs(
        self,
        jobs: List[Dict[str, Any]],
        keywords: List[str],
        target_location: str = "India",
    ) -> List[Dict[str, Any]]:
        """Filters jobs based on target roles, location, exclusions, and deduplication status."""
        configured_keywords = self.config.get("search", {}).get("keywords", [])
        combined_targets = list(dict.fromkeys(keywords + (configured_keywords if isinstance(configured_keywords, list) else [configured_keywords])))

        exclude_skills = self.config.get("search", {}).get("exclude_skills", ["sap", "salesforce"])
        cv_skills = self.config.get("profile", {}).get("cv_skills", None)

        qualified_jobs = []
        for job in jobs:
            title = job["title"]
            loc = job["location"]
            job_id = job["id"]

            # 1. Relevance check
            if not is_title_relevant(title, combined_targets):
                job["status"] = "Irrelevant Role"
                job["eligible"] = False
                continue

            # 2. Skill Blacklist
            if has_blacklisted_skills([title], blacklisted_skills=exclude_skills):
                job["status"] = "Excluded Skill"
                job["eligible"] = False
                continue

            # 3. Location check
            if target_location and target_location.lower() != "all":
                loc_lower = loc.lower()
                is_loc_match = (
                    target_location.lower() in loc_lower
                    or "remote" in loc_lower
                    or "hybrid" in loc_lower
                    or not loc
                )
                if not is_loc_match:
                    job["status"] = f"Location Mismatch ({loc})"
                    job["eligible"] = False
                    continue

            # 4. Check if already applied
            already_applied = self.db.is_job_applied(job_id, "workday")
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

            qualified_jobs.append(job)

        return qualified_jobs

    def display_jobs_table(self, jobs: List[Dict[str, Any]]):
        """Renders an interactive Rich table summarizing discovered positions."""
        table = Table(title=f"{self.company_name} Workday Careers - Discovered Roles", border_style="cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("Job ID", style="cyan", width=12)
        table.add_column("Job Title", style="bold green", min_width=25)
        table.add_column("Location", style="yellow", min_width=15)
        table.add_column("Posted Date", style="magenta", width=14)
        table.add_column("Status", style="bold", width=16)

        for i, j in enumerate(jobs, 1):
            status_style = "green" if j.get("eligible") else "dim yellow"
            table.add_row(
                str(i),
                j.get("id", "")[:12],
                j.get("title", ""),
                j.get("location", ""),
                j.get("posted_date", ""),
                f"[{status_style}]{j.get('status', 'Eligible')}[/{status_style}]",
            )

        console.print(table)

    def apply_to_jobs(
        self,
        jobs: List[Dict[str, Any]],
        max_applications: int = 10,
    ) -> int:
        """
        Navigates to each eligible job's application page, triggers apply_workday,
        and prompts the user for Fill-and-Review before final submission.
        """
        eligible_jobs = [j for j in jobs if j.get("eligible")]
        if not eligible_jobs:
            logger.info(f"No eligible positions to apply for at {self.company_name}.")
            return 0

        logger.info(
            f"Starting automated application process for {len(eligible_jobs)} eligible jobs at {self.company_name}."
        )

        applied_count = 0
        browser_mgr = BrowserManager("workday", headless=self.headless)
        try:
            page = browser_mgr.start()
            for job in eligible_jobs[:max_applications]:
                job_id = job["id"]
                title = job["title"]
                url = job["url"]
                loc = job["location"]

                logger.step(f"Navigating to {title} ({url})...")
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    time.sleep(3.0)
                    self._dismiss_cookie_banner(page)

                    # Execute full Workday form filling and review workflow
                    success = self.ats_handler.apply_workday(
                        page=page,
                        job_title=title,
                        company=self.company_name,
                        resume_path=self.resume_path,
                    )

                    if success:
                        applied_count += 1
                        self.db.record_application(
                            job_id=job_id,
                            platform="workday",
                            title=title,
                            company=self.company_name,
                            location=loc,
                            job_url=url,
                            status="applied",
                        )
                        logger.success(f"Successfully recorded application for '{title}' at {self.company_name}.")
                    else:
                        logger.warning(f"Application for '{title}' was skipped or not submitted.")

                except Exception as e:
                    logger.error(f"Failed application attempt for '{title}': {e}")
                    continue

        finally:
            browser_mgr.close()

        return applied_count
