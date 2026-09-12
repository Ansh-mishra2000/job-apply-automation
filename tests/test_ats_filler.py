"""
Comprehensive test suite for External ATS Automation (Workday, Greenhouse, Lever, SmartRecruiters, Generic).
Tests ATS detection, Fill-and-Review confirmation logic, DOM auto-filling, and platform integrations.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from playwright.sync_api import sync_playwright
from config_loader import load_config
from utils.ats_filler import ExternalATSHandler
from platforms.naukri import NaukriPlatform
from platforms.linkedin import LinkedInPlatform


class TestExternalATSFiller(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        cls.config["profile"] = {
            "full_name": "Test Candidate",
            "first_name": "TestFirst",
            "last_name": "TestLast",
            "email": "test.candidate@example.com",
            "phone": "9876543210",
            "street_address": "123 Tech Lane",
            "current_city": "Bengaluru",
            "state": "Karnataka",
            "postal_code": "560001",
            "country": "India",
            "linkedin_url": "https://www.linkedin.com/in/test-candidate/",
            "github_url": "https://github.com/test-candidate",
            "current_ctc": "700000",
            "expected_ctc": "1200000",
            "notice_period_days": 30,
            "total_experience_years": 2,
            "relevant_experience_years": 2,
            "work_authorization": "Yes",
            "requires_sponsorship": "No",
            "willing_to_relocate": "Yes",
            "remote_work_preference": "Yes",
            "gender": "Male",
            "skills_experience": {"aws": 2, "kubernetes": 2, "python": 2},
        }
        cls.config["external_apply"] = {
            "enabled": True,
            "auto_submit": False,
            "account_password": "TestSecurePassword123!",
            "supported_ats": ["lever", "greenhouse", "workday", "smartrecruiters", "bamboohr", "successfactors", "generic"],
        }
        # Create a temporary dummy resume file for file upload tests
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.dummy_resume = Path(cls.temp_dir.name) / "test_resume.pdf"
        cls.dummy_resume.write_text("Dummy Resume Content for ATS Testing")

        cls.dummy_cover_letter = Path(cls.temp_dir.name) / "test_cover_letter.pdf"
        cls.dummy_cover_letter.write_text("Dummy Cover Letter Content for ATS Testing")

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
            cls.playwright.stop()
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def setUp(self):
        self.ats_handler = ExternalATSHandler(self.config)

    def test_01_ats_url_detection(self):
        """Tests that external URLs are correctly classified into the proper ATS provider."""
        url_cases = [
            ("https://jobs.lever.co/stripe/abc-123", "lever"),
            ("https://lever.co/careers/job/456", "lever"),
            ("https://boards.greenhouse.io/airbnb/jobs/789", "greenhouse"),
            ("https://job-boards.greenhouse.io/figma/jobs/101", "greenhouse"),
            ("https://adobe.myworkdayjobs.com/en-US/external/job/DevOps_R123", "workday"),
            ("https://wd1.myworkday.com/walmart/d/inst/1$9925/9925.htmld", "workday"),
            ("https://jobs.smartrecruiters.com/Square/2026-sre", "smartrecruiters"),
            ("https://gitlab.bamboohr.com/careers/55", "bamboohr"),
            ("https://careers.google.com/jobs/results/123", "generic"),
            ("https://techcorp.internal.jobs/apply", "generic"),
        ]

        for url, expected_type in url_cases:
            detected = self.ats_handler.detect_ats(url)
            self.assertEqual(
                detected,
                expected_type,
                f"URL '{url}' detected as '{detected}', expected '{expected_type}'",
            )

    def test_02_ats_dom_detection_fallback(self):
        """Tests that when a generic URL is loaded, DOM signatures identify the underlying ATS."""
        page = self.browser.new_page()
        try:
            # HTML with Workday automation tags on a generic company domain
            workday_html = """
            <html>
                <body>
                    <div data-automation-id="jobPostingHeader"><h1>DevOps Engineer</h1></div>
                    <a data-automation-id="applyButton" href="#apply">Apply</a>
                </body>
            </html>
            """
            page.set_content(workday_html)
            detected = self.ats_handler.detect_ats("https://careers.acmecorp.com/postings/123", page=page)
            self.assertEqual(detected, "workday")

            # HTML with Lever form action on a generic domain
            lever_html = """
            <html>
                <body>
                    <form action="https://api.lever.co/v0/postings/acme/123/apply" id="application-form">
                        <input name="name" />
                    </form>
                </body>
            </html>
            """
            page.set_content(lever_html)
            detected = self.ats_handler.detect_ats("https://jobs.acmecorp.com/position", page=page)
            self.assertEqual(detected, "lever")
        finally:
            page.close()

    def test_03_fill_and_review_mode_confirmation(self):
        """Tests that Fill-and-Review mode respects user input (Enter = proceed, 's' = skip)."""
        page = self.browser.new_page()
        try:
            # Ensure auto_submit is False (Fill-and-Review mode)
            self.ats_handler.auto_submit = False

            # Case A: User confirms with ENTER (empty string)
            with patch("builtins.input", return_value=""):
                confirmed = self.ats_handler._review_and_confirm(page, "DevOps Engineer", "Netflix")
                self.assertTrue(confirmed, "Empty ENTER should confirm application submission.")

            # Case B: User confirms with 'yes' or 'y'
            with patch("builtins.input", return_value="y"):
                confirmed = self.ats_handler._review_and_confirm(page, "DevOps Engineer", "Netflix")
                self.assertTrue(confirmed, "'y' should confirm application submission.")

            # Case C: User skips with 's'
            with patch("builtins.input", return_value="s"):
                confirmed = self.ats_handler._review_and_confirm(page, "DevOps Engineer", "Netflix")
                self.assertFalse(confirmed, "'s' should cancel/skip application submission.")

            # Case D: User skips with 'skip'
            with patch("builtins.input", return_value="skip"):
                confirmed = self.ats_handler._review_and_confirm(page, "DevOps Engineer", "Netflix")
                self.assertFalse(confirmed, "'skip' should cancel application submission.")

            # Case E: auto_submit = True should bypass prompt completely
            self.ats_handler.auto_submit = True
            with patch("builtins.input", side_effect=Exception("Should not prompt when auto_submit=True")):
                confirmed = self.ats_handler._review_and_confirm(page, "DevOps Engineer", "Netflix")
                self.assertTrue(confirmed, "auto_submit=True should return True without prompting user.")
        finally:
            page.close()

    def test_04_live_dom_lever_form_filling(self):
        """Simulates a Lever DOM form, verifying that contact info, URLs, resume, and screening inputs are filled."""
        page = self.browser.new_page()
        try:
            lever_html = """
            <!DOCTYPE html>
            <html>
            <head><title>DevOps Engineer - Stripe</title></head>
            <body>
                <form id="application-form">
                    <input type="file" id="resume-upload-input" name="resume" />
                    <input type="text" name="name" placeholder="Full name" />
                    <input type="email" name="email" placeholder="Email" />
                    <input type="tel" name="phone" placeholder="Phone" />
                    <input type="text" name="org" placeholder="Current company" />
                    <input type="text" name="urls[LinkedIn]" placeholder="LinkedIn URL" />
                    <input type="text" name="urls[GitHub]" placeholder="GitHub URL" />
                    <div>
                        <label for="notice_period">Notice Period (in days)</label>
                        <input type="text" id="notice_period" />
                    </div>
                    <fieldset>
                        <legend>Are you legally authorized to work?</legend>
                        <label><input type="radio" name="auth" value="Yes" /> Yes</label>
                        <label><input type="radio" name="auth" value="No" /> No</label>
                    </fieldset>
                    <button type="button" id="btn-submit">Submit application</button>
                </form>
            </body>
            </html>
            """
            page.set_content(lever_html)

            # Mock user confirmation for Fill-and-Review
            with patch.object(self.ats_handler, "_review_and_confirm", return_value=True):
                success = self.ats_handler.apply_lever(
                    page=page,
                    job_title="DevOps Engineer",
                    company="Stripe",
                    resume_path=self.dummy_resume,
                    cover_letter_path=self.dummy_cover_letter,
                )
                self.assertTrue(success, "apply_lever should return True when form is filled and submitted.")

            # Validate filled form values
            self.assertEqual(page.locator("input[name='name']").input_value(), "Test Candidate")
            self.assertEqual(page.locator("input[name='email']").input_value(), "test.candidate@example.com")
            self.assertEqual(page.locator("input[name='phone']").input_value(), "9876543210")
            self.assertIn("https://www.linkedin.com/in/", page.locator("input[name='urls[LinkedIn]']").input_value())
            self.assertEqual(page.locator("input[name='urls[GitHub]']").input_value(), "https://github.com/test-candidate")
            self.assertEqual(page.locator("input#notice_period").input_value(), "30")
            self.assertTrue(page.locator("input[name='auth'][value='Yes']").is_checked())
        finally:
            page.close()

    def test_05_live_dom_greenhouse_form_filling(self):
        """Simulates a Greenhouse DOM form, verifying first/last name splitting, questions, and select dropdowns."""
        page = self.browser.new_page()
        try:
            greenhouse_html = """
            <!DOCTYPE html>
            <html>
            <head><title>Cloud Infrastructure Engineer - Airbnb</title></head>
            <body>
                <form id="application_form">
                    <input type="file" id="resume" />
                    <input type="text" id="first_name" />
                    <input type="text" id="last_name" />
                    <input type="email" id="email" />
                    <input type="tel" id="phone" />
                    <div>
                        <label for="eeo_gender">Gender</label>
                        <select id="eeo_gender">
                            <option value="">Please select</option>
                            <option value="Male">Male</option>
                            <option value="Female">Female</option>
                            <option value="Decline">I decline to identify</option>
                        </select>
                    </div>
                    <div>
                        <label for="custom_ctc">Expected CTC</label>
                        <input type="text" id="custom_ctc" />
                    </div>
                    <button type="button" id="submit_app">Submit Application</button>
                </form>
            </body>
            </html>
            """
            page.set_content(greenhouse_html)

            with patch.object(self.ats_handler, "_review_and_confirm", return_value=True):
                success = self.ats_handler.apply_greenhouse(
                    page=page,
                    job_title="Cloud Infrastructure Engineer",
                    company="Airbnb",
                    resume_path=self.dummy_resume,
                    cover_letter_path=self.dummy_cover_letter,
                )
                self.assertTrue(success, "apply_greenhouse should return True on submission.")

            self.assertEqual(page.locator("#first_name").input_value(), "TestFirst")
            self.assertEqual(page.locator("#last_name").input_value(), "TestLast")
            self.assertEqual(page.locator("#email").input_value(), "test.candidate@example.com")
            self.assertEqual(page.locator("#eeo_gender").input_value(), "Male")
            self.assertEqual(page.locator("#custom_ctc").input_value(), str(self.config["profile"]["expected_ctc"]))
        finally:
            page.close()

    def test_06_live_dom_workday_account_and_wizard(self):
        """Simulates Workday application wizard with candidate account login and review step."""
        page = self.browser.new_page()
        try:
            workday_html = """
            <!DOCTYPE html>
            <html>
            <body>
                <a data-automation-id="applyButton" href="#apply">Apply</a>
                <div id="auth-modal">
                    <input data-automation-id="email" type="email" />
                    <input data-automation-id="password" type="password" />
                    <button data-automation-id="signInSubmitButton">Sign In</button>
                </div>
                <div id="step-content">
                    <input type="file" data-automation-id="file-upload-input-ref" />
                    <label for="phone">Phone Number</label>
                    <input type="tel" id="phone" />
                </div>
                <button data-automation-id="bottom-navigation-control-submit-button">Submit</button>
            </body>
            </html>
            """
            page.set_content(workday_html)

            with patch.object(self.ats_handler, "_review_and_confirm", return_value=True):
                success = self.ats_handler.apply_workday(
                    page=page,
                    job_title="DevOps Engineer",
                    company="Adobe",
                    resume_path=self.dummy_resume,
                    cover_letter_path=self.dummy_cover_letter,
                )
                self.assertTrue(success, "apply_workday should succeed through account login and submit.")

            self.assertEqual(page.locator("input[data-automation-id='email']").input_value(), "test.candidate@example.com")
            self.assertEqual(page.locator("input[data-automation-id='password']").input_value(), "TestSecurePassword123!")
            self.assertEqual(page.locator("input#phone").input_value(), "9876543210")
        finally:
            page.close()

    def test_07_platform_handler_instantiation(self):
        """Verifies that NaukriPlatform and LinkedInPlatform correctly initialize ExternalATSHandler."""
        db_mock = MagicMock()
        naukri = NaukriPlatform(self.config, db_mock, headless=True)
        self.assertIsNotNone(getattr(naukri, "ats_handler", None))
        self.assertIsInstance(naukri.ats_handler, ExternalATSHandler)

        linkedin = LinkedInPlatform(self.config, db_mock, headless=True)
        self.assertIsNotNone(getattr(linkedin, "ats_handler", None))
        self.assertIsInstance(linkedin.ats_handler, ExternalATSHandler)

    def test_08_live_dom_smartrecruiters_form_and_hidden_file_upload(self):
        """Tests SmartRecruiters form filling with hidden file input and review gate."""
        page = self.browser.new_page()
        try:
            sr_html = """
            <!DOCTYPE html>
            <html>
            <body>
                <a data-qa="apply-button" href="#apply">I'm interested</a>
                <form id="sr-form">
                    <input type="file" style="display:none;" />
                    <input type="text" data-qa="first-name" />
                    <input type="text" data-qa="last-name" />
                    <input type="email" data-qa="email" />
                    <input type="tel" data-qa="phone" />
                    <button type="button" data-qa="btn-submit">Submit Application</button>
                </form>
            </body>
            </html>
            """
            page.set_content(sr_html)

            with patch.object(self.ats_handler, "_review_and_confirm", return_value=True):
                success = self.ats_handler.apply_smartrecruiters(
                    page=page,
                    job_title="Senior SRE",
                    company="Visa",
                    resume_path=self.dummy_resume,
                )
                self.assertTrue(success, "apply_smartrecruiters should succeed with hidden file input.")

            self.assertEqual(page.locator("input[data-qa='first-name']").input_value(), "TestFirst")
            self.assertEqual(page.locator("input[data-qa='last-name']").input_value(), "TestLast")
            self.assertEqual(page.locator("input[data-qa='email']").input_value(), "test.candidate@example.com")
            self.assertEqual(page.locator("input[data-qa='phone']").input_value(), "9876543210")
        finally:
            page.close()

    def test_09_generic_cta_redirection_to_ats(self):
        """Tests that apply_generic re-detects ATS after clicking the initial Apply CTA."""
        page = self.browser.new_page()
        try:
            landing_html = """
            <!DOCTYPE html>
            <html>
            <body>
                <h1>Careers at Fintech Corp</h1>
                <a href="#apply" id="apply-btn" onclick="document.getElementById('sr-sec').style.display='block';">Apply Now</a>
                <div id="sr-sec" style="display:none;" data-qa="smartrecruiters">
                    <input type="file" />
                    <input type="text" data-qa="first-name" />
                    <input type="text" data-qa="last-name" />
                    <input type="email" data-qa="email" />
                    <button type="button" data-qa="btn-submit">Submit</button>
                </div>
            </body>
            </html>
            """
            page.set_content(landing_html)

            with patch.object(self.ats_handler, "_review_and_confirm", return_value=True):
                # When apply_generic runs, clicking Apply Now displays the smartrecruiters element, triggering re-detection
                success = self.ats_handler.apply_generic(
                    page=page,
                    job_title="DevOps Engineer",
                    company="Fintech Corp",
                    resume_path=self.dummy_resume,
                )
                self.assertTrue(success)
        finally:
            page.close()

    def test_11_live_dom_candidate_account_creation_flexiple_style(self):
        """Replicates Flexiple/talent portal candidate account creation screen (Step 1 of 2)."""
        page = self.browser.new_page()
        try:
            flexiple_html = """
            <!DOCTYPE html>
            <html>
            <body>
                <div id="step1">
                    <h2>Step 1 of 2</h2>
                    <h1>Create your account</h1>
                    <p>Get started in under a minute</p>
                    <div class="space-y-4">
                        <div class="flex flex-col">
                            <label class="text-sm font-semibold">First name *</label>
                            <input type="text" name="firstName" />
                        </div>
                        <div class="flex flex-col">
                            <label class="text-sm font-semibold">Last name *</label>
                            <input type="text" name="lastName" />
                        </div>
                        <div class="flex flex-col">
                            <label class="text-sm font-semibold">Email *</label>
                            <input type="email" name="email" />
                        </div>
                        <div class="flex flex-col">
                            <label class="text-sm font-semibold">Password *</label>
                            <input type="password" placeholder="Create a password" />
                        </div>
                        <div class="flex items-center">
                            <label class="text-xs">
                                <input type="checkbox" name="terms" />
                                I agree to the <a href="#">Terms of Service</a> and <a href="#">Privacy Policy</a>
                            </label>
                        </div>
                        <button type="button" onclick="document.getElementById('step1').style.display='none'; document.getElementById('step2').style.display='block';">Create account</button>
                    </div>
                </div>
                <div id="step2" style="display:none;">
                    <h2>Step 2 of 2: Upload Resume</h2>
                    <input type="file" />
                    <button type="button">Submit Application</button>
                </div>
            </body>
            </html>
            """
            page.set_content(flexiple_html)

            # Test FormFiller on Step 1 directly first
            self.ats_handler.form_filler.fill_all_inputs_on_page(page.locator("#step1"), job_title="DevOps Engineer", company="Flexiple")

            # Verify accurate fields without "Yes" corruption
            self.assertEqual(page.locator("input[name='firstName']").input_value(), "TestFirst")
            self.assertNotEqual(page.locator("input[name='firstName']").input_value(), "Yes")

            self.assertEqual(page.locator("input[name='lastName']").input_value(), "TestLast")
            self.assertNotEqual(page.locator("input[name='lastName']").input_value(), "Yes")

            self.assertEqual(page.locator("input[name='email']").input_value(), "test.candidate@example.com")
            self.assertNotEqual(page.locator("input[name='email']").input_value(), "Yes")

            self.assertEqual(page.locator("input[type='password']").input_value(), "TestSecurePassword123!")
            self.assertTrue(page.locator("input[type='checkbox']").is_checked(), "Terms checkbox must be checked")

            # Now test apply_generic full flow on this page with mock confirmation
            page.set_content(flexiple_html)
            with patch.object(self.ats_handler, "_review_and_confirm", return_value=True):
                success = self.ats_handler.apply_generic(
                    page=page,
                    job_title="DevOps Engineer",
                    company="Flexiple",
                    resume_path=self.dummy_resume,
                )
                self.assertTrue(success, "apply_generic should successfully create candidate account and submit Step 2.")
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()


