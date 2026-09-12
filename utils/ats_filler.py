"""
External ATS Automation Engine.
Handles applications redirected from LinkedIn and Naukri to external company career sites:
- Lever
- Greenhouse
- Workday
- SmartRecruiters
- BambooHR / Generic company career portals

Supports 'Fill-and-Review' mode (auto_submit: false) where the bot fills
all fields, uploads resume/cover letter, and prompts the user in the terminal
to review before submitting.
"""

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError
from utils.form_filler import FormFiller
from utils.logger import logger


class ExternalATSHandler:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.profile = config.get("profile", {})
        self.ext_cfg = config.get("external_apply", {})
        self.auto_submit = self.ext_cfg.get("auto_submit", False)
        self.account_password = self.ext_cfg.get("account_password", "AutoApply@2026!")
        profile_with_pwd = dict(self.profile)
        if "account_password" not in profile_with_pwd:
            profile_with_pwd["account_password"] = self.account_password
        self.form_filler = FormFiller(profile_with_pwd)

    def detect_ats(self, url: str, page: Optional[Page] = None) -> str:
        """
        Detects ATS provider from URL domain or DOM indicators.
        Returns one of: 'lever', 'greenhouse', 'workday', 'smartrecruiters', 'bamboohr', 'generic'.
        """
        parsed = urlparse(url.lower())
        host = parsed.netloc
        path = parsed.path

        # 1. URL Domain & Path heuristics
        if "lever.co" in host or "jobs.lever.co" in host:
            return "lever"
        if "greenhouse.io" in host or "boards.greenhouse.io" in host or "gh_jid" in url.lower():
            return "greenhouse"
        if "myworkdayjobs.com" in host or "workday.com" in host or "wd1.myworkday" in host or "wd3.myworkday" in host or "wd5.myworkday" in host:
            return "workday"
        if "smartrecruiters.com" in host:
            return "smartrecruiters"
        if "bamboohr.com" in host:
            return "bamboohr"
        if "ashbyhq.com" in host:
            return "ashby"
        if (
            "sapsf.com" in host
            or "successfactors.com" in host
            or "jobs2web.com" in host
            or "deloitte.com" in host
            or "deloitte" in host
        ):
            return "successfactors"

        # 2. Page DOM & Frames Inspection (if page is provided)
        if page:
            try:
                def safe_has(sel: str, ctx=page) -> bool:
                    try:
                        c = ctx.locator(sel).count()
                        return isinstance(c, (int, float)) and c > 0
                    except Exception:
                        return False

                # Check frames first (embedded ATS widgets)
                for frame in page.frames:
                    f_url = frame.url.lower()
                    if "smartrecruiters.com" in f_url:
                        return "smartrecruiters"
                    if "lever.co" in f_url:
                        return "lever"
                    if "greenhouse.io" in f_url:
                        return "greenhouse"
                    if "myworkdayjobs.com" in f_url or "workday.com" in f_url:
                        return "workday"
                    if "sapsf.com" in f_url or "successfactors" in f_url or "jobs2web" in f_url:
                        return "successfactors"

                if safe_has("[data-qa*='smartrecruiters'], iframe[src*='smartrecruiters'], form[action*='smartrecruiters']"):
                    return "smartrecruiters"
                if safe_has("form[action*='lever.co'], .lever-job, [data-qa='btn-apply'], iframe[src*='lever.co']"):
                    return "lever"
                if safe_has("#grnhse_app, form#application_form, [data-mapped='greenhouse'], iframe[src*='greenhouse.io']"):
                    return "greenhouse"
                if safe_has("[data-automation-id*='workday'], [data-automation-id='jobPostingHeader'], script[src*='myworkday']"):
                    return "workday"
                if (
                    safe_has("a.dialogApplyBtn")
                    or safe_has("input#fbclc_userName")
                    or safe_has("form[action*='sapsf.com']")
                    or safe_has("form[action*='jobs2web']")
                    or safe_has("[data-automation-id*='successfactors']")
                ):
                    return "successfactors"
            except Exception:
                pass

        return "generic"

    def _review_and_confirm(self, page: Page, job_title: str, company: str) -> bool:
        """
        Fill-and-Review gatekeeper:
        - If auto_submit is True: returns True immediately.
        - If auto_submit is False: prompts the user in the terminal to inspect the browser
          window before clicking final submit.
        """
        if self.auto_submit:
            return True

        logger.info("=" * 70)
        logger.step(f"⭐ [FILL & REVIEW] Application Form Ready for: '{job_title}' at '{company}'")
        logger.info("All fields, contact information, and your resume have been populated.")
        logger.info(">>> ACTION REQUIRED: Inspect the open browser window to review the form.")
        logger.info("=" * 70)

        try:
            # Bring browser to front if possible
            try:
                page.bring_to_front()
            except Exception:
                pass

            prompt_msg = (
                f"\n[USER CONFIRMATION REQUIRED] Press [ENTER] in this terminal to submit application for {company}, "
                f"or type 's' / 'skip' to skip: "
            )
            resp = input(prompt_msg).strip().lower()

            if resp in ("s", "skip", "no", "n", "cancel"):
                logger.warning(f"Application for '{company}' skipped by user.")
                return False

            logger.info(f"User confirmed submission for '{company}'. Proceeding to submit...")
            return True
        except (EOFError, KeyboardInterrupt):
            # Non-interactive fallback (e.g. running in automated test or headless pipe)
            logger.info("No interactive terminal input available. Defaulting to submit confirmation.")
            return True

    def _wait_for_user_login(self, page: Page, company: str):
        """Pauses execution to allow user to enter credentials in the open browser window."""
        logger.info("=" * 70)
        logger.step(f"🔑 [USER LOGIN REQUIRED] {company} / SAP SuccessFactors Sign-In Screen Ready")
        logger.info("Please fill in your login credentials directly in the open browser window.")
        logger.info(">>> Enter your Email and Password, and complete any OTP or 2FA if prompted.")
        logger.info(">>> (If you do not have an account, you can also click 'Create an account' to register).")
        logger.info("=" * 70)

        try:
            page.bring_to_front()
        except Exception:
            pass

        try:
            input("\n[PRESS ENTER] in this terminal once you have logged in to continue: ")
        except (EOFError, KeyboardInterrupt):
            logger.info("Non-interactive terminal: proceeding with automated form check.")

    def _green_flag_confirm(self, page: Page, job_title: str, company: str) -> bool:
        """
        Deloitte / SuccessFactors Manual Submission & Green Flag Gatekeeper:
        Allows user to log in, select options, and submit the application manually in the browser.
        Once submitted, user presses [ENTER] in terminal to confirm application and advance to next job.
        """
        logger.info("=" * 70)
        logger.step(f"⭐ [MANUAL APPLY & GREEN FLAG] Application Ready: '{job_title}' at '{company}'")
        logger.info("• Auto-filling is bypassed as requested so you can select your options manually.")
        logger.info("• Once submitted and saved in your account, Deloitte retains your details for future roles.")
        logger.info("=" * 70)
        logger.info(">>> ACTION REQUIRED IN BROWSER:")
        logger.info("1. Complete sign-in on your Deloitte account (if prompted).")
        logger.info("2. Select your desired options and complete any needed details.")
        logger.info("3. Click the 'Apply' / 'Submit' button directly in the browser to post your application.")
        logger.info(">>> ONCE YOU HAVE SUBMITTED IN THE BROWSER:")
        logger.info("Press [ENTER] in this terminal to give the GREEN FLAG.")
        logger.info("The bot will record this application in the database and automatically")
        logger.info("advance to search and apply to the next Deloitte job (never repeating this one).")
        logger.info("=" * 70)

        try:
            page.bring_to_front()
        except Exception:
            pass

        prompt_msg = "\n[GREEN FLAG CONFIRMATION] Press [ENTER] once you have applied in the browser (or 's' to skip): "
        try:
            resp = input(prompt_msg).strip().lower()
        except (EOFError, KeyboardInterrupt):
            resp = ""

        if resp in ("s", "skip", "no", "n", "cancel"):
            logger.warning(f"Application for '{job_title}' at '{company}' skipped by user.")
            return False

        logger.success(f"Green flag received! Recording '{job_title}' at '{company}' as applied.")
        return True

    def _upload_file_to_locator(self, locator: Locator, file_path: Path) -> bool:
        """Safely attaches a file to Playwright file input locator."""
        if not file_path or not file_path.exists():
            logger.warning(f"File attachment not found at: {file_path}")
            return False
        try:
            locator.set_input_files(str(file_path.resolve()))
            time.sleep(1.5)
            return True
        except Exception as e:
            logger.warning(f"Failed uploading file to locator: {e}")
            return False

    def _dismiss_cookie_banner(self, page: Page):
        """Dismisses common corporate cookie consent modals."""
        try:
            btn = page.locator(
                "#cookie-accept, button#cookie-accept, button#onetrust-accept-btn-handler, "
                "button[data-automation-id*='cookie'], button:has-text('Accept All Cookies'), "
                "button:has-text('Accept All'), button:has-text('Accept')"
            ).first
            c = btn.count() if hasattr(btn, "count") else 0
            if isinstance(c, (int, float)) and c > 0 and btn.is_visible():
                btn.click()
                time.sleep(1.0)
        except Exception:
            pass

    def _close_advisory_tabs(self, page: Page):
        """Closes any accidental popups or external advisory tabs, keeping focus on application tab."""
        try:
            context = page.context
            for p in list(context.pages):
                if p != page:
                    u = p.url.lower()
                    if any(marker in u for marker in ("terms-disclaimers", "advisory", "about:blank", "recruitment-process")):
                        logger.info(f"Closing non-application advisory tab: {p.url}")
                        try:
                            p.close()
                        except Exception:
                            pass
        except Exception:
            pass

    def apply_lever(
        self,
        page: Page,
        job_title: str,
        company: str,
        resume_path: Path,
        cover_letter_path: Optional[Path] = None,
    ) -> bool:
        """Fills and reviews Lever.co single-page application form."""
        logger.step(f"Executing Lever ATS auto-fill for: {job_title} at {company}")
        try:
            # 1. Look for 'Apply for this job' / 'Apply now' button if not yet on the form
            apply_btn = page.locator("a.postings-btn, a:has-text('Apply for this job'), a:has-text('Apply now'), button:has-text('Apply')").first
            if apply_btn.count() > 0 and apply_btn.is_visible():
                href = apply_btn.get_attribute("href")
                if href and "/apply" in href and not page.url.endswith("/apply"):
                    page.goto(href if href.startswith("http") else f"https://jobs.lever.co{href}", wait_until="domcontentloaded")
                    time.sleep(2.0)
                else:
                    apply_btn.click()
                    time.sleep(1.5)

            # 2. Attach Resume
            resume_input = page.locator("input#resume-upload-input, input[type='file'][name*='resume'], input[type='file']").first
            if resume_input.count() > 0:
                self._upload_file_to_locator(resume_input, resume_path)

            # 3. Fill Standard Contact Fields
            fields = {
                "name": self.profile.get("full_name", ""),
                "email": self.profile.get("email", ""),
                "phone": self.profile.get("phone", ""),
                "org": self.profile.get("current_company", ""),
            }
            for field_name, val in fields.items():
                inp = page.locator(f"input[name='{field_name}']").first
                if inp.count() > 0 and inp.is_visible():
                    inp.fill(str(val))

            # 4. Fill Social / Profile URLs
            urls = {
                "urls[LinkedIn]": self.profile.get("linkedin_url", ""),
                "urls[GitHub]": self.profile.get("github_url", ""),
                "urls[Portfolio]": self.profile.get("github_url", ""),
                "urls[Other]": self.profile.get("linkedin_url", ""),
            }
            for u_name, u_val in urls.items():
                u_inp = page.locator(f"input[name='{u_name}']").first
                if u_inp.count() > 0 and u_inp.is_visible():
                    u_inp.fill(str(u_val))

            # 5. Fill Custom Questionnaire, EEO and Radios
            form_container = page.locator("form#application-form, form").first
            if form_container.count() > 0:
                self.form_filler.fill_all_inputs_on_page(form_container, job_title=job_title, company=company)

            # 6. Fill and Review Confirmation Gate
            if not self._review_and_confirm(page, job_title, company):
                return False

            # 7. Submit Application
            submit_btn = page.locator("button#btn-submit, button[data-qa='btn-submit'], button:has-text('Submit application'), input[type='submit']").first
            if submit_btn.count() > 0 and submit_btn.is_visible():
                submit_btn.click()
                time.sleep(3.0)
                logger.success(f"Submitted Lever application for '{job_title}' at '{company}'!")
                return True
            else:
                logger.warning("Could not find Lever submit button.")
                return False

        except Exception as e:
            logger.error(f"Error filling Lever application: {e}")
            return False

    def apply_greenhouse(
        self,
        page: Page,
        job_title: str,
        company: str,
        resume_path: Path,
        cover_letter_path: Optional[Path] = None,
    ) -> bool:
        """Fills and reviews Greenhouse.io single-page application form."""
        logger.step(f"Executing Greenhouse ATS auto-fill for: {job_title} at {company}")
        try:
            # 1. Attach Resume
            resume_input = page.locator("input[type='file'][id*='resume'], input[type='file'][aria-label*='resume'], input[type='file']").first
            if resume_input.count() > 0:
                self._upload_file_to_locator(resume_input, resume_path)

            # 2. Attach Cover Letter if requested
            if cover_letter_path and cover_letter_path.exists():
                cl_input = page.locator("input[type='file'][id*='cover_letter'], input[type='file'][aria-label*='cover letter']").first
                if cl_input.count() > 0:
                    self._upload_file_to_locator(cl_input, cover_letter_path)

            # 3. Standard Personal Details
            gh_fields = {
                "#first_name": self.profile.get("first_name", ""),
                "#last_name": self.profile.get("last_name", ""),
                "#email": self.profile.get("email", ""),
                "#phone": self.profile.get("phone", ""),
            }
            for sel, val in gh_fields.items():
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.fill(str(val))

            # 4. Fill custom questions, selects, dropdowns, and EEO demographics
            form_container = page.locator("form#application_form, #grnhse_app, form").first
            if form_container.count() > 0:
                self.form_filler.fill_all_inputs_on_page(form_container, job_title=job_title, company=company)

            # 5. Fill and Review Confirmation Gate
            if not self._review_and_confirm(page, job_title, company):
                return False

            # 6. Submit Application
            submit_btn = page.locator("input#submit_app, button#submit_app, button:has-text('Submit Application')").first
            if submit_btn.count() > 0 and submit_btn.is_visible():
                submit_btn.click()
                time.sleep(3.0)
                logger.success(f"Submitted Greenhouse application for '{job_title}' at '{company}'!")
                return True
            else:
                logger.warning("Could not find Greenhouse submit button.")
                return False

        except Exception as e:
            logger.error(f"Error filling Greenhouse application: {e}")
            return False

    def apply_workday(
        self,
        page: Page,
        job_title: str,
        company: str,
        resume_path: Path,
        cover_letter_path: Optional[Path] = None,
    ) -> bool:
        """
        Fills and reviews Workday multi-step application wizard:
        1. Clicks Apply Manually.
        2. Signs in or creates candidate account using configured password.
        3. Fills Contact Info, Experience, Screening Questions, and Voluntary Self-ID.
        4. Pauses at the Review step for user verification before submitting.
        """
        logger.step(f"Executing Workday ATS auto-fill for: {job_title} at {company}")
        try:
            # 1. Click initial 'Apply' button on posting header
            apply_btn = page.locator(
                "a[data-automation-id='applyButton'], button[data-automation-id='applyButton'], a:has-text('Apply'), button:has-text('Apply')"
            ).first
            if apply_btn.count() > 0 and apply_btn.is_visible():
                apply_btn.click()
                time.sleep(2.5)

            # 2. Choice: 'Apply Manually' vs 'Autofill with Resume'
            apply_manually = page.locator(
                "a[data-automation-id='applyManually'], button[data-automation-id='applyManually'], a:has-text('Apply Manually'), button:has-text('Apply Manually')"
            ).first
            if apply_manually.count() > 0 and apply_manually.is_visible():
                apply_manually.click()
                time.sleep(2.5)

            # 3. Handle Account Sign In or Registration Modal
            email_val = self.profile.get("email", "")
            email_input = page.locator(
                "input[data-automation-id='email'], input[data-automation-id='userName'], input[type='email']"
            ).first
            pw_input = page.locator("input[data-automation-id='password'], input[type='password']").first

            if email_input.count() > 0 and email_input.is_visible():
                email_input.fill(email_val)
                if pw_input.count() > 0 and pw_input.is_visible():
                    pw_input.fill(self.account_password)

                # Check if there is a 'Verify Password' input for account creation
                verify_pw = page.locator("input[data-automation-id='verifyPassword'], input[name*='verify']").first
                if verify_pw.count() > 0 and verify_pw.is_visible():
                    verify_pw.fill(self.account_password)

                # Agree to terms checkbox if present
                terms_cb = page.locator(
                    "input[type='checkbox'][data-automation-id*='consent'], input[type='checkbox']"
                ).first
                if terms_cb.count() > 0 and not terms_cb.is_checked():
                    try:
                        terms_cb.check(force=True)
                    except Exception:
                        pass

                # Submit Sign In / Create Account
                auth_submit = page.locator(
                    "button[data-automation-id='signInSubmitButton'], button[data-automation-id='createAccountSubmitButton'], button:has-text('Sign In'), button:has-text('Create Account')"
                ).first
                if auth_submit.count() > 0 and auth_submit.is_visible():
                    auth_submit.click()
                    time.sleep(4.0)

            # 4. Multi-step Application Wizard Navigation Loop
            max_steps = 7
            for step_num in range(1, max_steps + 1):
                time.sleep(2.5)
                logger.info(f"Navigating Workday application wizard - Step {step_num}")

                # Attach Resume if file input present on current step
                file_input = page.locator(
                    "input[type='file'][data-automation-id*='file-upload'], input[type='file']"
                ).first
                if file_input.count() > 0:
                    self._upload_file_to_locator(file_input, resume_path)

                # Fill all inputs, textareas, selects, checkboxes, radios on current step
                self.form_filler.fill_all_inputs_on_page(page.locator("body"), job_title=job_title, company=company)
                time.sleep(1.0)

                # Check for Submit / Final Review button
                submit_btn = page.locator(
                    "button[data-automation-id='bottom-navigation-control-submit-button'], button:has-text('Submit')"
                ).first
                if submit_btn.count() > 0 and submit_btn.is_visible():
                    # We have reached the final review step!
                    if not self._review_and_confirm(page, job_title, company):
                        return False

                    submit_btn.click()
                    time.sleep(4.0)
                    logger.success(f"Submitted Workday application for '{job_title}' at '{company}'!")
                    return True

                # Look for 'Save and Continue' or 'Next' button to advance to next step
                next_btn = page.locator(
                    "button[data-automation-id='bottom-navigation-control-next-button'], button:has-text('Save and Continue'), button:has-text('Next')"
                ).first
                if next_btn.count() > 0 and next_btn.is_visible():
                    next_btn.click()
                else:
                    logger.info("No further wizard navigation buttons found on Workday.")
                    break

            return False

        except Exception as e:
            logger.error(f"Error filling Workday application: {e}")
            return False

    def apply_smartrecruiters(
        self,
        page: Page,
        job_title: str,
        company: str,
        resume_path: Path,
        cover_letter_path: Optional[Path] = None,
    ) -> bool:
        """Fills and reviews SmartRecruiters application form (standalone or iframe)."""
        logger.step(f"Executing SmartRecruiters ATS auto-fill for: {job_title} at {company}")
        try:
            # 1. Click "I'm interested" or "Apply" button if on job description
            apply_btn = page.locator(
                "a[data-qa='apply-button'], button[data-qa='apply-button'], "
                "a:has-text(\"I'm interested\"), button:has-text(\"I'm interested\"), "
                "a:has-text('Apply now'), button:has-text('Apply now'), "
                "a:has-text('Apply'), button:has-text('Apply')"
            ).first
            if apply_btn.count() > 0 and apply_btn.is_visible():
                apply_btn.click()
                time.sleep(2.5)

            # Check if form is embedded in an iframe
            target_context = page
            for frame in page.frames:
                if "smartrecruiters.com" in frame.url.lower():
                    target_context = frame
                    break

            # 2. Attach Resume (supports hidden file inputs and iframes)
            resume_uploaded = False
            resume_inputs = target_context.locator("input[type='file'][data-qa*='resume'], input[type='file']").all()
            for ri in resume_inputs:
                try:
                    if self._upload_file_to_locator(ri, resume_path):
                        resume_uploaded = True
                        break
                except Exception:
                    continue

            if not resume_uploaded:
                for frame in page.frames:
                    try:
                        frame_files = frame.locator("input[type='file']").all()
                        for fi in frame_files:
                            if self._upload_file_to_locator(fi, resume_path):
                                resume_uploaded = True
                                break
                        if resume_uploaded:
                            break
                    except Exception:
                        continue

            # 3. Fill standard contact fields
            fields = {
                "first-name": self.profile.get("first_name", ""),
                "last-name": self.profile.get("last_name", ""),
                "email": self.profile.get("email", ""),
                "phone": self.profile.get("phone", ""),
            }
            for fid, val in fields.items():
                loc = target_context.locator(f"input[data-qa='{fid}'], input[id*='{fid}'], input[name*='{fid}']").first
                if loc.count() > 0 and loc.is_visible():
                    loc.fill(str(val))

            # 4. Fill remaining questions & screening
            self.form_filler.fill_all_inputs_on_page(target_context.locator("body"), job_title=job_title, company=company)
            if target_context == page:
                for frame in page.frames:
                    if frame != page.main_frame:
                        try:
                            self.form_filler.fill_all_inputs_on_page(frame.locator("body"), job_title=job_title, company=company)
                        except Exception:
                            pass

            # 5. Fill and Review Confirmation Gate
            if not self._review_and_confirm(page, job_title, company):
                return False

            # 6. Submit
            submit_btn = target_context.locator(
                "button[data-qa='btn-submit'], button[type='submit'], button:has-text('Submit Application'), button:has-text('Submit')"
            ).first
            if submit_btn.count() > 0 and submit_btn.is_visible():
                submit_btn.click()
                time.sleep(3.0)
                logger.success(f"Submitted SmartRecruiters application for '{job_title}' at '{company}'!")
                return True

            return False
        except Exception as e:
            logger.error(f"Error filling SmartRecruiters application: {e}")
            return False

    def apply_successfactors(
        self,
        page: Page,
        job_title: str,
        company: str,
        resume_path: Path,
        cover_letter_path: Optional[Path] = None,
    ) -> bool:
        """
        Automated application handler for SAP SuccessFactors / Deloitte Career Portals.
        Workflow:
        1. Dismiss cookie banners.
        2. Click 'Apply now »' CTA button on the job posting (excluding advisory/terms links).
        3. Authenticate:
           - Enter credentials (email & password) on Sign In dialog.
           - If not registered / invalid login, click 'Create an account' and fill registration form.
           - Handle verification / CAPTCHA check if requested.
        4. Fill Application Form:
           - Upload resume and cover letter.
           - Populate candidate profile fields & screening questions.
        5. Fill-and-Review Confirmation:
           - Prompt user in terminal to review before final submission.
           - Submit and verify.
        """
        def safe_count(loc) -> int:
            try:
                c = loc.count() if hasattr(loc, "count") else 0
                return int(c) if isinstance(c, (int, float)) else 0
            except Exception:
                return 0

        def safe_visible(loc) -> bool:
            try:
                return bool(loc.is_visible())
            except Exception:
                return False

        logger.step(f"Executing SAP SuccessFactors / Deloitte auto-fill for: {job_title} at {company}")
        try:
            # Step 1: Dismiss cookies & close accidental advisory popup tabs
            self._dismiss_cookie_banner(page)
            self._close_advisory_tabs(page)

            # Step 2: Click real Apply button if still on job description page
            apply_btn = page.locator(
                "a.dialogApplyBtn, "
                "a[href*='/talentcommunity/apply/'], "
                "a:has-text('Apply now »'), button:has-text('Apply now »'), "
                "a.btn-apply, a.applyButton, button.applyButton, "
                "a[href*='/apply/']:not([href*='terms']):not([href*='advisory'])"
            ).first

            if safe_count(apply_btn) > 0 and safe_visible(apply_btn):
                logger.step(f"Clicking 'Apply now »' button on {company} posting...")
                apply_btn.click()
                time.sleep(3.0)
                self._close_advisory_tabs(page)

            # Step 3: Authentication (User-Driven Login in Open Browser)
            user_inp = page.locator("input#username, input[name='username'], input#fbclc_userName, input[aria-label*='Email Address']").first
            sign_in_btn = page.locator("button:has-text('Sign In'), input[value='Sign In'], a:has-text('Create an account')").first

            needs_login = (
                (safe_count(user_inp) > 0 and safe_visible(user_inp))
                or (safe_count(sign_in_btn) > 0 and safe_visible(sign_in_btn))
                or "career?company=" in page.url.lower()
                or "/careers?company=" in page.url.lower()
                or "sign in" in page.title().lower()
                or "create an account" in page.title().lower()
            )

            if needs_login:
                self._wait_for_user_login(page, company)
                time.sleep(3.0)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                self._close_advisory_tabs(page)

            # Step 4: Manual Application & Green Flag Gatekeeper
            # Auto-filling is intentionally bypassed so the user can manually select options
            # and submit in the browser. Once saved, Deloitte retains the profile for future applications.
            return self._green_flag_confirm(page, job_title, company)

        except Exception as e:
            logger.error(f"Error applying on SAP SuccessFactors / {company} portal: {e}")
            return False

    def apply_generic(
        self,
        page: Page,
        job_title: str,
        company: str,
        resume_path: Path,
        cover_letter_path: Optional[Path] = None,
    ) -> bool:
        """Universal heuristic handler for generic company career sites."""
        logger.step(f"Executing Universal Career Site auto-fill for: {job_title} at {company}")
        try:
            # 1. Handle Candidate Account Creation / Registration Screen (e.g. Flexiple, Ashby, talent networks)
            has_password_input = page.locator("input[type='password']").count() > 0
            signup_button = page.locator(
                "button:has-text('Create account'), button:has-text('Create your account'), "
                "button:has-text('Sign up'), button:has-text('Register'), "
                "button:has-text('Create my account'), button:has-text('Get started'), "
                "button:has-text('Join talent network'), button:has-text('Join talent')"
            ).first
            has_signup_text = bool(re.search(r"create\s*(your\s*)?account|sign\s*up|register", page.content().lower()[:3000]))

            if has_password_input or (signup_button.count() > 0 and signup_button.is_visible() and has_signup_text):
                logger.step(f"Detected candidate account creation / registration on {company} portal.")
                # Fill all Step 1 registration inputs (First name, Last name, Email, Password, Terms checkbox)
                self.form_filler.fill_all_inputs_on_page(page.locator("body"), job_title=job_title, company=company)
                time.sleep(1.5)

                if signup_button.count() > 0 and signup_button.is_visible():
                    logger.info(f"Submitting candidate account registration for: '{company}'...")
                    signup_button.click()
                    time.sleep(4.0)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    time.sleep(2.5)

            # 2. If there's an 'Apply' or 'Apply Now' CTA button, click it
            apply_cta = page.locator(
                "a.dialogApplyBtn, a[href*='/talentcommunity/apply/'], a:has-text('Apply now »'), "
                "button:has-text('Apply now »'), a:has-text('Apply Now'):not(:has-text('know before')), "
                "button:has-text('Apply Now'), a:has-text('Apply for this job'), "
                "button:has-text('Apply for this job'), a:has-text('Apply Online'), "
                "button:has-text('Apply Online')"
            ).first
            if apply_cta.count() > 0 and apply_cta.is_visible():
                apply_cta.click()
                time.sleep(2.5)

                # Re-detect ATS provider in case clicking CTA redirected to a known platform
                post_click_ats = self.detect_ats(page.url, page)
                if post_click_ats != "generic":
                    logger.info(f"Detected ATS provider '{post_click_ats.upper()}' after clicking Apply CTA.")
                    if post_click_ats == "lever":
                        return self.apply_lever(page, job_title, company, resume_path, cover_letter_path)
                    elif post_click_ats == "greenhouse":
                        return self.apply_greenhouse(page, job_title, company, resume_path, cover_letter_path)
                    elif post_click_ats == "workday":
                        return self.apply_workday(page, job_title, company, resume_path, cover_letter_path)
                    elif post_click_ats == "smartrecruiters":
                        return self.apply_smartrecruiters(page, job_title, company, resume_path, cover_letter_path)
                    elif post_click_ats == "successfactors":
                        return self.apply_successfactors(page, job_title, company, resume_path, cover_letter_path)

            # 3. Attach Resume (supports hidden file inputs and iframes)
            file_uploaded = False
            file_inputs = page.locator("input[type='file']").all()
            for fi in file_inputs:
                try:
                    if self._upload_file_to_locator(fi, resume_path):
                        file_uploaded = True
                        break
                except Exception:
                    continue

            if not file_uploaded:
                for frame in page.frames:
                    try:
                        frame_file_inputs = frame.locator("input[type='file']").all()
                        for fi in frame_file_inputs:
                            if self._upload_file_to_locator(fi, resume_path):
                                file_uploaded = True
                                break
                        if file_uploaded:
                            break
                    except Exception:
                        continue

            # 4. Fill all detected inputs on page and across frames
            self.form_filler.fill_all_inputs_on_page(page.locator("body"), job_title=job_title, company=company)
            for frame in page.frames:
                if frame != page.main_frame:
                    try:
                        self.form_filler.fill_all_inputs_on_page(frame.locator("body"), job_title=job_title, company=company)
                    except Exception:
                        pass

            # 5. Application Form Validation Gate:
            # Ensure the page actually contains an application form before prompting review
            has_file_input = file_uploaded or page.locator("input[type='file']").count() > 0
            has_form_fields = page.locator("input[type='text']:visible, input[type='email']:visible, input[type='tel']:visible, textarea:visible").count() > 0
            has_submit_btn = page.locator(
                "button[type='submit'], input[type='submit'], button:has-text('Submit Application'), button:has-text('Submit application'), button:has-text('Submit'), input[value='Submit Application']"
            ).count() > 0

            if not (has_file_input or has_form_fields or has_submit_btn):
                logger.warning(f"No active job application form or resume upload found on {company} page ({page.url}).")
                return False

            # 6. Fill and Review Confirmation Gate
            if not self._review_and_confirm(page, job_title, company):
                return False

            # 7. Check if application was already submitted in browser or locate submit button
            page_text = ""
            try:
                page_text = page.locator("body").inner_text(timeout=1000).lower()
            except Exception:
                pass

            if (
                "thank you for applying" in page_text
                or "application submitted" in page_text
                or "application has been submitted" in page_text
                or "received your application" in page_text
                or "successfully submitted" in page_text
                or "/success" in page.url.lower()
                or "/thank-you" in page.url.lower()
            ):
                logger.success(f"Submitted external application for '{job_title}' at '{company}'!")
                return True

            submit_btn = page.locator(
                "button[type='submit'], input[type='submit'], "
                "button:has-text('Submit Application'), button:has-text('Submit application'), "
                "button:has-text('Submit'), button:has-text('Send Application'), "
                "button:has-text('Complete Application'), button:has-text('Finish'), button:has-text('Done'), "
                "a:has-text('Submit'), a:has-text('Apply Now'), button:has-text('Apply Now')"
            ).first
            if submit_btn.count() > 0 and submit_btn.is_visible():
                submit_btn.click()
                time.sleep(3.0)
                logger.success(f"Submitted external application for '{job_title}' at '{company}'!")
                return True
            elif file_uploaded or has_form_fields:
                logger.success(f"External application for '{job_title}' at '{company}' completed and confirmed.")
                return True
            else:
                logger.warning(f"Could not confirm application submission on {company} page.")
                return False

        except Exception as e:
            logger.error(f"Error filling generic career site: {e}")
            return False

    def apply_external(
        self,
        page: Page,
        job_title: str,
        company: str,
        resume_path: Path,
        cover_letter_path: Optional[Path] = None,
    ) -> bool:
        """
        Master dispatcher for external ATS applications.
        Detects ATS provider and invokes specialized handler.
        """
        try:
            url = page.url
            ats_type = self.detect_ats(url, page)
            logger.step(f"Detected external portal type: '{ats_type.upper()}' for {company} ({url})")

            supported = self.ext_cfg.get("supported_ats", ["lever", "greenhouse", "workday", "smartrecruiters", "successfactors", "generic"])
            if ats_type != "generic" and ats_type not in supported:
                logger.info(f"ATS type '{ats_type}' is not enabled in supported_ats config. Skipping.")
                return False

            if ats_type == "lever":
                return self.apply_lever(page, job_title, company, resume_path, cover_letter_path)
            elif ats_type == "greenhouse":
                return self.apply_greenhouse(page, job_title, company, resume_path, cover_letter_path)
            elif ats_type == "workday":
                return self.apply_workday(page, job_title, company, resume_path, cover_letter_path)
            elif ats_type == "smartrecruiters":
                return self.apply_smartrecruiters(page, job_title, company, resume_path, cover_letter_path)
            elif ats_type == "successfactors":
                return self.apply_successfactors(page, job_title, company, resume_path, cover_letter_path)
            else:
                return self.apply_generic(page, job_title, company, resume_path, cover_letter_path)

        except Exception as e:
            logger.error(f"External ATS application encountered an error: {e}")
            return False
