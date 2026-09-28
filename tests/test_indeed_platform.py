"""
Unit tests for Indeed platform automation engine (platforms/indeed.py).
"""

import unittest
from unittest.mock import MagicMock, patch

from database import JobDatabase
from platforms.indeed import IndeedPlatform


class TestIndeedPlatform(unittest.TestCase):
    def setUp(self):
        self.config = {
            "search": {
                "keywords": ["DevOps Engineer", "Cloud Engineer"],
                "locations": ["Noida", "Bengaluru"],
                "experience_years": "0-3",
                "date_posted": "30d",
                "exclude_staffing_agencies": True,
            },
            "platforms": {
                "indeed": {
                    "enabled": True,
                    "max_daily_applications": 50,
                    "easily_apply_only": True,
                }
            },
            "profile": {
                "full_name": "Ansh Mishra",
                "first_name": "Ansh",
                "last_name": "Mishra",
                "email": "ansh@example.com",
                "phone": "9999999999",
                "total_experience_years": 2,
                "skills_experience": {"aws": 2, "kubernetes": 2, "docker": 2, "python": 2},
            },
        }
        self.mock_db = MagicMock(spec=JobDatabase)
        self.platform = IndeedPlatform(self.config, self.mock_db, headless=True)

    def test_build_search_url_india_and_pagination(self):
        """Tests that Indian locations target in.indeed.com with proper fromage and pagination."""
        url = self.platform._build_search_url("DevOps Engineer", "Noida", time_filter="24h", page_no=2)
        self.assertIn("in.indeed.com/jobs?", url)
        self.assertIn("q=DevOps+Engineer", url)
        self.assertIn("l=Noida", url)
        self.assertIn("fromage=1", url)
        self.assertIn("start=20", url)

    def test_build_search_url_global_and_time_filters(self):
        """Tests US/Global locations target www.indeed.com with respective date filters."""
        # 7d filter
        url_7d = self.platform._build_search_url("SRE", "New York", time_filter="7d", page_no=0)
        self.assertIn("www.indeed.com/jobs?", url_7d)
        self.assertIn("fromage=7", url_7d)
        self.assertNotIn("start=", url_7d)

        # 14d / 15d filter
        url_15d = self.platform._build_search_url("Cloud Engineer", "London", time_filter="15d")
        self.assertIn("fromage=14", url_15d)

        # 30d filter
        url_30d = self.platform._build_search_url("Platform Engineer", "Austin", time_filter="30d")
        self.assertIn("fromage=30", url_30d)

    def test_check_limit_detection(self):
        """Tests detection of application limit or bot challenge in Indeed."""
        mock_page = MagicMock()
        mock_page.title.return_value = "Verify you are human | Indeed"
        mock_page.locator.return_value.all.return_value = []

        self.assertTrue(self.platform._check_limit(mock_page))

        # Test normal page
        mock_page.title.return_value = "DevOps Engineer Jobs in Noida - Indeed"
        self.assertFalse(self.platform._check_limit(mock_page))

    def test_agency_filtering_in_indeed(self):
        """Tests that staffing agency titles or companies are flagged and skipped."""
        from utils.job_filter import is_staffing_agency

        self.assertTrue(is_staffing_agency("XYZ Staffing Solutions", "Hiring for C2H client"))
        self.assertTrue(is_staffing_agency("Direct Placement Consultants", "Third party payroll"))
        self.assertFalse(is_staffing_agency("Deloitte", "Direct hire DevOps Engineer"))

    def test_fill_indeed_apply_limit_aborts(self):
        """Tests that _fill_indeed_apply aborts gracefully if daily limit is detected."""
        mock_page = MagicMock()
        with patch.object(self.platform, "_check_limit", return_value=True):
            result = self.platform._fill_indeed_apply(mock_page, "DevOps Engineer", "Acme Corp")
            self.assertFalse(result)
            self.assertTrue(self.platform.limit_reached)
            self.mock_db.mark_daily_limit_reached.assert_called_with("indeed")


if __name__ == "__main__":
    unittest.main()
