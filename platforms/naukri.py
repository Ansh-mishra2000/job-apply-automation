"""
Naukri.com job apply automation engine.
Supports persistent sessions, direct 1-click applies, recruiter questionnaire handling,
job listing search with time filters (24h, 7d, 15d, 30d), and daily quota detection.
"""

from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus
from playwright.sync_api import Locator, Page

from platforms.base import BasePlatform
from utils.browser import BrowserManager
from utils.form_filler import FormFiller
from utils.job_filter import (
    is_title_relevant,
    is_posted_within_window,
    extract_posted_time_from_text,
    has_blacklisted_skills,
    is_experience_eligible,
    calculate_cv_skills_match,
)
from utils.ats_filler import ExternalATSHandler
from utils.logger import logger


class NaukriPlatform(BasePlatform):
    def __init__(self, config: Dict[str, Any], db, headless: bool = False):
        super().__init__("naukri", config, db, headless)
        self.naukri_cfg = self.config.get("platforms", {}).get("naukri", {})
        self.max_daily = self.naukri_cfg.get("max_daily_applications", 50)
        self.form_filler = FormFiller(self.config.get("profile", {}))
        self.ats_handler = ExternalATSHandler(self.config)

    def login(self):
        """Interactive visible login session to authenticate and persist cookies."""
        logger.info("Opening visible browser window for Naukri login...")
        browser = BrowserManager("naukri", headless=False)
        page = browser.start()

        try:
            page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded")
            logger.info("=======================================================")
            logger.info("ACTION REQUIRED: Log into Naukri in the opened browser.")
            logger.info("Complete OTP if prompted. Ensure your profile / dashboard loads.")
            logger.info("=======================================================")

            print("\n[Input] Press ENTER in this terminal once you have successfully logged in: ", end="", flush=True)
            input()

            page.wait_for_timeout(2000)
            if "homepage" in page.url or "mnjuser" in page.url or page.locator(".nI-gNb-drawer").count() > 0:
                logger.success("Naukri session authenticated and saved successfully!")
            else:
                logger.warning("Session cookies saved. Please verify your login if issues persist.")
        finally:
            browser.close()

    def check_auth(self) -> bool:
        """Verifies whether the persistent profile is logged in on Naukri."""
        browser = BrowserManager("naukri", headless=True)
        page = browser.start()
        try:
            page.goto("https://www.naukri.com/mnjuser/homepage", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            if "nlogin" in page.url or "login" in page.url:
                return False
            return page.locator(".nI-gNb-drawer, a[href*='logout']").count() > 0 or "homepage" in page.url
        except Exception:
            return False
        finally:
            browser.close()

    def _build_search_url(
        self, keyword: str, location: str, time_filter: Optional[str] = None, page_no: int = 1
    ) -> str:
        """
        Constructs Naukri search URL with time filters and page pagination:
        - 24h -> days=1 / q_days=1
        - 7d  -> days=7 / q_days=7
        - 15d -> days=15 / q_days=15
        - 30d -> days=30 / q_days=30
        """
        loc = location.strip() if (location and location.strip()) else "India"
        k_slug = keyword.strip().lower().replace(" ", "-")
        l_slug = loc.strip().lower().replace(" ", "-")

        from config_loader import parse_experience_range
        min_exp, max_exp = parse_experience_range(self.config.get("search", {}).get("experience_years", "0-3"))
        exp_param = f"&experience={min_exp}&experience={max_exp}" if min_exp != max_exp else f"&experience={min_exp}"

        t_filter = time_filter or self.config.get("search", {}).get("date_posted", "30d")
        if isinstance(t_filter, list):
            order = ["30d", "15d", "7d", "24h"]
            t_filter = next((w for w in order if w in t_filter), t_filter[-1] if t_filter else "30d")
        t_clean = str(t_filter).lower().strip()

        days_param = ""
        if t_clean in ("24h", "past_24h", "1d", "day"):
            days_param = "&q_days=1&days=1"
        elif t_clean in ("7d", "past_7d", "past_week", "week"):
            days_param = "&q_days=7&days=7"
        elif t_clean in ("15d", "past_15d", "15days"):
            days_param = "&q_days=15&days=15"
        elif t_clean in ("30d", "past_30d", "past_month", "month"):
            days_param = "&q_days=30&days=30"

        if page_no > 1:
            return (
                f"https://www.naukri.com/{k_slug}-jobs-in-{l_slug}-{page_no}?"
                f"k={quote_plus(keyword)}&l={quote_plus(loc)}{exp_param}{days_param}&pageNo={page_no}"
            )

        return (
            f"https://www.naukri.com/{k_slug}-jobs-in-{l_slug}?"
            f"k={quote_plus(keyword)}&l={quote_plus(loc)}{exp_param}{days_param}"
        )

    def _check_limit_toast(self, page: Page) -> bool:
        """Detects if Naukri's daily application limit toast or alert has popped up."""
        limit_terms = [
            "daily application limit",
            "daily apply limit",
            "reached your daily",
            "exhausted your daily",
            "maximum applications allowed for today",
            "limit exceeded",
        ]
        try:
            elements = page.locator(".server-err, .toast, .toaster, .lightbox, .apply-message, div[role='alert']").all()
            for el in elements:
                if el.is_visible():
                    txt = el.inner_text().lower()
                    for term in limit_terms:
                        if term in txt:
                            return True
        except Exception:
            pass
        return False

    def _handle_naukri_chatbot_questions(self, page: Page, job_title: str = "", company_name: str = ""):
        """Answers recruiter screening chatbot or modal questions if shown after clicking apply."""
        try:
            chat_container = page.locator(".chatbot_drawer, .bot-wrapper, .apply-questions, div[class*='drawer']")
            if chat_container.count() > 0 and chat_container.first.is_visible():
                logger.info("Handling Naukri recruiter questionnaire...")
                time.sleep(1.5)

                self.form_filler.fill_all_inputs_on_page(chat_container.first, job_title=job_title, company=company_name)

                action_btn = chat_container.locator("button:has-text('Submit'), button:has-text('Save'), button.send-btn")
                if action_btn.count() > 0 and action_btn.first.is_visible():
                    action_btn.first.click()
                    time.sleep(2.0)
        except Exception as e:
            logger.warning(f"Note on questionnaire: {e}")

    def list_jobs(
        self,
        keyword: str,
        location: str,
        time_filter: str = "24h",
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Searches and returns job listings matching position, location, and time window."""
        browser = BrowserManager("naukri", headless=self.headless)
        page = browser.start()
        jobs: List[Dict[str, Any]] = []

        try:
            logger.info(f"Searching Naukri jobs for '{keyword}' in '{location}' [Filter: {time_filter}]...")
            search_url = self._build_search_url(keyword, location, time_filter=time_filter)
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3.0)

            BrowserManager.smooth_scroll(page, scrolls=3, distance=500)
            job_cards = page.locator(
                "div.cust-job-tuple, article.jobTuple, div.srp-jobtuple-wrapper"
            ).all()

            for card in job_cards[:limit]:
                try:
                    title_elem = card.locator("a.title, a.job-title").first
                    if title_elem.count() == 0:
                        continue

                    job_title = title_elem.inner_text().strip()
                    cfg_keywords = self.config.get("search", {}).get("keywords", [])
                    rel_targets = list(dict.fromkeys([keyword] + (cfg_keywords if isinstance(cfg_keywords, list) else [cfg_keywords])))
                    if not is_title_relevant(job_title, rel_targets):
                        continue

                    href = title_elem.get_attribute("href") or ""

                    job_id = card.get_attribute("data-job-id") or card.get_attribute("id") or ""
                    if not job_id and href:
                        m = re.search(r"-(\d+)\??", href)
                        if m:
                            job_id = m.group(1)

                    if not job_id:
                        continue

                    company_elem = card.locator("a.comp-name, a.subTitle").first
                    company_name = company_elem.inner_text().strip() if company_elem.count() > 0 else "Unknown Company"

                    loc_elem = card.locator(".loc-wrap, .loc, .location").first
                    job_loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else location

                    time_elem = card.locator(".job-post-day, span[class*='job-post-day'], span[class*='post-day'], span[class*='date'], span[class*='jpt'], .ni-job-tuple-icon-time + span, span.badge").first
                    card_raw_txt = card.inner_text().strip()
                    posted_time = time_elem.inner_text().strip() if time_elem.count() > 0 else ""
                    if not posted_time or posted_time.lower() in ("recently", ""):
                        posted_time = extract_posted_time_from_text(card_raw_txt) or posted_time or "Recently"

                    if posted_time and not is_posted_within_window(posted_time, time_filter):
                        continue

                    applied = self.db.is_job_applied(job_id, "naukri")

                    # 1. Experience check (strict candidate threshold 0-3 years)
                    exp_elem = card.locator(".exp-wrap, .exp, li.experience, span.exp, span.ni-job-tuple-icon-experience").first
                    exp_text = exp_elem.inner_text().strip() if exp_elem.count() > 0 else ""
                    if exp_text and not is_experience_eligible(exp_text, max_allowed_min_exp=3.0):
                        continue

                    # 2. Skill tags & Blacklist (exclude SAP, Salesforce, etc.)
                    tags_elems = card.locator("ul.tags-gt li, .tag-li, .ellipsis, .tags").all()
                    skill_tags = [t.inner_text().strip() for t in tags_elems if t.inner_text().strip()]
                    exclude_skills = self.config.get("search", {}).get("exclude_skills", None)
                    if has_blacklisted_skills(skill_tags + [job_title], blacklisted_skills=exclude_skills):
                        continue

                    cv_skills = self.config.get("profile", {}).get("cv_skills", None)
                    match_count, matched_skills = calculate_cv_skills_match(skill_tags + [job_title], cv_skills=cv_skills)

                    jobs.append({
                        "id": job_id,
                        "title": job_title,
                        "company": company_name,
                        "location": job_loc,
                        "platform": "Naukri",
                        "posted_time": posted_time,
                        "experience": exp_text or "0-3 Yrs",
                        "skill_match_count": match_count,
                        "matched_skills": matched_skills,
                        "apply_type": "Direct / Fast Apply",
                        "already_applied": applied,
                        "url": href,
                    })
                except Exception:
                    continue

        except Exception as e:
            logger.error(f"Error fetching Naukri job listings: {e}")
        finally:
            browser.close()

        return jobs

    def _process_search_page(
        self,
        page: Page,
        browser: BrowserManager,
        time_filter: str,
        combined_targets: List[str],
        location: str,
        today_count: int,
        total_applied_this_run: int,
    ) -> Tuple[int, bool]:
        """Processes all eligible job cards on the current Naukri search results page."""
        BrowserManager.smooth_scroll(page, scrolls=3, distance=500)

        # Extract job cards metadata upfront to avoid stale Playwright locators
        job_cards_data = []
        seen_jids = set()
        raw_cards = page.locator("div.cust-job-tuple, article.jobTuple, div.srp-jobtuple-wrapper").all()
        for c in raw_cards:
            try:
                title_elem = c.locator("a.title, a.job-title").first
                if title_elem.count() == 0:
                    continue
                href = title_elem.get_attribute("href", timeout=1000) or ""
                job_id = c.get_attribute("data-job-id", timeout=1000) or c.get_attribute("id", timeout=1000) or ""
                if not job_id and href:
                    m = re.search(r"-(\d+)\??", href)
                    if m:
                        job_id = m.group(1)
                if not job_id or job_id in seen_jids or not href:
                    continue
                job_title = title_elem.inner_text(timeout=1000).strip()

                # 1. Strict title relevance check (rejecting unwanted roles like Social Media Intern, Content Creator, etc.)
                if not is_title_relevant(job_title, combined_targets):
                    logger.info(f"Skipping irrelevant role on Naukri: '{job_title}' (does not match target roles: {combined_targets})")
                    continue

                # 2. Strict experience check (rejecting senior roles > 3 years min experience)
                exp_elem = c.locator(".exp-wrap, .exp, li.experience, span.exp, span.ni-job-tuple-icon-experience").first
                exp_text = exp_elem.inner_text(timeout=1000).strip() if exp_elem.count() > 0 else ""
                if exp_text and not is_experience_eligible(exp_text, max_allowed_min_exp=3.0):
                    logger.info(f"Skipping senior role on Naukri: '{job_title}' requires '{exp_text}' (exceeds candidate experience 0-3 yrs)")
                    continue

                # 3. Skill tags & Blacklist (exclude SAP, Salesforce, Snaplogic)
                tags_elems = c.locator("ul.tags-gt li, .tag-li, .ellipsis, .tags").all()
                skill_tags = [t.inner_text(timeout=500).strip() for t in tags_elems if t.inner_text(timeout=500).strip()]
                exclude_skills = self.config.get("search", {}).get("exclude_skills", None)
                if has_blacklisted_skills(skill_tags + [job_title], blacklisted_skills=exclude_skills):
                    logger.info(f"Skipping job with blacklisted skill on Naukri: '{job_title}' (tags: {skill_tags})")
                    continue

                # 4. Strict freshness check (rejecting jobs older than time_filter)
                time_elem = c.locator(".job-post-day, span[class*='job-post-day'], span[class*='post-day'], span[class*='date'], span[class*='jpt'], .ni-job-tuple-icon-time + span, span.badge").first
                c_raw = c.inner_text(timeout=1000)
                posted_time = time_elem.inner_text(timeout=1000).strip() if time_elem.count() > 0 else ""
                if not posted_time or posted_time.lower() in ("recently", ""):
                    posted_time = extract_posted_time_from_text(c_raw) or posted_time or "Recently"

                if posted_time and not is_posted_within_window(posted_time, time_filter):
                    logger.info(f"Skipping older job on Naukri: '{job_title}' posted '{posted_time}' (exceeds {time_filter} window)")
                    continue

                # 5. Calculate CV skills match score
                cv_skills = self.config.get("profile", {}).get("cv_skills", None)
                skill_match_count, matched_skills = calculate_cv_skills_match(skill_tags + [job_title], cv_skills=cv_skills)

                comp_elem = c.locator("a.comp-name, a.subTitle").first
                comp_name = comp_elem.inner_text(timeout=1000).strip() if comp_elem.count() > 0 else "Unknown Company"

                # Deduplication check across company & title to prevent revisiting the same external portal/posting
                if self.db.is_url_or_company_applied(company=comp_name, title=job_title):
                    logger.info(f"Skipping already applied/processed role on Naukri: '{job_title}' at '{comp_name}'")
                    continue

                card_txt = c.inner_text(timeout=1000).lower()
                is_priority = (
                    "early applicant" in card_txt
                    or "top" in card_txt
                    or "preferred" in card_txt
                    or c.locator(".hot-job, .early-applicant, .keyskill-match, span.badge:has-text('Early')").count() > 0
                )
                # Prioritize native Direct Apply over external redirects
                is_external_hint = (
                    "company site" in card_txt
                    or c.locator(".ni-job-tuple-icon-company, [title*='company site']").count() > 0
                )

                seen_jids.add(job_id)
                job_cards_data.append({
                    "id": job_id,
                    "href": href,
                    "title": job_title,
                    "company": comp_name,
                    "posted_time": posted_time,
                    "experience": exp_text or "0-3 Yrs",
                    "skill_match_count": skill_match_count,
                    "matched_skills": matched_skills,
                    "is_priority": is_priority,
                    "is_external_hint": is_external_hint,
                })
            except Exception:
                continue

        if not job_cards_data:
            return 0, False

        # Sort candidates so native Direct Apply AND Early/Top Match AND high CV skill matches are applied to first
        ordered_jobs = sorted(
            job_cards_data,
            key=lambda j: (not j.get("is_external_hint", False), j["is_priority"], j["skill_match_count"]),
            reverse=True,
        )
        high_match_jobs = [j for j in ordered_jobs if j["skill_match_count"] >= 3]
        priority_jobs = [j for j in ordered_jobs if j["is_priority"]]
        direct_jobs = [j for j in ordered_jobs if not j.get("is_external_hint", False)]
        logger.info(
            f"Discovered {len(ordered_jobs)} eligible Naukri jobs on page "
            f"({len(direct_jobs)} direct apply, {len(high_match_jobs)} with high CV skills match, {len(priority_jobs)} Early/Top Match)."
        )

        if high_match_jobs:
            logger.info(f"⭐ Found {len(high_match_jobs)} jobs with high CV skills match! Prioritizing them first.")

        applied_on_page = 0
        for job_info in ordered_jobs:
            if self.limit_reached or (today_count + total_applied_this_run + applied_on_page) >= self.max_daily:
                logger.info(f"Reached daily application limit target ({self.max_daily}). Stopping.")
                return applied_on_page, False

            job_id = job_info["id"]
            if self.db.is_job_applied(job_id, "naukri"):
                continue

            href = job_info["href"]
            job_title = job_info["title"]
            company_name = job_info["company"]

            matched = job_info.get("matched_skills", [])
            skills_str = f" [Skills: {', '.join(matched[:3])}]" if matched else ""
            logger.step(
                f"Applying to Naukri Job #{job_id}: '{job_title}' at '{company_name}' "
                f"({job_info.get('experience', '0-3 Yrs')}){skills_str}"
            )

            try:
                job_page = browser.context.new_page()
                try:
                    job_page.goto(href, wait_until="domcontentloaded", timeout=25000)
                    time.sleep(2.0)

                    # Re-verify freshness on the actual job detail page (e.g. catches 'Posted: 3+ weeks ago')
                    page_header = job_page.locator(".styles_jph__header, .job-desc-header, .styles_jph, [class*='header'], [class*='info'], body").first
                    page_header_txt = page_header.inner_text(timeout=2000) if page_header.count() > 0 else ""
                    detail_posted_time = extract_posted_time_from_text(page_header_txt)
                    if detail_posted_time and not is_posted_within_window(detail_posted_time, time_filter):
                        logger.info(
                            f"Skipping older job on Naukri detail page: '{job_title}' posted '{detail_posted_time}' "
                            f"(exceeds {time_filter} window)"
                        )
                        continue

                    apply_btn = job_page.locator("button#apply-button, button:has-text('Apply')")
                    if apply_btn.count() == 0 or not apply_btn.first.is_visible():
                        continue

                    btn_text = apply_btn.first.inner_text().strip().lower()
                    if "company site" in btn_text:
                        ext_enabled = self.config.get("external_apply", {}).get("enabled", False)
                        if not ext_enabled:
                            logger.info(f"Skipping external application on Naukri: '{job_title}' at '{company_name}' ('Apply on company site')")
                            continue

                        logger.step(f"Opening external application on company site for: '{job_title}' at '{company_name}'")
                        ext_page = None
                        try:
                            with job_page.context.expect_page(timeout=8000) as new_page_info:
                                apply_btn.first.click()
                            ext_page = new_page_info.value
                        except Exception:
                            time.sleep(2.0)
                            if len(job_page.context.pages) > 1:
                                ext_page = job_page.context.pages[-1]
                            else:
                                ext_page = job_page

                        if ext_page:
                            # Wait for redirection to leave naukri.com and settle
                            logger.info(f"Waiting for external redirect to settle (current: {ext_page.url})...")
                            redirect_start = time.time()
                            while time.time() - redirect_start < 15:
                                cur_url = ext_page.url or ""
                                if (
                                    cur_url
                                    and not cur_url.startswith("about:")
                                    and "naukri.com/apply" not in cur_url
                                ):
                                    break
                                time.sleep(1.0)

                            try:
                                ext_page.wait_for_load_state("domcontentloaded", timeout=20000)
                            except Exception:
                                pass
                            time.sleep(2.5)
                            logger.info(f"External career page loaded at: {ext_page.url}")

                        from config_loader import get_resume_path
                        resolved_resume = get_resume_path(self.config)
                        cl_path = self.config.get("profile", {}).get("cover_letter_path", "cover_letter.pdf")
                        resolved_cl = Path(cl_path)
                        if not resolved_cl.is_absolute():
                            resolved_cl = Path(__file__).parent.parent.resolve() / resolved_cl

                        applied_ext = self.ats_handler.apply_external(
                            page=ext_page,
                            job_title=job_title,
                            company=company_name,
                            resume_path=resolved_resume,
                            cover_letter_path=resolved_cl if resolved_cl.exists() else None,
                        )

                        if applied_ext:
                            applied_on_page += 1
                            self.db.record_application(
                                job_id=job_id,
                                platform="naukri",
                                title=job_title,
                                company=company_name,
                                location=location,
                                job_url=ext_page.url if ext_page else href,
                                status="applied",
                                reason="Applied on external company site",
                            )
                            logger.success(
                                f"Successfully applied on company site to {job_title} at {company_name} "
                                f"[{today_count + total_applied_this_run + applied_on_page}/{self.max_daily} today]"
                            )
                            BrowserManager.human_delay(
                                self.config.get("execution", {}).get("human_delay_min", 3.0),
                                self.config.get("execution", {}).get("human_delay_max", 6.0),
                            )
                        else:
                            # Record as skipped so the bot NEVER re-opens this external posting
                            self.db.record_application(
                                job_id=job_id,
                                platform="naukri",
                                title=job_title,
                                company=company_name,
                                location=location,
                                job_url=ext_page.url if ext_page else href,
                                status="skipped",
                                reason="External application skipped by user or completed in browser",
                            )

                        if ext_page and ext_page != job_page:
                            try:
                                ext_page.close()
                            except Exception:
                                pass
                        continue

                    if "already applied" in btn_text:
                        self.db.record_application(
                            job_id=job_id,
                            platform="naukri",
                            title=job_title,
                            company=company_name,
                            location=location,
                            job_url=href,
                            status="applied",
                            reason="Already applied on Naukri",
                        )
                        continue

                    logger.step(f"Applying on Naukri: {job_title} at {company_name}")
                    apply_btn.first.click()
                    time.sleep(2.5)

                    if self._check_limit_toast(job_page):
                        logger.warning("Naukri daily application limit reached!")
                        self.limit_reached = True
                        self.db.mark_daily_limit_reached("naukri")
                        return applied_on_page, False

                    self._handle_naukri_chatbot_questions(job_page, job_title=job_title, company_name=company_name)

                    applied_on_page += 1
                    self.db.record_application(
                        job_id=job_id,
                        platform="naukri",
                        title=job_title,
                        company=company_name,
                        location=location,
                        job_url=href,
                        status="applied",
                    )
                    logger.success(
                        f"Successfully applied to {job_title} at {company_name} "
                        f"[{today_count + total_applied_this_run + applied_on_page}/{self.max_daily} today]"
                    )

                    BrowserManager.human_delay(
                        self.config.get("execution", {}).get("human_delay_min", 3.0),
                        self.config.get("execution", {}).get("human_delay_max", 6.0),
                    )

                finally:
                    job_page.close()

            except Exception as e:
                logger.warning(f"Error applying on Naukri job: {e}")
                continue

        return applied_on_page, True

    def run(
        self,
        keyword_override: Optional[str] = None,
        location_override: Optional[str] = None,
        time_filter_override: Optional[str] = None,
    ) -> int:
        """Executes Naukri direct apply loop across keywords, locations, deep pages, and time filter."""
        if not self.naukri_cfg.get("enabled", True):
            logger.info("Naukri automation is disabled in config.yaml.")
            return 0

        today_count = self.db.get_daily_applied_count("naukri")
        if self.limit_reached or today_count >= self.max_daily:
            logger.info(
                f"Naukri daily limit already reached ({today_count}/{self.max_daily} applications). Skipping for today."
            )
            return 0

        browser = BrowserManager("naukri", headless=self.headless)
        page = browser.start()
        total_applied_this_run = 0

        try:
            logger.step("Checking Naukri session authentication...")
            page.goto("https://www.naukri.com/mnjuser/homepage", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3.0)

            if "nlogin" in page.url or "login" in page.url:
                logger.error("Naukri session expired or not logged in! Please run 'python main.py login --platform naukri'.")
                return 0

            if isinstance(keyword_override, list):
                keywords = keyword_override
            elif isinstance(keyword_override, str):
                keywords = [k.strip() for k in keyword_override.split(",") if k.strip()]
            else:
                keywords = self.config.get("search", {}).get("keywords", ["DevOps Engineer"])

            # Full target roles from config.yaml to evaluate relevance across all configured career roles
            configured_keywords = self.config.get("search", {}).get("keywords", [])
            if isinstance(configured_keywords, str):
                configured_keywords = [configured_keywords]
            combined_targets = list(dict.fromkeys(keywords + configured_keywords))

            if isinstance(location_override, list):
                locations = location_override
            elif isinstance(location_override, str):
                locations = [l.strip() for l in location_override.split(",") if l.strip()]
            else:
                locations = self.config.get("search", {}).get("locations", ["India"])

            time_filter = time_filter_override or self.config.get("search", {}).get("date_posted", "30d")
            if isinstance(time_filter, list):
                order = ["30d", "15d", "7d", "24h"]
                time_filter = next((w for w in order if w in time_filter), time_filter[-1] if time_filter else "30d")

            max_pages = int(self.config.get("search", {}).get("max_pages_per_keyword", 3))

            for keyword in keywords:
                if self.limit_reached or (today_count + total_applied_this_run) >= self.max_daily:
                    break

                for location in locations:
                    if self.limit_reached or (today_count + total_applied_this_run) >= self.max_daily:
                        break

                    for page_no in range(1, max_pages + 1):
                        if self.limit_reached or (today_count + total_applied_this_run) >= self.max_daily:
                            break

                        page_num_str = f" (Page {page_no})" if page_no > 1 else ""
                        logger.step(f"Searching Naukri jobs{page_num_str} for '{keyword}' in '{location}' [Filter: {time_filter}]...")
                        search_url = self._build_search_url(keyword, location, time_filter=time_filter, page_no=page_no)
                        page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(3.0)

                        if self._check_limit_toast(page):
                            logger.warning("Naukri daily application limit reached!")
                            self.limit_reached = True
                            self.db.mark_daily_limit_reached("naukri")
                            break

                        applied_on_page, has_more = self._process_search_page(
                            page=page,
                            browser=browser,
                            time_filter=time_filter,
                            combined_targets=combined_targets,
                            location=location,
                            today_count=today_count,
                            total_applied_this_run=total_applied_this_run,
                        )
                        total_applied_this_run += applied_on_page

                        if not has_more:
                            logger.info(f"No further eligible Naukri jobs on Page {page_no}. Advancing.")
                            break

        except Exception as e:
            logger.error(f"Naukri automation error: {e}")
        finally:
            browser.close()

        return total_applied_this_run

    def update_resume(self) -> bool:
        """
        Uploads the latest resume PDF to Naukri profile to refresh the
        'Profile Last Updated' timestamp and boost recruiter search ranking.
        """
        from config_loader import get_resume_path
        resume_file = get_resume_path(self.config)
        if not resume_file:
            logger.warning("No resume PDF found to update on Naukri profile.")
            return False

        logger.step(f"Updating Naukri profile with latest resume: {resume_file.name}...")
        browser = BrowserManager("naukri", headless=self.headless)
        page = browser.start()

        try:
            page.goto("https://www.naukri.com/mnjuser/profile", wait_until="domcontentloaded", timeout=35000)
            time.sleep(3.0)

            if "nlogin" in page.url or "login" in page.url:
                logger.error("Naukri session expired! Please run 'python main.py login --platform naukri'.")
                return False

            BrowserManager.smooth_scroll(page, scrolls=2, distance=400)
            time.sleep(1.5)

            file_input = page.locator("input#attachCV, input[type='file'][id*='attach'], input[type='file']")
            if file_input.count() > 0:
                file_input.first.set_input_files(str(resume_file))
                logger.info("Uploading resume to Naukri...")
                time.sleep(5.0)
                logger.success("Naukri resume uploaded successfully! Profile updated timestamp refreshed to today.")
                return True
            else:
                edit_headline = page.locator("span.widgetTitle:has-text('Resume headline') ~ * .edit, .resumeHeadline .edit")
                if edit_headline.count() > 0 and edit_headline.first.is_visible():
                    edit_headline.first.click()
                    time.sleep(1.5)
                    save_btn = page.locator("button:has-text('Save')")
                    if save_btn.count() > 0 and save_btn.first.is_visible():
                        save_btn.first.click()
                        time.sleep(2.0)
                        logger.success("Naukri profile timestamp refreshed to today via headline update.")
                        return True

            logger.warning("Could not locate resume upload input on Naukri profile.")
            return False

        except Exception as e:
            logger.error(f"Error updating Naukri resume: {e}")
            return False
        finally:
            browser.close()

