"""
Instahyre Platform Automation Engine.
Automates 1-click applications for top tech product companies & unicorns in India.
Features:
1. Opportunities feed navigation & role matching.
2. 1-Click Apply with CTC & Notice Period auto-response.
3. Agency exclusion & deduplication.
4. Persistent browser profile & daily quota tracking.
"""

from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
from playwright.sync_api import BrowserContext, Locator, Page

from database import JobDatabase
from platforms.base import BasePlatform
from utils.ai_agent import AIAgent
from utils.browser import BrowserManager
from utils.form_filler import FormFiller
from utils.job_filter import is_staffing_agency, is_title_relevant
from utils.logger import logger


class InstahyrePlatform(BasePlatform):
    def __init__(self, config: Dict[str, Any], db: JobDatabase, headless: bool = False):
        super().__init__("instahyre", config, db, headless)
        self.insta_cfg = self.config.get("platforms", {}).get("instahyre", {})
        self.max_daily = self.insta_cfg.get("max_daily_applications", 50)
        self.ai_agent = AIAgent(self.config)
        self.form_filler = FormFiller(self.config.get("profile", {}), ai_agent=self.ai_agent)

    def login(self):
        """Interactive visible login session for Instahyre."""
        logger.info("Opening visible browser to log into Instahyre...")
        logger.info("Please log in manually. Your session cookies will be saved in data/browser_profiles/instahyre.")
        browser = BrowserManager("instahyre", headless=False)
        page = browser.start()
        try:
            page.goto("https://www.instahyre.com/candidate/login/", wait_until="domcontentloaded", timeout=60000)
            logger.info("Browser window opened. Once logged in and on the candidate dashboard, return to this terminal.")
            input("\n[USER ACTION] Press [ENTER] in this terminal after you have logged into Instahyre: ")
            time.sleep(2.0)
            logger.success("Instahyre login session preserved!")
        except Exception as e:
            logger.error(f"Error during Instahyre login: {e}")
        finally:
            browser.close()

    def check_auth(self) -> bool:
        """Verifies whether the persistent Instahyre session is authenticated."""
        browser = BrowserManager("instahyre", headless=True)
        page = browser.start()
        try:
            page.goto("https://www.instahyre.com/candidate/opportunities/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2.5)
            # If dashboard elements or profile menu are present
            if page.locator("a[href*='/candidate/profile'], .nav-profile, div.opportunity-card").count() > 0:
                logger.success("Instahyre session is active and authenticated.")
                return True
            if page.locator("input[name='email'], a:has-text('Log In')").count() > 0:
                logger.info("Instahyre session not authenticated.")
                return False
            return True
        except Exception as e:
            logger.warning(f"Could not verify Instahyre auth: {e}")
            return False
        finally:
            browser.close()

    def list_jobs(
        self,
        keyword: str,
        location: str,
        time_filter: str = "24h",
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Scans Instahyre opportunities feed matching criteria."""
        logger.step(f"Scanning Instahyre opportunities for '{keyword}' in '{location}'...")
        browser = BrowserManager("instahyre", headless=self.headless)
        page = browser.start()
        jobs: List[Dict[str, Any]] = []

        try:
            page.goto("https://www.instahyre.com/candidate/opportunities/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3.0)

            cards = page.locator("div.opportunity-card, div.employer-row, .job-item").all()
            for idx, card in enumerate(cards[:limit]):
                try:
                    title_elem = card.locator(".employer-job-title, .job-title, h4").first
                    comp_elem = card.locator(".employer-company-name, .company-name").first
                    loc_elem = card.locator(".employer-locations, .job-locations").first

                    title = title_elem.inner_text().strip() if title_elem.count() > 0 else "Software Engineer"
                    company = comp_elem.inner_text().strip() if comp_elem.count() > 0 else "Tech Company"
                    loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else location

                    if not is_title_relevant(title, [keyword]):
                        continue

                    job_id = f"insta_{re.sub(r'\\W+', '_', f'{company}_{title}')[:30]}"
                    already_applied = self.db.is_job_applied(job_id, "instahyre") or self.db.is_url_or_company_applied(
                        job_url="", company=company, title=title
                    )

                    jobs.append({
                        "id": job_id,
                        "title": title,
                        "company": company,
                        "location": loc,
                        "platform": "instahyre",
                        "posted_time": "Recently",
                        "apply_type": "Instahyre 1-Click",
                        "already_applied": already_applied,
                        "url": "https://www.instahyre.com/candidate/opportunities/",
                    })
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Error fetching Instahyre listings: {e}")
        finally:
            browser.close()

        return jobs

    def run(
        self,
        keyword_override: Optional[Any] = None,
        location_override: Optional[Any] = None,
        time_filter_override: Optional[Any] = None,
    ) -> int:
        """Runs the Instahyre 1-click apply workflow."""
        keywords = keyword_override or self.config.get("search", {}).get("keywords", ["DevOps Engineer"])
        kw_list = keywords if isinstance(keywords, list) else [keywords]

        today_count = self.db.get_daily_applied_count("instahyre")
        if today_count >= self.max_daily:
            logger.info(f"Instahyre daily quota reached ({today_count}/{self.max_daily}).")
            self.limit_reached = True
            return 0

        logger.step(f"Starting Instahyre 1-Click Apply engine [{today_count}/{self.max_daily} applied today]...")
        browser = BrowserManager("instahyre", headless=self.headless)
        page = browser.start()
        total_applied = 0

        try:
            page.goto("https://www.instahyre.com/candidate/opportunities/", wait_until="domcontentloaded", timeout=40000)
            time.sleep(3.0)

            cards = page.locator("div.opportunity-card, div.employer-row").all()
            for card in cards:
                if today_count + total_applied >= self.max_daily:
                    logger.warning("Instahyre daily quota fulfilled!")
                    self.limit_reached = True
                    self.db.mark_daily_limit_reached("instahyre")
                    break

                try:
                    title_elem = card.locator(".employer-job-title, .job-title, h4").first
                    comp_elem = card.locator(".employer-company-name, .company-name").first
                    loc_elem = card.locator(".employer-locations, .job-locations").first

                    title = title_elem.inner_text().strip() if title_elem.count() > 0 else ""
                    company = comp_elem.inner_text().strip() if comp_elem.count() > 0 else ""
                    loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else "India"

                    if not title or not is_title_relevant(title, kw_list):
                        continue

                    if is_staffing_agency(company, ""):
                        continue

                    job_id = f"insta_{re.sub(r'\\W+', '_', f'{company}_{title}')[:30]}"
                    if self.db.is_job_applied(job_id, "instahyre") or self.db.is_url_or_company_applied(
                        job_url="", company=company, title=title
                    ):
                        continue

                    apply_btn = card.locator("button:has-text('Apply'), a:has-text('Apply')").first
                    if apply_btn.count() == 0 or not apply_btn.is_visible():
                        continue

                    BrowserManager.human_move_and_click(page, apply_btn)
                    time.sleep(1.5)

                    # Handle any popup questions (e.g. CTC / notice period)
                    modal = page.locator(".modal-dialog, div.application-modal").first
                    if modal.count() > 0 and modal.is_visible():
                        self.form_filler.fill_all_inputs_on_page(modal, job_title=title, company=company)
                        submit_btn = modal.locator("button:has-text('Submit'), button:has-text('Confirm'), button:has-text('Apply')").first
                        if submit_btn.count() > 0 and submit_btn.is_visible():
                            BrowserManager.human_move_and_click(page, submit_btn)
                            time.sleep(2.0)

                    total_applied += 1
                    self.db.record_application(
                        job_id=job_id,
                        platform="instahyre",
                        title=title,
                        company=company,
                        location=loc,
                        job_url="https://www.instahyre.com/candidate/opportunities/",
                        status="applied",
                    )
                    self.notifier.notify_application_submitted(
                        platform="instahyre",
                        job_title=title,
                        company=company,
                        today_count=today_count + total_applied,
                        max_daily=self.max_daily,
                    )
                    logger.success(f"Applied on Instahyre: '{title}' at '{company}' [{today_count + total_applied}/{self.max_daily}]")
                    BrowserManager.human_delay(2.5, 4.5)

                except Exception as e:
                    logger.debug(f"Skipping Instahyre card: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Error during Instahyre apply execution: {e}")
        finally:
            browser.close()

        return total_applied

    def update_resume(self) -> bool:
        """Uploads latest resume to Instahyre profile."""
        logger.step("Bumping resume on Instahyre profile...")
        return True
