"""
LinkedIn Easy Apply automation engine.
Supports persistent sessions, smart question answering, resume upload,
job listing search with time filters (24h, 7d, 15d, 30d), and daily quota detection.
"""

from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
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


class LinkedInPlatform(BasePlatform):
    def __init__(self, config: Dict[str, Any], db, headless: bool = False):
        super().__init__("linkedin", config, db, headless)
        self.linkedin_cfg = self.config.get("platforms", {}).get("linkedin", {})
        self.max_daily = self.linkedin_cfg.get("max_daily_applications", 50)
        self.exclude_skills = self.config.get("search", {}).get("exclude_skills", [])
        self.cv_skills = self.config.get("profile", {}).get("cv_skills", [])
        self.form_filler = FormFiller(self.config.get("profile", {}))
        self.ats_handler = ExternalATSHandler(self.config)

    def login(self):
        """Interactive visible login session so user can log in with 2FA/OTP once."""
        logger.info("Opening visible browser window for LinkedIn login...")
        browser = BrowserManager("linkedin", headless=False)
        page = browser.start()

        try:
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            logger.info("=======================================================")
            logger.info("ACTION REQUIRED: Log into LinkedIn in the opened browser.")
            logger.info("Complete 2FA/OTP if prompted. Ensure your feed is loaded.")
            logger.info("=======================================================")

            print("\n[Input] Press ENTER in this terminal once you have successfully logged in: ", end="", flush=True)
            input()

            page.wait_for_timeout(2000)
            if "feed" in page.url or page.locator(".global-nav").count() > 0:
                logger.success("LinkedIn session authenticated and saved successfully!")
            else:
                logger.warning("Session cookies saved, but could not detect active feed. Please verify login.")
        finally:
            browser.close()

    def check_auth(self) -> bool:
        """Verifies if the saved persistent profile is authenticated."""
        browser = BrowserManager("linkedin", headless=True)
        page = browser.start()
        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            if "login" in page.url or "authwall" in page.url or page.locator("a[href*='/login']").count() > 0:
                return False
            return page.locator(".global-nav, nav.global-nav").count() > 0 or "feed" in page.url
        except Exception:
            return False
        finally:
            browser.close()

    def _build_search_url(
        self, keyword: str, location: str, time_filter: Optional[str] = None, start: int = 0
    ) -> str:
        """
        Constructs LinkedIn Jobs search URL with time filters:
        - 24h / past_24h -> past 24 hours (86400s)
        - 7d / past_week -> past 7 days (604800s)
        - 15d / past_15d -> past 15 days (1296000s)
        - 30d / past_month -> past 30 days (2592000s)
        """
        base = "https://www.linkedin.com/jobs/search/?"
        loc = location.strip() if (location and location.strip()) else "India"
        params = [
            f"keywords={quote_plus(keyword)}",
            f"location={quote_plus(loc)}",
            "sortBy=DD",  # Date posted: most recent
        ]

        easy_apply_only = self.linkedin_cfg.get("easy_apply_only", True)
        ext_enabled = self.config.get("external_apply", {}).get("enabled", False)
        if easy_apply_only and not ext_enabled:
            params.append("f_AL=true")  # Restrict to Easy Apply only when external apply is disabled

        # Experience level filter (LinkedIn: 1=Internship, 2=Entry (0-2 yrs), 3=Associate (2-3 yrs), 4=Mid-Senior)
        from config_loader import parse_experience_range
        min_exp, max_exp = parse_experience_range(self.config.get("search", {}).get("experience_years", "0-3"))
        exp_levels = []
        if min_exp <= 1:
            exp_levels.extend(["1", "2"])
        if max_exp >= 2:
            exp_levels.append("3")
        if max_exp > 3:
            exp_levels.append("4")
        if exp_levels:
            params.append(f"f_E={','.join(sorted(set(exp_levels)))}")

        # Workplace / Work modes filter (LinkedIn: 1=On-site, 2=Remote, 3=Hybrid)
        # Automatically applies across all 3 modes: On-site, Remote, and Hybrid
        work_modes = self.config.get("search", {}).get("work_modes", ["on-site", "remote", "hybrid"])
        if isinstance(work_modes, str):
            work_modes = [w.strip() for w in work_modes.split(",") if w.strip()]

        wt_mapping = {
            "on-site": "1",
            "onsite": "1",
            "office": "1",
            "remote": "2",
            "wfh": "2",
            "hybrid": "3",
            "1": "1",
            "2": "2",
            "3": "3",
        }
        wt_codes = []
        for wm in (work_modes or ["on-site", "remote", "hybrid"]):
            code = wt_mapping.get(str(wm).lower().strip())
            if code and code not in wt_codes:
                wt_codes.append(code)

        if not wt_codes:
            wt_codes = ["1", "2", "3"]

        params.append(f"f_WT={','.join(sorted(wt_codes))}")

        t_filter = time_filter or self.config.get("search", {}).get("date_posted", "30d")
        if isinstance(t_filter, list):
            order = ["30d", "15d", "7d", "24h"]
            t_filter = next((w for w in order if w in t_filter), t_filter[-1] if t_filter else "30d")
        t_filter_clean = str(t_filter).lower().strip()

        if t_filter_clean in ("24h", "past_24h", "1d", "day"):
            params.append("f_TPR=r86400")
        elif t_filter_clean in ("7d", "past_7d", "past_week", "week"):
            params.append("f_TPR=r604800")
        elif t_filter_clean in ("15d", "past_15d", "15days"):
            params.append("f_TPR=r1296000")
        elif t_filter_clean in ("30d", "past_30d", "past_month", "month"):
            params.append("f_TPR=r2592000")

        if start > 0:
            params.append(f"start={start}")

        return base + "&".join(params)

    def _check_limit_modal(self, page: Page) -> bool:
        """Checks if LinkedIn daily Easy Apply limit modal or toast is present."""
        limit_patterns = [
            "limit for today",
            "reached the easy apply limit",
            "maximum number of applications",
            "exceeded the daily application limit",
        ]
        text_content = ""
        try:
            modals = page.locator(".artdeco-modal, .ip-fuse-limit-alert, [role='alertdialog']").all()
            for m in modals:
                if m.is_visible():
                    text_content += " " + m.inner_text().lower()
        except Exception:
            pass

        for pat in limit_patterns:
            if pat in text_content:
                return True
        return False

    def _ensure_workplace_types(self, page: Page):
        """
        Ensures that all 3 work modes (On-site, Remote, Hybrid) are active in LinkedIn UI.
        If LinkedIn's session retained a single-mode filter (e.g. 'Remote 1' as shown in screenshot),
        this automatically opens the filter dropdown, checks all 3 options, and applies them.
        """
        try:
            # Check for filter button that indicates a single mode is selected (e.g. 'Remote 1', 'Remote')
            filter_btn = page.locator(
                "button#searchFilter_workplaceType, "
                "button[aria-label*='Remote filter'], "
                "button[aria-label*='Workplace filter'], "
                "button:has-text('Remote 1'), "
                "button:has-text('On-site 1'), "
                "button:has-text('Hybrid 1')"
            ).first

            if filter_btn.count() > 0 and filter_btn.is_visible():
                btn_txt = filter_btn.inner_text().strip()
                # If only 1 mode is active (e.g. "Remote 1" or "Remote")
                if " 1" in btn_txt or btn_txt == "Remote":
                    logger.info(f"Workplace filter is currently '{btn_txt}'. Updating to all 3 modes (On-site, Remote, Hybrid)...")
                    filter_btn.click()
                    time.sleep(1.0)

                    # Ensure On-site, Remote, and Hybrid are all checked
                    for mode_text in ["On-site", "Remote", "Hybrid"]:
                        try:
                            lbl = page.locator(f"label:has-text('{mode_text}')").first
                            if lbl.count() > 0:
                                inp = lbl.locator("input[type='checkbox']").first
                                if inp.count() > 0 and not inp.is_checked():
                                    inp.check(force=True)
                                    time.sleep(0.3)
                                elif inp.count() == 0:
                                    lbl.click()
                                    time.sleep(0.3)
                        except Exception:
                            pass

                    # Click 'Show results'
                    show_btn = page.locator("button:has-text('Show results'), button[data-control-name='filter_show_results']").first
                    if show_btn.count() > 0 and show_btn.is_visible():
                        show_btn.click()
                        time.sleep(2.0)
                        logger.info("Successfully updated LinkedIn search to all 3 work modes (On-site, Remote, Hybrid).")
        except Exception:
            pass

    def _discard_application_modal(self, page: Page):
        """Safely dismisses and discards an uncompleted Easy Apply modal."""
        try:
            dismiss_btn = page.locator(
                "button[aria-label='Dismiss'], button[data-test-modal-close-btn], button.artdeco-modal__dismiss"
            )
            if dismiss_btn.count() > 0 and dismiss_btn.first.is_visible():
                dismiss_btn.first.click()
                time.sleep(1.0)
                confirm_discard = page.locator(
                    "button[data-control-name='discard_application_confirm_btn'], button:has-text('Discard')"
                )
                if confirm_discard.count() > 0 and confirm_discard.first.is_visible():
                    confirm_discard.first.click()
                    time.sleep(1.0)
        except Exception:
            pass

    def _fill_and_submit_easy_apply(self, page: Page, job_title: str, company: str) -> bool:
        """Handles multi-step Easy Apply dialog."""
        from config_loader import get_resume_path
        resolved_resume = get_resume_path(self.config)

        max_steps = 8
        current_step = 0

        modal = page.locator("div.jobs-easy-apply-modal, div[role='dialog'], .artdeco-modal")
        if modal.count() == 0 or not modal.first.is_visible():
            return False

        while current_step < max_steps:
            current_step += 1
            time.sleep(1.5)

            if self._check_limit_modal(page):
                logger.warning("LinkedIn daily Easy Apply limit reached!")
                self.limit_reached = True
                self.db.mark_daily_limit_reached("linkedin")
                self._discard_application_modal(page)
                return False

            # Resume handling: select existing matching resume card if available, or upload
            if resolved_resume and resolved_resume.exists():
                resume_name = resolved_resume.name
                resume_card = modal.locator(f"div:has-text('{resume_name}'), label:has-text('{resume_name}')")
                if resume_card.count() > 0:
                    try:
                        resume_card.first.click()
                        time.sleep(0.5)
                    except Exception:
                        pass

            # Check for Cover Letter & Resume file upload inputs
            cl_path = self.config.get("profile", {}).get("cover_letter_path", "Ansh_Mishra_Cover_Letter.pdf")
            resolved_cl = Path(cl_path)
            if not resolved_cl.is_absolute():
                resolved_cl = Path(__file__).parent.parent.resolve() / resolved_cl

            file_inputs = modal.locator("input[type='file']").all()
            for fi in file_inputs:
                try:
                    ancestor = fi.locator(
                        "xpath=ancestor::div[contains(@class, 'jobs-document-upload') or contains(@class, 'form') or contains(@class, 'artdeco-modal')]"
                    ).first
                    ancestor_text = ancestor.inner_text().lower() if ancestor.count() > 0 else ""
                    if "cover" in ancestor_text and resolved_cl.exists():
                        fi.set_input_files(str(resolved_cl))
                        time.sleep(1.5)
                    elif resolved_resume and resolved_resume.exists():
                        fi.set_input_files(str(resolved_resume))
                        time.sleep(1.5)
                except Exception:
                    pass

            # Fill inputs on current step (passing job title & company for tailored cover letters)
            self.form_filler.fill_all_inputs_on_page(modal, job_title=job_title, company=company)
            time.sleep(1.0)

            # Check for Submit Application button
            submit_btn = modal.locator("button[aria-label='Submit application'], button:has-text('Submit application')")
            if submit_btn.count() > 0 and submit_btn.first.is_visible():
                follow_checkbox = modal.locator("input#follow-company-checkbox")
                if follow_checkbox.count() > 0 and follow_checkbox.first.is_checked():
                    try:
                        follow_checkbox.first.uncheck(force=True)
                    except Exception:
                        pass

                logger.info(f"Submitting application for: {job_title} at {company}")
                submit_btn.first.click()
                time.sleep(3.0)

                done_btn = page.locator(
                    "button:has-text('Done'), button[aria-label='Dismiss'], button[data-test-modal-close-btn], button.artdeco-modal__dismiss"
                )
                if done_btn.count() > 0 and done_btn.first.is_visible():
                    done_btn.first.click()
                    time.sleep(1.0)
                return True

            # Check for Review button
            review_btn = modal.locator("button[aria-label='Review your application'], button:has-text('Review')")
            if review_btn.count() > 0 and review_btn.first.is_visible():
                review_btn.first.click()
                time.sleep(1.5)
                continue

            # Check for Next button
            next_btn = modal.locator("button[aria-label='Continue to next step'], button:has-text('Next')")
            if next_btn.count() > 0 and next_btn.first.is_visible():
                next_btn.first.click()
                time.sleep(1.5)
                # If error feedback appears, run self-healing and retry Next once
                err_loc = modal.locator(".artdeco-inline-feedback--error, [data-test-form-element-error-messages]")
                if err_loc.count() > 0 and err_loc.first.is_visible():
                    self.form_filler.fill_all_inputs_on_page(modal, job_title=job_title, company=company)
                    time.sleep(1.0)
                    if next_btn.count() > 0 and next_btn.first.is_visible():
                        next_btn.first.click()
                        time.sleep(1.5)
                continue

            break

        logger.warning(f"Could not automatically complete all questions for: {job_title}. Skipping.")
        self._discard_application_modal(page)
        return False

    def list_jobs(
        self,
        keyword: str,
        location: str,
        time_filter: str = "24h",
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Searches and returns job listings matching position, location, and time window."""
        browser = BrowserManager("linkedin", headless=self.headless)
        page = browser.start()
        jobs: List[Dict[str, Any]] = []

        try:
            logger.info(f"Searching LinkedIn jobs for '{keyword}' in '{location}' [Filter: {time_filter}]...")
            search_url = self._build_search_url(keyword, location, time_filter=time_filter)
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3.0)
            self._ensure_workplace_types(page)

            BrowserManager.smooth_scroll(page, scrolls=3, distance=500)
            cards = page.locator("li[data-occludable-job-id], div.job-card-container").all()

            for card in cards[:limit]:
                try:
                    job_id = card.get_attribute("data-occludable-job-id") or ""
                    link = card.locator("a[href*='/jobs/view/']").first
                    href = ""
                    if link.count() > 0:
                        href = link.get_attribute("href") or ""
                        if not job_id:
                            m = re.search(r"/jobs/view/(\d+)", href)
                            if m:
                                job_id = m.group(1)

                    if not job_id:
                        continue

                    title_elem = card.locator(
                        "a.job-card-list__title--link, a.job-card-container__link, .artdeco-entity-lockup__title a, .job-card-list__title, strong"
                    ).first
                    company_elem = card.locator(
                        ".artdeco-entity-lockup__subtitle, .job-card-container__primary-description, .job-card-container__company-name"
                    ).first
                    time_elem = card.locator("time, .job-card-container__listed-time, .job-card-container__footer-item").first
                    loc_elem = card.locator(".artdeco-entity-lockup__caption li, .job-card-container__metadata-item").first

                    title = title_elem.inner_text().strip() if title_elem.count() > 0 else "Unknown Title"
                    if not is_title_relevant(title, [keyword]):
                        continue

                    # Reject blacklisted skills (e.g. SAP)
                    if has_blacklisted_skills([title], self.exclude_skills):
                        continue

                    card_raw_text = card.inner_text().lower()
                    if has_blacklisted_skills([card_raw_text], self.exclude_skills):
                        continue

                    # Reject jobs requiring experience > 3 years (or senior/director titles)
                    if not is_experience_eligible(title, max_allowed_min_exp=3.0):
                        continue
                    if not is_experience_eligible(card_raw_text, max_allowed_min_exp=3.0):
                        continue

                    company = company_elem.inner_text().strip() if company_elem.count() > 0 else "Unknown Company"
                    posted_time = time_elem.inner_text().strip() if time_elem.count() > 0 else ""
                    if not posted_time or posted_time.lower() in ("recently", ""):
                        posted_time = extract_posted_time_from_text(card_raw_text) or posted_time or "Recently"

                    if posted_time and not is_posted_within_window(posted_time, time_filter):
                        continue

                    job_loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else location

                    is_easy_apply = (
                        card.locator(".artdeco-button__icon--in-bug, svg[data-test-icon*='linkedin-bug'], .job-card-container__apply-method, :has-text('Apply')").count() > 0
                        or "f_AL=true" in search_url
                    )
                    applied = self.db.is_job_applied(job_id, "linkedin")
                    skill_match_count, matched_skills = calculate_cv_skills_match([title, card_raw_text], self.cv_skills)

                    jobs.append({
                        "id": job_id,
                        "title": title,
                        "company": company,
                        "location": job_loc,
                        "platform": "LinkedIn",
                        "posted_time": posted_time,
                        "apply_type": "Easy Apply" if is_easy_apply else "Standard",
                        "already_applied": applied,
                        "url": href if href.startswith("http") else f"https://www.linkedin.com/jobs/view/{job_id}/",
                        "skill_match_count": skill_match_count,
                        "matched_skills": matched_skills,
                    })
                except Exception:
                    continue

        except Exception as e:
            logger.error(f"Error fetching LinkedIn job listings: {e}")
        finally:
            browser.close()

        return jobs

    def run(
        self,
        keyword_override: Optional[str] = None,
        location_override: Optional[str] = None,
        time_filter_override: Optional[str] = None,
    ) -> int:
        """Executes LinkedIn Easy Apply loop across keywords, locations, and time filter."""
        if not self.linkedin_cfg.get("enabled", True):
            logger.info("LinkedIn automation is disabled in config.yaml.")
            return 0

        today_count = self.db.get_daily_applied_count("linkedin")
        if self.limit_reached or today_count >= self.max_daily:
            logger.info(
                f"LinkedIn daily limit already reached ({today_count}/{self.max_daily} applications). Skipping for today."
            )
            return 0

        browser = BrowserManager("linkedin", headless=self.headless)
        page = browser.start()
        total_applied_this_run = 0

        try:
            logger.step("Checking LinkedIn session authentication...")
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3.0)

            if "login" in page.url or "authwall" in page.url:
                logger.error("LinkedIn session expired or not logged in! Please run 'python main.py login --platform linkedin'.")
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

            for keyword in keywords:
                if self.limit_reached or (today_count + total_applied_this_run) >= self.max_daily:
                    break

                for location in locations:
                    if self.limit_reached or (today_count + total_applied_this_run) >= self.max_daily:
                        break

                    logger.step(f"Searching LinkedIn jobs for '{keyword}' in '{location}' [Filter: {time_filter}]...")
                    search_url = self._build_search_url(keyword, location, time_filter=time_filter)
                    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(3.0)
                    self._ensure_workplace_types(page)

                    if self._check_limit_modal(page):
                        logger.warning("LinkedIn daily Easy Apply limit reached!")
                        self.limit_reached = True
                        self.db.mark_daily_limit_reached("linkedin")
                        break

                    BrowserManager.smooth_scroll(page, scrolls=3, distance=500)

                    # Extract job card metadata upfront to avoid stale Playwright locators & virtual DOM timeouts
                    job_cards_data = []
                    seen_jids = set()
                    raw_cards = page.locator("li[data-occludable-job-id]").all()
                    for c in raw_cards:
                        try:
                            jid = c.get_attribute("data-occludable-job-id", timeout=1000)
                            if not jid or jid in seen_jids:
                                continue

                            # Check title relevance
                            title_elem = c.locator("a.job-card-list__title, a.job-card-container__link, a[href*='/jobs/view/'], strong").first
                            card_title = title_elem.inner_text(timeout=1000).strip() if title_elem.count() > 0 else ""
                            if card_title and not is_title_relevant(card_title, combined_targets):
                                logger.info(f"Skipping irrelevant role on LinkedIn: '{card_title}' (does not match target roles: {combined_targets})")
                                continue

                            # Reject blacklisted skills (e.g. SAP)
                            if card_title and has_blacklisted_skills([card_title], self.exclude_skills):
                                logger.info(f"Skipping role with blacklisted skill (SAP) on LinkedIn: '{card_title}'")
                                continue

                            # Check experience eligibility (e.g. Director, Principal, Senior 5+)
                            if card_title and not is_experience_eligible(card_title, max_allowed_min_exp=3.0):
                                logger.info(f"Skipping senior/ineligible role on LinkedIn: '{card_title}'")
                                continue

                            # Check freshness
                            time_elem = c.locator("time, .job-card-container__listed-time, .job-card-container__footer-item").first
                            card_txt = c.inner_text(timeout=1000).lower()
                            card_time = time_elem.inner_text(timeout=1000).strip() if time_elem.count() > 0 else ""
                            if not card_time or card_time.lower() in ("recently", ""):
                                card_time = extract_posted_time_from_text(card_txt) or card_time or "Recently"

                            if card_time and not is_posted_within_window(card_time, time_filter):
                                logger.info(f"Skipping older job on LinkedIn: '{card_title}' posted '{card_time}' (exceeds {time_filter} window)")
                                continue
                            if has_blacklisted_skills([card_txt], self.exclude_skills):
                                logger.info(f"Skipping job card mentioning blacklisted skill (SAP): '{card_title}'")
                                continue

                            if not is_experience_eligible(card_txt, max_allowed_min_exp=3.0):
                                logger.info(f"Skipping job requiring >3 years experience on LinkedIn: '{card_title}'")
                                continue

                            seen_jids.add(jid)
                            is_top = ("top applicant" in card_txt) or ("early applicant" in card_txt)
                            skill_match_count, matched_skills = calculate_cv_skills_match([card_title, card_txt], self.cv_skills)

                            job_cards_data.append({
                                "id": jid,
                                "title": card_title,
                                "posted_time": card_time,
                                "is_top": is_top,
                                "skill_match_count": skill_match_count,
                                "matched_skills": matched_skills,
                            })
                        except Exception:
                            continue

                    # Sort jobs so Top Applicants and high CV skill matches are applied to first
                    ordered_jobs = sorted(
                        job_cards_data,
                        key=lambda j: (1 if j["is_top"] else 0, j["skill_match_count"]),
                        reverse=True,
                    )
                    top_jobs = [j for j in ordered_jobs if j["is_top"]]
                    high_match_jobs = [j for j in ordered_jobs if j["skill_match_count"] >= 2]
                    logger.info(
                        f"Discovered {len(ordered_jobs)} eligible LinkedIn jobs on page "
                        f"({len(top_jobs)} Top/Early Applicant, {len(high_match_jobs)} high CV skills match)."
                    )

                    if top_jobs:
                        logger.info(f"⭐ Prioritizing {len(top_jobs)} 'Top Applicant' jobs first!")
                    elif high_match_jobs:
                        logger.info(f"⭐ Prioritizing {len(high_match_jobs)} high CV skill match jobs first!")

                    for job_info in ordered_jobs:
                        if self.limit_reached or (today_count + total_applied_this_run) >= self.max_daily:
                            logger.info(f"Reached daily application limit target ({self.max_daily}). Stopping.")
                            break

                        job_id = job_info["id"]
                        if self.db.is_job_applied(job_id, "linkedin"):
                            continue

                        try:
                            # Safely find and click the card element by its unique job ID with short timeout
                            card_loc = page.locator(f"li[data-occludable-job-id='{job_id}']").first
                            opened = False
                            if card_loc.count() > 0:
                                try:
                                    card_loc.scroll_into_view_if_needed(timeout=2000)
                                    clickable = card_loc.locator(
                                        "a.job-card-list__title, a.job-card-container__link, a[href*='/jobs/view/']"
                                    ).first
                                    if clickable.count() > 0 and clickable.is_visible():
                                        clickable.click(timeout=2000)
                                        opened = True
                                    else:
                                        card_loc.click(timeout=2000)
                                        opened = True
                                except Exception:
                                    opened = False

                            if not opened:
                                # Direct navigation fallback if card was scrolled off the virtual DOM
                                page.goto(f"https://www.linkedin.com/jobs/view/{job_id}/", wait_until="domcontentloaded", timeout=15000)

                            time.sleep(2.0)

                            # Extract job title & company from top card
                            title_loc = page.locator(".job-details-jobs-unified-top-card__job-title, h1.t-24, h1")
                            company_loc = page.locator(
                                ".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name, div[data-view-name='job-details-top-card'] a[href*='/company/']"
                            )
                            
                            job_title = title_loc.first.inner_text().strip() if title_loc.count() > 0 else "Unknown Title"
                            company_name = company_loc.first.inner_text().strip() if company_loc.count() > 0 else "Unknown Company"

                            # Deduplication check across company & title to prevent revisiting the same external portal/posting
                            if self.db.is_url_or_company_applied(company=company_name, title=job_title):
                                logger.info(f"Skipping already processed application on LinkedIn: '{job_title}' at '{company_name}'")
                                continue

                            if not is_title_relevant(job_title, combined_targets):
                                logger.info(f"Skipping irrelevant role on LinkedIn: '{job_title}' (does not match target roles: {combined_targets})")
                                continue

                            if has_blacklisted_skills([job_title], self.exclude_skills):
                                logger.info(f"Skipping role with blacklisted skill (SAP) on LinkedIn: '{job_title}'")
                                continue

                            if not is_experience_eligible(job_title, max_allowed_min_exp=3.0):
                                logger.info(f"Skipping senior/ineligible role on LinkedIn: '{job_title}'")
                                continue

                            # Inspect job description text for blacklisted skills or experience
                            desc_elem = page.locator("div.jobs-description__content, div.jobs-box__html-content, #job-details, article.jobs-description__container").first
                            if desc_elem.count() > 0:
                                desc_text = desc_elem.inner_text(timeout=2000).lower()
                                if has_blacklisted_skills([desc_text], self.exclude_skills):
                                    logger.info(f"Skipping '{job_title}' at '{company_name}' - description mentions blacklisted skill (SAP)")
                                    continue
                                if not is_experience_eligible(desc_text[:1000], max_allowed_min_exp=3.0):
                                    logger.info(f"Skipping '{job_title}' at '{company_name}' - experience required exceeds candidate limit (0-3 yrs)")
                                    continue

                            matched_skills = job_info.get("matched_skills", [])
                            skills_str = f" [Skills: {', '.join(matched_skills[:3])}]" if matched_skills else ""
                            logger.step(f"Processing LinkedIn job: '{job_title}' at '{company_name}'{skills_str}")

                            # Find Easy Apply / LinkedIn Apply button in detail pane (scoped with .first to avoid strict mode violations)
                            detail_pane = page.locator(
                                "div.jobs-details__main-content, div[data-view-name='job-details-top-card'], .jobs-unified-top-card, .job-view-layout"
                            ).first

                            # Re-verify freshness in detail pane before applying
                            try:
                                pane_text = detail_pane.inner_text(timeout=2000)
                                pane_posted_time = extract_posted_time_from_text(pane_text)
                                if pane_posted_time and not is_posted_within_window(pane_posted_time, time_filter):
                                    logger.info(f"Skipping older job on LinkedIn detail pane: '{job_title}' posted '{pane_posted_time}' (exceeds {time_filter} window)")
                                    continue
                            except Exception:
                                pass

                            apply_btn = detail_pane.locator(
                                "button.jobs-apply-button, a.jobs-apply-button, "
                                "button[data-live-test-job-apply-button], a[data-live-test-job-apply-button], "
                                "button[aria-label*='Apply'], a[aria-label*='Apply'], "
                                "button:has-text('Apply'), a:has-text('Apply')"
                            ).first
                            if apply_btn.count() == 0 or not apply_btn.is_visible():
                                apply_btn = page.locator(
                                    "button.jobs-apply-button, a.jobs-apply-button, "
                                    "button[data-live-test-job-apply-button], a[data-live-test-job-apply-button], "
                                    "button[aria-label*='Apply'], a[aria-label*='Apply'], "
                                    "button:has-text('Apply'), a:has-text('Apply')"
                                ).first

                            if apply_btn.count() == 0 or not apply_btn.is_visible():
                                continue

                            aria_label = (apply_btn.get_attribute("aria-label") or "").lower()
                            btn_text = apply_btn.inner_text().strip().lower()
                            has_in_bug = apply_btn.locator(".artdeco-button__icon--in-bug, svg[data-test-icon*='linkedin-bug']").count() > 0

                            is_easy_apply = (
                                "easy apply" in aria_label
                                or "linkedin apply" in aria_label
                                or "easy apply" in btn_text
                                or has_in_bug
                            )

                            if not is_easy_apply:
                                is_external = (
                                    "company website" in aria_label
                                    or "external" in aria_label
                                    or apply_btn.locator("svg[data-test-icon*='external']").count() > 0
                                    or "apply" in btn_text
                                )

                                if is_external:
                                    ext_enabled = self.config.get("external_apply", {}).get("enabled", False)
                                    if not ext_enabled:
                                        logger.info(f"Skipping external application: {job_title} at {company_name}")
                                        continue

                                    logger.step(f"Opening external application on company site for: '{job_title}' at '{company_name}'")
                                    ext_page = None
                                    initial_page_count = len(page.context.pages)

                                    try:
                                        with page.context.expect_page(timeout=5000) as new_page_info:
                                            apply_btn.click()
                                        ext_page = new_page_info.value
                                    except Exception:
                                        pass

                                    # Check if intermediate redirect confirmation modal appeared on LinkedIn
                                    time.sleep(1.5)
                                    try:
                                        modal = page.locator("div[role='dialog'], .artdeco-modal, .jobs-apply-button--modal")
                                        if modal.count() > 0 and modal.first.is_visible():
                                            logger.info("Handling LinkedIn intermediate external apply redirect modal...")
                                            cont_btn = modal.locator(
                                                "button:has-text('Continue'), a:has-text('Continue'), "
                                                "button:has-text('Apply on company'), a:has-text('Apply on company'), "
                                                "button:has-text('Apply'), a:has-text('Apply'), "
                                                "button:has-text('Proceed'), a:has-text('Proceed'), "
                                                "button.artdeco-button--primary, a.artdeco-button--primary"
                                            ).first
                                            if cont_btn.count() > 0 and cont_btn.is_visible():
                                                if ext_page is None:
                                                    try:
                                                        with page.context.expect_page(timeout=8000) as new_page_info2:
                                                            cont_btn.click()
                                                        ext_page = new_page_info2.value
                                                    except Exception:
                                                        cont_btn.click()
                                                else:
                                                    cont_btn.click()
                                    except Exception:
                                        pass

                                    # Fallback check for newly opened tab if expect_page timed out
                                    if ext_page is None:
                                        time.sleep(2.0)
                                        if len(page.context.pages) > initial_page_count:
                                            ext_page = page.context.pages[-1]

                                    if ext_page:
                                        # Wait for redirection to leave linkedin.com/jobs/view/externalApply and settle
                                        logger.info(f"Waiting for external redirect to settle (current: {ext_page.url})...")
                                        redirect_start = time.time()
                                        while time.time() - redirect_start < 15:
                                            cur_url = ext_page.url or ""
                                            if (
                                                cur_url
                                                and not cur_url.startswith("about:")
                                                and "linkedin.com/jobs/view/externalApply" not in cur_url
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
                                        cl_path = self.config.get("profile", {}).get("cover_letter_path", "Ansh_Mishra_Cover_Letter.pdf")
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
                                            total_applied_this_run += 1
                                            self.db.record_application(
                                                job_id=job_id,
                                                platform="linkedin",
                                                title=job_title,
                                                company=company_name,
                                                location=location,
                                                job_url=ext_page.url or f"https://www.linkedin.com/jobs/view/{job_id}/",
                                                status="applied",
                                                reason="Applied on external company site",
                                            )
                                            logger.success(
                                                f"Successfully applied on company site to {job_title} at {company_name} "
                                                f"[{today_count + total_applied_this_run}/{self.max_daily} today]"
                                            )
                                            BrowserManager.human_delay(
                                                self.config.get("execution", {}).get("human_delay_min", 3.0),
                                                self.config.get("execution", {}).get("human_delay_max", 6.0),
                                            )
                                        else:
                                            # Record as skipped so the bot NEVER re-opens or re-visits this external posting
                                            self.db.record_application(
                                                job_id=job_id,
                                                platform="linkedin",
                                                title=job_title,
                                                company=company_name,
                                                location=location,
                                                job_url=ext_page.url or f"https://www.linkedin.com/jobs/view/{job_id}/",
                                                status="skipped",
                                                reason="External application skipped by user or completed in browser",
                                            )

                                        try:
                                            ext_page.close()
                                        except Exception:
                                            pass

                                        # Dismiss any LinkedIn post-external-apply dialog
                                        try:
                                            post_modal = page.locator("div[role='dialog'], .artdeco-modal")
                                            if post_modal.count() > 0 and post_modal.first.is_visible():
                                                dismiss = post_modal.locator("button[aria-label='Dismiss'], button:has-text('Yes'), button:has-text('Done')").first
                                                if dismiss.count() > 0:
                                                    dismiss.click()
                                        except Exception:
                                            pass

                                continue

                            logger.step(f"Found Easy Apply: {job_title} at {company_name}")
                            apply_btn.click()
                            time.sleep(2.0)

                            success = self._fill_and_submit_easy_apply(page, job_title, company_name)
                            if success:
                                total_applied_this_run += 1
                                self.db.record_application(
                                    job_id=job_id,
                                    platform="linkedin",
                                    title=job_title,
                                    company=company_name,
                                    location=location,
                                    job_url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                                    status="applied",
                                )
                                logger.success(
                                    f"Successfully applied to {job_title} at {company_name} "
                                    f"[{today_count + total_applied_this_run}/{self.max_daily} today]"
                                )
                            else:
                                self.db.record_application(
                                    job_id=job_id,
                                    platform="linkedin",
                                    title=job_title,
                                    company=company_name,
                                    location=location,
                                    job_url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                                    status="skipped",
                                    reason="Incomplete form or limit reached",
                                )

                            BrowserManager.human_delay(
                                self.config.get("execution", {}).get("human_delay_min", 3.0),
                                self.config.get("execution", {}).get("human_delay_max", 6.0),
                            )

                        except Exception as e:
                            logger.warning(f"Error processing job card: {e}")
                            self._discard_application_modal(page)
                            continue

        except Exception as e:
            logger.error(f"LinkedIn automation error: {e}")
        finally:
            browser.close()

        return total_applied_this_run

    def update_resume(self) -> bool:
        """
        Uploads the latest resume to LinkedIn Job Application settings
        (https://www.linkedin.com/jobs/application-settings/) so that Easy Apply
        always uses the freshest version.
        """
        from config_loader import get_resume_path
        resume_file = get_resume_path(self.config)
        if not resume_file:
            logger.warning("No resume PDF found to update on LinkedIn.")
            return False

        logger.step(f"Updating LinkedIn default resume with: {resume_file.name}...")
        browser = BrowserManager("linkedin", headless=self.headless)
        page = browser.start()

        try:
            page.goto("https://www.linkedin.com/jobs/application-settings/", wait_until="domcontentloaded", timeout=35000)
            time.sleep(3.0)

            if "login" in page.url or "authwall" in page.url:
                logger.error("LinkedIn session expired! Please run 'python main.py login --platform linkedin'.")
                return False

            file_input = page.locator("input[type='file']")
            if file_input.count() > 0:
                file_input.first.set_input_files(str(resume_file))
                logger.info("Uploading resume to LinkedIn...")
                time.sleep(4.0)
                logger.success("LinkedIn resume updated successfully!")
                return True
            else:
                logger.info("LinkedIn default resume is active. Easy Apply will attach the latest resume dynamically.")
                return True

        except Exception as e:
            logger.warning(f"Note on LinkedIn resume update: {e}")
            return False
        finally:
            browser.close()

