"""
Unit tests for Workday Career Portal Scanner and Application Engine (platforms/workday_portal.py).
"""

from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from playwright.sync_api import sync_playwright

from database import JobDatabase
from platforms.workday_portal import WorkdayPortalScanner


class TestWorkdayPortal(unittest.TestCase):
    def setUp(self):
        self.dummy_db_path = Path("/tmp/test_workday_jobs.db")
        if self.dummy_db_path.exists():
            self.dummy_db_path.unlink()
        self.db = JobDatabase(str(self.dummy_db_path))

        self.test_config = {
            "search": {
                "keywords": ["DevOps Engineer", "Cloud Infrastructure Engineer"],
                "exclude_skills": ["sap", "salesforce"],
            },
            "profile": {
                "cv_skills": ["aws", "kubernetes", "docker", "terraform", "ci/cd", "python"],
            },
        }

    def tearDown(self):
        if self.dummy_db_path.exists():
            self.dummy_db_path.unlink()

    def test_01_workday_url_parsing_and_company_inference(self):
        """Verifies company name inference and search URL construction for various Workday domains."""
        scanner1 = WorkdayPortalScanner("https://invesco.wd1.myworkdayjobs.com/IVZ", config=self.test_config, db=self.db)
        self.assertEqual(scanner1.company_name, "Invesco")
        search_url1 = scanner1.extract_search_url("https://invesco.wd1.myworkdayjobs.com/IVZ", "DevOps")
        self.assertIn("q=DevOps", search_url1)

        scanner2 = WorkdayPortalScanner("https://accenture.wd3.myworkdayjobs.com/AccentureCareers", config=self.test_config, db=self.db)
        self.assertEqual(scanner2.company_name, "Accenture")

        scanner3 = WorkdayPortalScanner("https://adobe.wd5.myworkdayjobs.com/external_experienced", config=self.test_config, db=self.db)
        self.assertEqual(scanner3.company_name, "Adobe")

    def test_02_workday_job_filtering_and_deduplication(self):
        """Verifies filtering of relevant roles, excluded skills, locations, and duplicate checks."""
        scanner = WorkdayPortalScanner("https://invesco.wd1.myworkdayjobs.com/IVZ", config=self.test_config, db=self.db)

        # Mark R1001 as already applied in database
        self.db.record_application(
            job_id="R1001",
            platform="workday",
            title="DevOps Engineer",
            company="Invesco",
            location="Hyderabad, India",
            status="applied",
        )

        mock_jobs = [
            {
                "id": "R1001",
                "title": "DevOps Engineer",
                "company": "Invesco",
                "location": "Hyderabad, India",
                "posted_date": "2 days ago",
                "url": "https://invesco.wd1.myworkdayjobs.com/IVZ/job/R1001",
            },
            {
                "id": "R1002",
                "title": "Cloud Infrastructure Engineer",
                "company": "Invesco",
                "location": "Bengaluru, India",
                "posted_date": "1 day ago",
                "url": "https://invesco.wd1.myworkdayjobs.com/IVZ/job/R1002",
            },
            {
                "id": "R1003",
                "title": "SAP Solution Architect",
                "company": "Invesco",
                "location": "Hyderabad, India",
                "posted_date": "3 days ago",
                "url": "https://invesco.wd1.myworkdayjobs.com/IVZ/job/R1003",
            },
            {
                "id": "R1004",
                "title": "Senior Marketing Manager",
                "company": "Invesco",
                "location": "Hyderabad, India",
                "posted_date": "4 days ago",
                "url": "https://invesco.wd1.myworkdayjobs.com/IVZ/job/R1004",
            },
            {
                "id": "R1005",
                "title": "DevOps Engineer - US Only",
                "company": "Invesco",
                "location": "Atlanta, USA",
                "posted_date": "Today",
                "url": "https://invesco.wd1.myworkdayjobs.com/IVZ/job/R1005",
            },
        ]

        filtered = scanner.filter_jobs(mock_jobs, keywords=["DevOps Engineer"], target_location="India")

        # R1001 is eligible role & India, but already applied
        r1001 = next(j for j in filtered if j["id"] == "R1001")
        self.assertEqual(r1001["status"], "Already Applied")
        self.assertFalse(r1001["eligible"])

        # R1002 is eligible role & India, not applied yet
        r1002 = next(j for j in filtered if j["id"] == "R1002")
        self.assertEqual(r1002["status"], "Eligible")
        self.assertTrue(r1002["eligible"])

        # R1003 (SAP) and R1004 (Marketing) must be filtered out
        filtered_ids = [j["id"] for j in filtered]
        self.assertNotIn("R1003", filtered_ids)
        self.assertNotIn("R1004", filtered_ids)
        self.assertNotIn("R1005", filtered_ids)

    def test_03_workday_apply_flow_integration(self):
        """Verifies that apply_to_jobs calls ats_handler.apply_workday and persists application in DB."""
        scanner = WorkdayPortalScanner("https://invesco.wd1.myworkdayjobs.com/IVZ", config=self.test_config, db=self.db, headless=True)

        mock_eligible_jobs = [
            {
                "id": "R2001",
                "title": "DevOps Engineer",
                "company": "Invesco",
                "location": "Hyderabad, India",
                "posted_date": "1 day ago",
                "url": "https://invesco.wd1.myworkdayjobs.com/IVZ/job/R2001",
                "eligible": True,
            }
        ]

        with patch.object(scanner.ats_handler, "apply_workday", return_value=True) as mock_apply:
            with patch("platforms.workday_portal.BrowserManager") as mock_bm_cls:
                mock_bm = MagicMock()
                mock_page = MagicMock()
                mock_bm.start.return_value = mock_page
                mock_bm_cls.return_value = mock_bm

                applied = scanner.apply_to_jobs(mock_eligible_jobs)
                self.assertEqual(applied, 1)
                mock_apply.assert_called_once()
                self.assertTrue(self.db.is_job_applied("R2001", "workday"))

    def test_04_direct_apply_url_execution(self):
        """Verifies execute_apply_url executes ats_handler and records direct applications (e.g. Deloitte)."""
        from main import execute_apply_url

        with patch("main.ExternalATSHandler.apply_external", return_value=True) as mock_apply:
            with patch("main.BrowserManager") as mock_bm_cls:
                mock_bm = MagicMock()
                mock_page = MagicMock()
                mock_bm.start.return_value = mock_page
                mock_bm_cls.return_value = mock_bm

                execute_apply_url(
                    url="https://jobs2.deloitte.com/in/en/job/DELOA003X/DevOps-Engineer",
                    title="DevOps Engineer",
                    company="Deloitte",
                    headless=True,
                    db=self.db,
                )
                mock_apply.assert_called_once()
                self.assertTrue(self.db.is_url_or_company_applied(company="Deloitte", title="DevOps Engineer"))


if __name__ == "__main__":
    unittest.main()
