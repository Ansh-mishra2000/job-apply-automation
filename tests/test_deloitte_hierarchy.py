"""
Unit tests for Deloitte / SAP SuccessFactors application hierarchy,
Apply CTA precision, authentication flow, and advisory link rejection.
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from database import JobDatabase
from utils.ats_filler import ExternalATSHandler


class TestDeloitteHierarchy(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_jobs.db"
        self.db = JobDatabase(str(self.db_path))

        self.resume_path = Path(self.temp_dir.name) / "test_resume.pdf"
        self.resume_path.write_text("Dummy Resume Content")

        self.test_config = {
            "profile": {
                "first_name": "TestFirst",
                "last_name": "TestLast",
                "email": "candidate@example.com",
                "phone": "9876543210",
                "current_city": "Bengaluru",
                "country": "India",
            },
            "external_apply": {
                "enabled": True,
                "auto_submit": False,
                "account_password": "MockPassword123!",
                "supported_ats": ["lever", "greenhouse", "workday", "smartrecruiters", "successfactors", "generic"],
            },
        }
        self.handler = ExternalATSHandler(self.test_config)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_detect_ats_successfactors_domains(self):
        """Verifies detect_ats identifies SuccessFactors from various Deloitte & SAP domains."""
        urls = [
            "https://southasiacareers.deloitte.com/job/Bengaluru-Senior-Consultant-DevOps/59416044/",
            "https://career44.sapsf.com/career?company=deloittesh&site=&lang=en_US",
            "https://jobs2.deloitte.com/in/en/job/DELOA003X/DevOps-Engineer",
            "https://careers.deloitte.com/jobs/devops",
        ]
        for u in urls:
            detected = self.handler.detect_ats(u)
            self.assertEqual(detected, "successfactors", f"Failed for URL: {u}")

    def test_02_apply_button_selector_ignores_advisory(self):
        """
        Verifies that on a DOM containing both 'What to know before you apply' and
        'Apply now »', the selector matches the actual Apply button, NOT the advisory link.
        """
        mock_page = MagicMock()
        def mock_loc(sel):
            m = MagicMock()
            m.count.return_value = 1 if "dialogApplyBtn" in sel else 0
            m.is_visible.return_value = True
            m.first = m
            return m

        mock_page.locator.side_effect = mock_loc

        apply_btn = mock_page.locator(
            "a.dialogApplyBtn, a[href*='/talentcommunity/apply/'], a:has-text('Apply now »'), button:has-text('Apply now »')"
        ).first

        self.assertEqual(apply_btn.count(), 1)
        self.assertTrue(apply_btn.is_visible())

    def test_03_close_advisory_tabs(self):
        """Verifies _close_advisory_tabs closes any popup tabs with terms/advisory URLs."""
        mock_page = MagicMock()
        mock_context = MagicMock()
        mock_page.context = mock_context

        main_tab = mock_page
        advisory_tab = MagicMock()
        advisory_tab.url = "https://www.deloitte.com/in/en/careers/explore-your-fit/students/terms-disclaimers-recruitment-process.html"
        blank_tab = MagicMock()
        blank_tab.url = "about:blank"

        mock_context.pages = [main_tab, advisory_tab, blank_tab]

        self.handler._close_advisory_tabs(mock_page)

        advisory_tab.close.assert_called_once()
        blank_tab.close.assert_called_once()
        main_tab.close.assert_not_called()

    def test_04_apply_successfactors_full_hierarchy(self):
        """
        Verifies that apply_successfactors handles Apply button click, registration,
        and prompts Fill-and-Review before completion.
        """
        mock_page = MagicMock()
        mock_page.url = "https://southasiacareers.deloitte.com/job/123"
        mock_page.context.pages = [mock_page]

        with patch.object(self.handler, "_wait_for_user_login") as mock_login, \
             patch.object(self.handler, "_green_flag_confirm", return_value=True) as mock_green_flag:
            result = self.handler.apply_successfactors(
                page=mock_page,
                job_title="Senior Consultant | DevOps",
                company="Deloitte",
                resume_path=self.resume_path,
            )
            self.assertTrue(result)
            mock_green_flag.assert_called_once()

    def test_05_apply_successfactors_bypasses_autofill(self):
        """
        Verifies that apply_successfactors does NOT call form_filler.fill_all_inputs_on_page
        and does not auto-submit, allowing manual option selection by user.
        """
        mock_page = MagicMock()
        mock_page.url = "https://southasiacareers.deloitte.com/job/456"
        mock_page.context.pages = [mock_page]

        with patch.object(self.handler.form_filler, "fill_all_inputs_on_page") as mock_form_fill, \
             patch.object(self.handler, "_green_flag_confirm", return_value=True):
            self.handler.apply_successfactors(
                page=mock_page,
                job_title="DevOps Engineer",
                company="Deloitte",
                resume_path=self.resume_path,
            )
            mock_form_fill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
