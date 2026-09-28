"""
Unit tests for LinkedIn direct recruiter outreach engine (platforms/linkedin_outreach.py).
"""

import unittest
from unittest.mock import MagicMock, patch

from database import JobDatabase
from platforms.linkedin_outreach import LinkedInOutreach


class TestLinkedInOutreach(unittest.TestCase):
    def setUp(self):
        self.config = {
            "ai": {"enabled": False},
            "profile": {
                "full_name": "Ansh Mishra",
                "total_experience_years": 2,
            },
        }
        self.mock_db = MagicMock(spec=JobDatabase)
        self.outreach = LinkedInOutreach(self.config, self.mock_db, headless=True)

    def test_draft_outreach_note_fallback(self):
        """Tests that generated connection note is within 300 characters and mentions role/company."""
        note = self.outreach.draft_outreach_note(
            recruiter_name="Sarah Jenkins",
            job_title="DevOps Engineer",
            company="Stripe",
        )
        self.assertLessEqual(len(note), 300)
        self.assertIn("Sarah", note)
        self.assertIn("DevOps Engineer", note)
        self.assertIn("Stripe", note)

    def test_find_job_poster_present(self):
        """Tests parsing of recruiter card DOM structure."""
        mock_page = MagicMock()
        mock_card = MagicMock()
        mock_card.count.return_value = 1
        mock_card.is_visible.return_value = True

        mock_name = MagicMock()
        mock_name.count.return_value = 1
        mock_name.inner_text.return_value = "Priya Sharma"
        mock_name.first = mock_name

        mock_link = MagicMock()
        mock_link.count.return_value = 1
        mock_link.get_attribute.return_value = "https://www.linkedin.com/in/priyasharma/?trackingId=123"
        mock_link.first = mock_link

        mock_headline = MagicMock()
        mock_headline.count.return_value = 1
        mock_headline.inner_text.return_value = "Technical Talent Partner at Razorpay"
        mock_headline.first = mock_headline

        mock_card.locator.side_effect = lambda sel: (
            mock_name if "name" in sel or "strong" in sel
            else mock_link if "href" in sel
            else mock_headline
        )
        mock_page.locator.return_value.first = mock_card

        poster = self.outreach.find_job_poster(mock_page)
        self.assertIsNotNone(poster)
        self.assertEqual(poster["name"], "Priya Sharma")
        self.assertEqual(poster["profile_url"], "https://www.linkedin.com/in/priyasharma/")


if __name__ == "__main__":
    unittest.main()
