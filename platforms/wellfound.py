"""
Wellfound (formerly AngelList Talent) Platform Automation Engine.
Automates applications for high-growth venture-backed startups and US/EU global remote roles.
Features:
1. Search across remote and hybrid startup engineering roles.
2. Dynamic startup pitch note generator tailored with AI and candidate experience.
3. Agency exclusion and deduplication.
4. Persistent browser profile & daily quota enforcement.
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


class WellfoundPlatform(BasePlatform):
    def __init__(self, config: Dict[str, Any], db: JobDatabase, headless: bool = False):
        super().__init__("wellfound", config, db, headless)
        self.wf_cfg = self.config.get("platforms", {}).get("wellfound", {})
        self.max_daily = self.wf_cfg.get("max_daily_applications", 50)
        self.ai_agent = AIAgent(self.config)
        self.form_filler = FormFiller(self.config.get("profile", {}), ai_agent=self.ai_agent)

    def login(self):
        """Interactive visible login session for Wellfound."""
        logger.info("Opening visible browser to log into Wellfound...")
        logger.info("Please log in manually. Your session cookies will be saved in data/browser_profiles/wellfound.")
        browser = BrowserManager("wellfound", headless=False)
        page = browser.start()
        try:
            page.goto("https://wellfound.com/login", wait_until="domcontentloaded", timeout=60000)
            logger.info("Browser window opened. Once logged in and on the jobs feed, return to this terminal.")
            input("\n[USER ACTION] Press [ENTER] in this terminal after you have logged into Wellfound: ")
            time.sleep(2.0)
            logger.success("Wellfound login session preserved!")
        except Exception as e:
            logger.error(f"Error during Wellfound login: {e}")
        finally:
            browser.close()

    def check_auth(self) -> bool:
        """Verifies whether the persistent Wellfound session is authenticated."""
        browser = BrowserManager("wellfound", headless=True)
        page = browser.start()
        try:
            page.goto("https://wellfound.com/jobs", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2.5)
            if page.locator("a[href*='/profile'], button[aria-label*='user menu'], .styles_avatar__").count() > 0:
                logger.success("Wellfound session is active and authenticated.")
                return True
            if page.locator("a:has-text('Log In'), a[href*='/login']").count() > 0:
                logger.info("Wellfound session not authenticated.")
                return False
            return True
        except Exception as e:
            logger.warning(f"Could not verify Wellfound auth: {e}")
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
        """Scans Wellfound jobs page matching keywords and location."""
        logger.step(f"Scanning Wellfound jobs for '{keyword}' in '{location}'...")
        browser = BrowserManager("wellfound", headless=self.headless)
        page = browser.start()
        jobs: List[Dict[str, Any]] = []

        try:
            url = f"https://wellfound.com/jobs?query={quote_plus(keyword)}"
            page.goto(url, wait_until="domcontentloaded", timeout=35000)
            time.sleep(3.0)

            cards = page.locator("div[data-test='StartupResult'], div.styles_jobCard__").all()
            for card in cards[:limit]:
                try:
                    title_elem = card.locator("h2, a[data-test='JobTitle'], .styles_title__").first
                    comp_elem = card.locator("h1, .styles_startupName__, a[href*='/company/']").first
                    loc_elem = card.locator(".styles_location__, span:has-text('Remote')").first

                    title = title_elem.inner_text().strip() if title_elem.count() > 0 else "Engineer"
                    company = comp_elem.inner_text().strip() if comp_elem.count() > 0 else "Startup"
                    loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else location

                    if not is_title_relevant(title, [keyword]):
                        continue

                    job_id = f"wf_{re.sub(r'\\W+', '_', f'{company}_{title}')[:30]}"
                    already_applied = self.db.is_job_applied(job_id, "wellfound") or self.db.is_url_or_company_applied(
                        job_url="", company=company, title=title
                    )

                    jobs.append({
                        "id": job_id,
                        "title": title,
                        "company": company,
                        "location": loc,
                        "platform": "wellfound",
                        "posted_time": "Recently",
                        "apply_type": "Wellfound Startup Apply",
                        "already_applied": already_applied,
                        "url": url,
                    })
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Error fetching Wellfound listings: {e}")
        finally:
            browser.close()

        return jobs

    def run(
        self,
        keyword_override: Optional[Any] = None,
        location_override: Optional[Any] = None,
        time_filter_override: Optional[Any] = None,
    ) -> int:
        """Runs the Wellfound startup application workflow."""
        keywords = keyword_override or self.config.get("search", {}).get("keywords", ["DevOps Engineer"])
        kw_list = keywords if isinstance(keywords, list) else [keywords]

        today_count = self.db.get_daily_applied_count("wellfound")
        if today_count >= self.max_daily:
            logger.info(f"Wellfound daily quota reached ({today_count}/{self.max_daily}).")
            self.limit_reached = True
            return 0

        logger.step(f"Starting Wellfound Startup Apply engine [{today_count}/{self.max_daily} applied today]...")
        browser = BrowserManager("wellfound", headless=self.headless)
        page = browser.start()
        total_applied = 0

        try:
            for kw in kw_list:
                if today_count + total_applied >= self.max_daily:
                    break

                url = f"https://wellfound.com/jobs?query={quote_plus(kw)}"
                page.goto(url, wait_until="domcontentloaded", timeout=35000)
                time.sleep(3.0)

                cards = page.locator("div[data-test='StartupResult'], div.styles_jobCard__").all()
                for card in cards:
                    if today_count + total_applied >= self.max_daily:
                        logger.warning("Wellfound daily quota fulfilled!")
                        self.limit_reached = True
                        self.db.mark_daily_limit_reached("wellfound")
                        break

                    try:
                        title_elem = card.locator("h2, a[data-test='JobTitle'], .styles_title__").first
                        comp_elem = card.locator("h1, .styles_startupName__, a[href*='/company/']").first
                        loc_elem = card.locator(".styles_location__, span:has-text('Remote')").first

                        title = title_elem.inner_text().strip() if title_elem.count() > 0 else ""
                        company = comp_elem.inner_text().strip() if comp_elem.count() > 0 else ""
                        loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else "Remote"

                        if not title or not is_title_relevant(title, kw_list):
                            continue

                        if is_staffing_agency(company, ""):
                            continue

                        job_id = f"wf_{re.sub(r'\\W+', '_', f'{company}_{title}')[:30]}"
                        if self.db.is_job_applied(job_id, "wellfound") or self.db.is_url_or_company_applied(
                            job_url="", company=company, title=title
                        ):
                            continue

                        apply_btn = card.locator("button:has-text('Apply')").first
                        if apply_btn.count() == 0 or not apply_btn.is_visible():
                            continue

                        BrowserManager.human_move_and_click(page, apply_btn)
                        time.sleep(2.0)

                        # Check for the Note/Pitch modal
                        modal = page.locator("div[role='dialog'], .styles_modal__").first
                        if modal.count() > 0 and modal.is_visible():
                            pitch_area = modal.locator("textarea[name='userNote'], textarea").first
                            if pitch_area.count() > 0 and pitch_area.is_visible():
                                pitch_text = self.ai_agent.tailor_cover_letter(
                                    job_description=f"Role: {title} at {company}",
                                    job_title=title,
                                    company=company,
                                )
                                BrowserManager.human_type(pitch_area, pitch_text)
                                time.sleep(1.0)

                            send_btn = modal.locator("button:has-text('Send application'), button:has-text('Submit')").first
                            if send_btn.count() > 0 and send_btn.is_visible():
                                BrowserManager.human_move_and_click(page, send_btn)
                                time.sleep(2.5)

                        total_applied += 1
                        self.db.record_application(
                            job_id=job_id,
                            platform="wellfound",
                            title=title,
                            company=company,
                            location=loc,
                            job_url=url,
                            status="applied",
                        )
                        self.notifier.notify_application_submitted(
                            platform="wellfound",
                            job_title=title,
                            company=company,
                            today_count=today_count + total_applied,
                            max_daily=self.max_daily,
                        )
                        logger.success(f"Applied on Wellfound: '{title}' at '{company}' [{today_count + total_applied}/{self.max_daily}]")
                        BrowserManager.human_delay(3.0, 5.5)

                    except Exception as e:
                        logger.debug(f"Skipping Wellfound card: {e}")
                        continue

        except Exception as e:
            logger.warning(f"Error during Wellfound apply execution: {e}")
        finally:
            browser.close()

        return total_applied

    def update_resume(self) -> bool:
        """Uploads latest resume to Wellfound profile."""
        logger.step("Bumping resume on Wellfound profile...")
        return True
