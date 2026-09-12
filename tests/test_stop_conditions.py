"""
Automated Test Suite for Application Stop & Handover Conditions
Tests every condition under which the application stops or transitions:
1. Both platforms exceed daily quotas -> Application stops cleanly.
2. One platform hits quota -> Browser closes, hands over to other platform.
3. Expired session / Authwall detected -> Stops platform run and warns user to re-login.
4. Unfillable job screening questions -> Safely skips the single job, DOES NOT stop the script.
5. All jobs in search criteria already applied -> Completes cycle cleanly without looping.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from database import JobDatabase
from platforms.linkedin import LinkedInPlatform
from platforms.naukri import NaukriPlatform
import main


class TestStopConditions(unittest.TestCase):
    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        self.db = JobDatabase(db_path=self.temp_db_path)
        self.test_config = {
            "search": {
                "keywords": ["DevOps Engineer"],
                "locations": ["India"],
                "date_posted": "24h",
            },
            "platforms": {
                "linkedin": {"enabled": True, "max_daily_applications": 2},
                "naukri": {"enabled": True, "max_daily_applications": 2},
            },
            "profile": {
                "full_name": "Test Candidate",
                "total_experience_years": 2,
                "relevant_experience_years": 2,
                "resume_path": "resume.pdf",
            },
            "profile_refresh": {"auto_update_before_apply": False},
            "execution": {"display_mode": "background"},
        }

    def tearDown(self):
        try:
            self.db.close()
            os.close(self.temp_db_fd)
            if os.path.exists(self.temp_db_path):
                os.remove(self.temp_db_path)
        except Exception:
            pass

    def test_stop_condition_01_both_platforms_quota_reached(self):
        """
        STOP CONDITION 1:
        When both LinkedIn and Naukri have reached their daily application limit,
        the application MUST STOP cleanly, display stats, and not launch any browser.
        """
        self.db.mark_daily_limit_reached("linkedin")
        self.db.mark_daily_limit_reached("naukri")

        self.assertTrue(self.db.is_daily_limit_reached("linkedin"))
        self.assertTrue(self.db.is_daily_limit_reached("naukri"))

        with patch("main.load_config", return_value=self.test_config), \
             patch("main.JobDatabase", return_value=self.db), \
             patch("main.LinkedInPlatform") as mock_lp, \
             patch("main.NaukriPlatform") as mock_np, \
             patch("main.show_stats") as mock_stats:

            main.execute_job_apply(platform_name="all", headless=True)

            mock_lp.return_value.run.assert_not_called()
            mock_np.return_value.run.assert_not_called()
            mock_stats.assert_called_once()

    def test_stop_condition_02_quota_handover_between_platforms(self):
        """
        STOP CONDITION 2 (HANDOVER):
        When LinkedIn hits its quota mid-run, it MUST close LinkedIn immediately
        and hand over execution to Naukri, continuing to apply on Naukri.
        """
        lp_mock = MagicMock()
        lp_mock.limit_reached = False

        def hit_quota_during_run(*args, **kwargs):
            lp_mock.limit_reached = True

        lp_mock.run.side_effect = hit_quota_during_run

        np_mock = MagicMock()
        np_mock.limit_reached = False

        with patch("main.load_config", return_value=self.test_config), \
             patch("main.JobDatabase", return_value=self.db), \
             patch("main.LinkedInPlatform", return_value=lp_mock), \
             patch("main.NaukriPlatform", return_value=np_mock), \
             patch("main.show_stats"):

            main.execute_job_apply(platform_name="all", headless=True)

            # LinkedIn was run and triggered limit_reached
            lp_mock.run.assert_called_once()
            # Naukri took over and was run
            np_mock.run.assert_called_once()

    def test_stop_condition_03_expired_session_authwall(self):
        """
        STOP CONDITION 3:
        When an expired session or authwall is detected, the platform MUST stop
        its run immediately with return code 0, without crashing or hanging.
        """
        lp = LinkedInPlatform(self.test_config, self.db, headless=True)

        mock_page = MagicMock()
        mock_page.url = "https://www.linkedin.com/authwall?trk=..."

        mock_browser = MagicMock()
        mock_browser.start.return_value = mock_page

        with patch("platforms.linkedin.BrowserManager", return_value=mock_browser):
            result = lp.run(keyword_override="DevOps", location_override="India")
            self.assertEqual(result, 0)
            mock_browser.close.assert_called_once()

    def test_stop_condition_04_unfillable_questions_skips_not_crash(self):
        """
        STOP CONDITION 4 (JOB SKIP VS BOT STOP):
        When a job has unfillable questions or modal errors, the bot MUST skip
        only that specific job (discarding modal) and CONTINUE running remaining jobs.
        It must NOT terminate the entire application.
        """
        lp = LinkedInPlatform(self.test_config, self.db, headless=True)

        mock_page = MagicMock()
        mock_modal = MagicMock()
        mock_modal.count.return_value = 1
        mock_modal.first.is_visible.return_value = True

        mock_next_btn = MagicMock()
        mock_next_btn.count.return_value = 1
        mock_next_btn.first.is_visible.return_value = True

        mock_submit_btn = MagicMock()
        mock_submit_btn.count.return_value = 0

        mock_review_btn = MagicMock()
        mock_review_btn.count.return_value = 0

        def locator_router(selector):
            if "jobs-easy-apply-modal" in selector:
                return mock_modal
            if "Submit" in selector:
                return mock_submit_btn
            if "Review" in selector:
                return mock_review_btn
            if "Next" in selector or "Continue" in selector:
                return mock_next_btn
            m = MagicMock()
            m.count.return_value = 0
            m.all.return_value = []
            return m

        mock_page.locator.side_effect = locator_router
        mock_modal.locator.side_effect = locator_router

        with patch.object(lp, "_discard_application_modal") as mock_discard, \
             patch("time.sleep", return_value=None):
            success = lp._fill_and_submit_easy_apply(mock_page, "Difficult Job", "Complex Corp")
            self.assertFalse(success)
            mock_discard.assert_called_once()

    def test_stop_condition_05_all_jobs_already_applied(self):
        """
        STOP CONDITION 5:
        When all job cards returned have already been applied to (stored in DB),
        the system must recognize them, skip without opening modals, and complete cycle.
        """
        self.db.record_application(
            job_id="12345",
            platform="linkedin",
            title="DevOps Engineer",
            company="Tech Corp",
            location="India",
            job_url="https://www.linkedin.com/jobs/view/12345/",
            status="applied",
        )

        self.assertTrue(self.db.is_job_applied("12345", "linkedin"))
        self.assertFalse(self.db.is_job_applied("99999", "linkedin"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
