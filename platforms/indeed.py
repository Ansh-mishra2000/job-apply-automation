"""
Indeed Platform Automation Module.
Supports:
1. Multi-page job search with date freshness and experience filters.
2. "Easily apply" (Indeed Apply) modal and iframe automation.
3. Agency & staffing body-shop exclusion.
4. Form-filling with regex heuristics and AI resolver.
5. Persistent browser contexts and daily quota enforcement.
"""

from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus
from playwright.sync_api import BrowserContext, Locator, Page

from database import JobDatabase
from platforms.base import BasePlatform
from utils.ai_agent import AIAgent
from utils.ats_filler import ExternalATSHandler
from utils.browser import BrowserManager
from utils.form_filler import FormFiller
from utils.job_filter import (
    calculate_cv_skills_match,
    extract_posted_time_from_text,
    has_blacklisted_skills,
    is_experience_eligible,
    is_posted_within_window,
    is_staffing_agency,
    is_title_relevant,
)
from utils.logger import logger


class IndeedPlatform(BasePlatform):
    def __init__(self, config: Dict[str, Any], db: JobDatabase, headless: bool = False):
        super().__init__("indeed", config, db, headless)
        self.indeed_cfg = self.config.get("platforms", {}).get("indeed", {})
        self.max_daily = self.indeed_cfg.get("max_daily_applications", 50)
        self.easily_apply_only = self.indeed_cfg.get("easily_apply_only", True)
        self.exclude_agencies = self.config.get("search", {}).get("exclude_staffing_agencies", True)
        self.exclude_skills = self.config.get("search", {}).get("exclude_skills", None)
        self.ats_handler = ExternalATSHandler(self.config)
        self.ai_agent = AIAgent(self.config)
        self.form_filler = FormFiller(self.config.get("profile", {}), ai_agent=self.ai_agent)

    def _build_search_url(
        self,
        keyword: str,
        location: str,
        time_filter: Optional[str] = None,
        page_no: int = 0,
    ) -> str:
        """
        Constructs Indeed search URL with pagination and date filter:
        - 24h -> fromage=1
        - 7d -> fromage=7
        - 14d / 15d -> fromage=14
        - 30d -> fromage=30
        - page_no -> start = page_no * 10
        """
        if isinstance(location, list):
            loc = location[0] if location else "India"
        else:
            loc = str(location).strip() if (location and str(location).strip()) else "India"

        if isinstance(keyword, list):
            kw = keyword[0] if keyword else "DevOps Engineer"
        else:
            kw = str(keyword).strip() if (keyword and str(keyword).strip()) else "DevOps Engineer"

        is_india = any(
            c in loc.lower()
            for c in [
                "india", "noida", "bengaluru", "bangalore", "delhi",
                "mumbai", "hyderabad", "pune", "chennai", "gurugram", "gurgaon"
            ]
        )
        base = "https://in.indeed.com/jobs?" if is_india else "https://www.indeed.com/jobs?"

        params = [
            f"q={quote_plus(kw)}",
            f"l={quote_plus(loc)}",
            "sort=date",
        ]

        t_filter = time_filter or self.config.get("search", {}).get("date_posted", "30d")
        if isinstance(t_filter, list):
            order = ["30d", "15d", "7d", "24h"]
            t_filter = next((w for w in order if w in t_filter), t_filter[-1] if t_filter else "30d")
        t_clean = str(t_filter).lower().strip()

        if t_clean in ("24h", "past_24h", "1d", "day"):
            params.append("fromage=1")
        elif t_clean in ("7d", "past_7d", "past_week", "week"):
            params.append("fromage=7")
        elif t_clean in ("15d", "14d", "past_15d"):
            params.append("fromage=14")
        elif t_clean in ("30d", "past_30d", "month", "past_month"):
            params.append("fromage=30")

        if page_no > 0:
            params.append(f"start={page_no * 10}")

        return base + "&".join(params)

    def login(self):
        """Interactive visible login session for Indeed."""
        logger.info("Opening visible browser to log into Indeed...")
        logger.info("Please log in manually. Your session cookies will be saved in data/browser_profiles/indeed.")
        browser = BrowserManager("indeed", headless=False)
        page = browser.start()
        try:
            page.goto("https://secure.indeed.com/auth", wait_until="domcontentloaded", timeout=60000)
            logger.info("Browser window opened. Once logged in and on the Indeed homepage, return to this terminal.")
            input("\n[USER ACTION] Press [ENTER] in this terminal after you have logged into Indeed: ")
            time.sleep(2.0)
            logger.success("Indeed login session preserved!")
        except Exception as e:
            logger.error(f"Error during Indeed login: {e}")
        finally:
            browser.close()

    def check_auth(self) -> bool:
        """Verifies whether the persistent Indeed session has authenticated cookies."""
        logger.step("Checking Indeed session authentication...")
        browser = BrowserManager("indeed", headless=True)
        page = browser.start()
        try:
            page.goto("https://in.indeed.com/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2.5)
            # Check for signed-in profile elements
            profile_selectors = [
                "a[href*='/account']",
                "button[id*='AccountMenu']",
                "[data-gnav-element='profile']",
                "a[data-gnav-element='user-account']",
                "div.gnav-UserMenu",
            ]
            for sel in profile_selectors:
                if page.locator(sel).count() > 0:
                    logger.success("Indeed session is active and authenticated.")
                    return True

            # If sign-in links are prominent, not authenticated
            if page.locator("a:has-text('Sign in'), a[href*='secure.indeed.com/auth']").count() > 0:
                logger.info("Indeed session not authenticated (guest mode).")
                return False

            return True
        except Exception as e:
            logger.warning(f"Could not verify Indeed auth: {e}")
            return False
        finally:
            browser.close()

    def _check_limit(self, page: Page) -> bool:
        """Checks if an application limit, CAPTCHA, or block is present."""
        limit_patterns = [
            "you've reached the application limit",
            "exceeded the daily application limit",
            "too many requests",
            "unusual traffic from your computer network",
            "verify you are human",
            "verify you are a human",
            "human verification",
            "cloudflare",
            "challenge-running",
        ]
        text_content = ""
        try:
            alerts = page.locator(".alert, [role='alert'], #challenge-running, .cf-browser-verification").all()
            for a in alerts:
                if a.is_visible():
                    text_content += " " + a.inner_text().lower()
            text_content += " " + page.title().lower()
        except Exception:
            pass

        for pat in limit_patterns:
            if pat in text_content:
                return True
        return False

    def _fill_indeed_apply(self, page: Page, job_title: str, company_name: str) -> bool:
        """
        Automates the multi-step Indeed Apply modal / iframe.
        Fills contact info, selects resume, answers screening questions, reviews, and submits.
        """
        logger.step(f"Executing Indeed Apply wizard for: '{job_title}' at '{company_name}'")
        try:
            time.sleep(2.5)
            # Find the active container (modal or iframe)
            target = page
            try:
                iframe_loc = page.locator("iframe[name='indeed-apply-iframe']")
                cnt = iframe_loc.count() if hasattr(iframe_loc, "count") else 0
                if isinstance(cnt, int) and cnt > 0:
                    target = page.frame_locator("iframe[name='indeed-apply-iframe']")
            except Exception:
                pass

            max_steps = 8
            for step in range(1, max_steps + 1):
                time.sleep(1.5)

                if self._check_limit(page):
                    logger.warning("Indeed daily limit or verification barrier reached!")
                    self.limit_reached = True
                    self.db.mark_daily_limit_reached("indeed")
                    return False

                # 1. Fill input fields
                inputs = target.locator("input[type='text'], input[type='number'], input[type='tel'], input[type='email'], textarea").all()
                for inp in inputs:
                    try:
                        if not inp.is_visible():
                            continue
                        current_val = inp.input_value()
                        if current_val and current_val.strip():
                            continue  # Already pre-filled

                        lbl = ""
                        inp_id = inp.get_attribute("id")
                        if inp_id:
                            lbl_elem = target.locator(f"label[for='{inp_id}']").first
                            if lbl_elem.count() > 0:
                                lbl = lbl_elem.inner_text().strip()

                        if not lbl:
                            lbl = (
                                inp.get_attribute("aria-label")
                                or inp.get_attribute("placeholder")
                                or inp.get_attribute("name")
                                or ""
                            )

                        ans = self.form_filler.get_answer_for_text_question(lbl)
                        if ans:
                            inp.fill(ans)
                            time.sleep(0.3)
                    except Exception:
                        pass

                # 2. Handle Radio Buttons & Dropdowns
                radios = target.locator("input[type='radio']").all()
                for r in radios:
                    try:
                        if not r.is_visible():
                            continue
                        # If already checked in this group, continue
                        r_name = r.get_attribute("name")
                        if r_name and target.locator(f"input[type='radio'][name='{r_name}']:checked").count() > 0:
                            continue
                        # Prefer affirmative / yes options
                        r_val = (r.get_attribute("value") or "").lower()
                        if r_val in ("yes", "y", "true", "1") or r == radios[0]:
                            r.check(force=True)
                            time.sleep(0.2)
                    except Exception:
                        pass

                # 3. Handle File Upload (Resume)
                from config_loader import get_resume_path
                resume_path = get_resume_path(self.config)
                if resume_path:
                    file_inps = target.locator("input[type='file']").all()
                    for fi in file_inps:
                        try:
                            fi.set_input_files(str(resume_path))
                            time.sleep(1.0)
                        except Exception:
                            pass

                # 4. Check for Final Submit Button
                submit_btn = target.locator(
                    "button:has-text('Submit your application'), "
                    "button:has-text('Submit application'), "
                    "button:has-text('Submit'), "
                    "button[aria-label*='Submit']"
                ).first

                if submit_btn.count() > 0 and submit_btn.is_visible():
                    submit_btn.click()
                    time.sleep(3.0)
                    logger.success(f"Submitted Indeed application for '{job_title}' at '{company_name}'!")
                    return True

                # 5. Check for 'Continue' or 'Review' button
                continue_btn = target.locator(
                    "button:has-text('Continue'), "
                    "button:has-text('Next'), "
                    "button:has-text('Review your application'), "
                    "button[aria-label*='Continue']"
                ).first

                if continue_btn.count() > 0 and continue_btn.is_visible():
                    continue_btn.click()
                    time.sleep(2.0)
                else:
                    # No continue or submit button found
                    break

            return False
        except Exception as e:
            logger.warning(f"Error in Indeed Apply wizard: {e}")
            return False

    def list_jobs(
        self,
        keyword: str,
        location: str,
        time_filter: str = "24h",
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Searches and returns job listings matching criteria without applying."""
        browser = BrowserManager("indeed", headless=self.headless)
        page = browser.start()
        jobs: List[Dict[str, Any]] = []

        try:
            logger.info(f"Searching Indeed jobs for '{keyword}' in '{location}' [Filter: {time_filter}]...")
            search_url = self._build_search_url(keyword, location, time_filter=time_filter, page_no=0)
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3.0)

            BrowserManager.smooth_scroll(page, scrolls=3, distance=500)
            cards = page.locator("div.job_seen_beacon, div.cardOutline, td.resultContent").all()

            for card in cards[:limit]:
                try:
                    title_elem = card.locator("h2.jobTitle span, a[data-jk] span, .jobTitle a").first
                    if title_elem.count() == 0:
                        continue
                    job_title = title_elem.inner_text().strip()

                    cfg_keywords = self.config.get("search", {}).get("keywords", [])
                    rel_targets = list(dict.fromkeys([keyword] + (cfg_keywords if isinstance(cfg_keywords, list) else [cfg_keywords])))
                    if not is_title_relevant(job_title, rel_targets):
                        continue

                    # Company name
                    comp_elem = card.locator("span[data-testid='company-name'], span.companyName, .companyName").first
                    company_name = comp_elem.inner_text().strip() if comp_elem.count() > 0 else "Unknown Company"

                    # Agency filter
                    if self.exclude_agencies and is_staffing_agency(company_name, card.inner_text()):
                        continue

                    # Extract Job ID
                    job_id = card.get_attribute("data-jk") or ""
                    link = card.locator("a[data-jk], a[href*='/rc/clk'], a[href*='/viewjob']").first
                    if not job_id and link.count() > 0:
                        job_id = link.get_attribute("data-jk") or ""
                        if not job_id:
                            m = re.search(r"jk=([a-f0-9]+)", link.get_attribute("href") or "")
                            if m:
                                job_id = m.group(1)

                    if not job_id:
                        continue

                    applied = self.db.is_job_applied(job_id, "indeed")

                    # Location
                    loc_elem = card.locator("div[data-testid='text-location'], .companyLocation").first
                    job_loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else location

                    # Freshness
                    time_elem = card.locator("span.date, span[data-testid='myJobsStateDate']").first
                    posted_time = time_elem.inner_text().strip() if time_elem.count() > 0 else "Recently"

                    # Easily Apply hint
                    is_easily_apply = card.locator("span.iaIcon, span:has-text('Easily apply'), span:has-text('Apply with Indeed')").count() > 0

                    jobs.append({
                        "id": job_id,
                        "title": job_title,
                        "company": company_name,
                        "location": job_loc,
                        "platform": "Indeed",
                        "posted_time": posted_time,
                        "experience": "0-3 Yrs",
                        "apply_type": "Easily Apply" if is_easily_apply else "External Site",
                        "already_applied": applied,
                    })
                except Exception:
                    continue

        except Exception as e:
            logger.error(f"Error fetching Indeed job listings: {e}")
        finally:
            browser.close()

        return jobs

    def run(
        self,
        keyword_override: Optional[str] = None,
        location_override: Optional[str] = None,
        time_filter_override: Optional[str] = None,
    ) -> int:
        """Executes full search and application cycle for Indeed."""
        if self.limit_reached or self.db.is_daily_limit_reached("indeed"):
            logger.info("Indeed daily limit reached for today. Skipping Indeed.")
            return 0

        today_count = self.db.get_daily_applied_count("indeed")
        if today_count >= self.max_daily:
            logger.info(f"Indeed daily quota reached ({today_count}/{self.max_daily}).")
            self.db.mark_daily_limit_reached("indeed")
            return 0

        logger.info(f"Starting Indeed application engine (Applied today: {today_count}/{self.max_daily}).")
        browser = BrowserManager("indeed", headless=self.headless)
        page = browser.start()
        total_applied = 0
        try:
            if keyword_override:
                keywords = keyword_override if isinstance(keyword_override, list) else [keyword_override]
            else:
                keywords = self.config.get("search", {}).get("keywords", ["DevOps Engineer"])

            if location_override:
                locations = location_override if isinstance(location_override, list) else [location_override]
            else:
                locations = self.config.get("search", {}).get("locations", ["India"])
            time_filter = time_filter_override or self.config.get("search", {}).get("date_posted", "30d")
            max_pages = int(self.config.get("search", {}).get("max_pages_per_keyword", 3))

            for keyword in keywords:
                if self.limit_reached or (today_count + total_applied) >= self.max_daily:
                    break

                for location in locations:
                    if self.limit_reached or (today_count + total_applied) >= self.max_daily:
                        break

                    for page_no in range(max_pages):
                        if self.limit_reached or (today_count + total_applied) >= self.max_daily:
                            break

                        search_url = self._build_search_url(keyword, location, time_filter=time_filter, page_no=page_no)
                        logger.step(f"Searching Indeed jobs (Page {page_no + 1}) for '{keyword}' in '{location}'...")
                        page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(3.0)

                        if self._check_limit(page):
                            logger.warning("Indeed rate limit / barrier detected!")
                            self.limit_reached = True
                            self.db.mark_daily_limit_reached("indeed")
                            break

                        BrowserManager.smooth_scroll(page, scrolls=2, distance=400)
                        cards = page.locator("div.job_seen_beacon, div.cardOutline, td.resultContent").all()
                        if not cards:
                            logger.info(f"No job cards found on Indeed Page {page_no + 1}. Moving to next keyword.")
                            break

                        for card in cards:
                            if self.limit_reached or (today_count + total_applied) >= self.max_daily:
                                break

                            try:
                                title_elem = card.locator("h2.jobTitle span, a[data-jk] span, .jobTitle a").first
                                if title_elem.count() == 0:
                                    continue
                                job_title = title_elem.inner_text().strip()

                                if not is_title_relevant(job_title, keywords):
                                    continue
                                if has_blacklisted_skills([job_title], self.exclude_skills):
                                    continue

                                comp_elem = card.locator("span[data-testid='company-name'], span.companyName").first
                                company_name = comp_elem.inner_text().strip() if comp_elem.count() > 0 else "Unknown Company"

                                if self.exclude_agencies and is_staffing_agency(company_name, card.inner_text()):
                                    logger.info(f"Skipping staffing agency on Indeed: '{company_name}' ({job_title})")
                                    continue

                                job_id = card.get_attribute("data-jk") or ""
                                link = card.locator("a[data-jk], a[href*='/rc/clk'], a[href*='/viewjob']").first
                                if not job_id and link.count() > 0:
                                    job_id = link.get_attribute("data-jk") or ""
                                    if not job_id:
                                        m = re.search(r"jk=([a-f0-9]+)", link.get_attribute("href") or "")
                                        if m:
                                            job_id = m.group(1)

                                if not job_id or self.db.is_job_applied(job_id, "indeed"):
                                    continue

                                # Check Easily Apply
                                is_easily_apply = card.locator("span.iaIcon, span:has-text('Easily apply'), span:has-text('Apply with Indeed')").count() > 0
                                if self.easily_apply_only and not is_easily_apply:
                                    continue

                                logger.step(f"Processing Indeed job: '{job_title}' at '{company_name}'")
                                # In-place card click to load detail pane
                                title_elem.evaluate("el => el.click()")
                                time.sleep(2.0)

                                # Look for apply button in detail pane
                                apply_btn = page.locator(
                                    "button#indeedApplyButton, "
                                    "button:has-text('Apply now'), "
                                    "button:has-text('Easily apply'), "
                                    "div.indeed-apply-widget button"
                                ).first

                                if apply_btn.count() == 0 or not apply_btn.is_visible():
                                    continue

                                apply_btn.click()
                                time.sleep(2.5)

                                success = self._fill_indeed_apply(page, job_title, company_name)
                                if success:
                                    total_applied += 1
                                    self.db.record_application(
                                        job_id=job_id,
                                        platform="indeed",
                                        title=job_title,
                                        company=company_name,
                                        location=location,
                                        job_url=f"https://www.indeed.com/viewjob?jk={job_id}",
                                        status="applied",
                                    )
                                    self.notifier.notify_application_submitted(
                                        platform="indeed",
                                        job_title=job_title,
                                        company=company_name,
                                        job_url=f"https://www.indeed.com/viewjob?jk={job_id}",
                                        today_count=today_count + total_applied,
                                        max_daily=self.max_daily,
                                    )
                                    logger.success(
                                        f"Successfully applied on Indeed to {job_title} at {company_name} "
                                        f"[{today_count + total_applied}/{self.max_daily} today]"
                                    )
                                    BrowserManager.human_delay(
                                        self.config.get("execution", {}).get("human_delay_min", 3.0),
                                        self.config.get("execution", {}).get("human_delay_max", 6.0),
                                    )
                                else:
                                    self.db.record_application(
                                        job_id=job_id,
                                        platform="indeed",
                                        title=job_title,
                                        company=company_name,
                                        location=location,
                                        job_url=f"https://www.indeed.com/viewjob?jk={job_id}",
                                        status="skipped",
                                        reason="Incomplete form or limit reached",
                                    )

                            except Exception as e:
                                logger.warning(f"Error processing Indeed card: {e}")
                                continue

        except Exception as e:
            logger.error(f"Indeed automation error: {e}")
        finally:
            browser.close()

        return total_applied

    def update_resume(self) -> bool:
        """Refreshes the latest resume on Indeed to boost recruiter ranking."""
        logger.step("Refreshing Indeed profile resume...")
        from config_loader import get_resume_path
        resume = get_resume_path(self.config)
        if not resume:
            return False

        browser = BrowserManager("indeed", headless=self.headless)
        page = browser.start()
        try:
            page.goto("https://profile.indeed.com/resume", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3.0)
            file_inp = page.locator("input[type='file']").first
            if file_inp.count() > 0:
                file_inp.set_input_files(str(resume))
                time.sleep(3.0)
                logger.success("Indeed resume updated successfully!")
                return True
            return False
        except Exception as e:
            logger.warning(f"Could not refresh Indeed resume: {e}")
            return False
        finally:
            browser.close()
