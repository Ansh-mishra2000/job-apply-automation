"""
Unit tests for platform expansion modules (platforms/instahyre.py and platforms/wellfound.py).
"""

import unittest
from unittest.mock import MagicMock, patch

from database import JobDatabase
from platforms.instahyre import InstahyrePlatform
from platforms.wellfound import WellfoundPlatform


class TestPlatformExpansion(unittest.TestCase):
    def setUp(self):
        self.config = {
            "search": {
                "keywords": ["DevOps Engineer", "Cloud Engineer"],
                "locations": ["India", "Remote"],
            },
            "platforms": {
                "instahyre": {"enabled": True, "max_daily_applications": 30},
                "wellfound": {"enabled": True, "max_daily_applications": 25},
            },
            "profile": {
                "full_name": "Ansh Mishra",
                "total_experience_years": 2,
                "current_ctc": "600000",
                "expected_ctc": "1000000",
                "notice_period_days": 30,
            },
        }
        self.mock_db = MagicMock(spec=JobDatabase)

    def test_instahyre_initialization(self):
        """Tests InstahyrePlatform initialization and quota configuration."""
        platform = InstahyrePlatform(self.config, self.mock_db, headless=True)
        self.assertEqual(platform.name, "instahyre")
        self.assertEqual(platform.max_daily, 30)

    def test_wellfound_initialization(self):
        """Tests WellfoundPlatform initialization and quota configuration."""
        platform = WellfoundPlatform(self.config, self.mock_db, headless=True)
        self.assertEqual(platform.name, "wellfound")
        self.assertEqual(platform.max_daily, 25)

    def test_instahyre_quota_exhausted(self):
        """Tests that Instahyre halts if today's count reaches daily quota."""
        self.mock_db.get_daily_applied_count.return_value = 30
        platform = InstahyrePlatform(self.config, self.mock_db, headless=True)

        applied = platform.run()
        self.assertEqual(applied, 0)
        self.assertTrue(platform.limit_reached)

    def test_wellfound_quota_exhausted(self):
        """Tests that Wellfound halts if today's count reaches daily quota."""
        self.mock_db.get_daily_applied_count.return_value = 25
        platform = WellfoundPlatform(self.config, self.mock_db, headless=True)

        applied = platform.run()
        self.assertEqual(applied, 0)
        self.assertTrue(platform.limit_reached)


if __name__ == "__main__":
    unittest.main()
