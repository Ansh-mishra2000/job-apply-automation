"""
Unit tests for email recruitment lifecycle tracker (utils/email_tracker.py).
"""

import unittest
from unittest.mock import MagicMock, patch

from database import JobDatabase
from utils.email_tracker import EmailTracker


class TestEmailTracker(unittest.TestCase):
    def setUp(self):
        self.config_disabled = {
            "email_tracker": {
                "enabled": False,
                "email": "",
                "app_password": "",
            }
        }
        self.config_enabled = {
            "email_tracker": {
                "enabled": True,
                "imap_server": "imap.gmail.com",
                "email": "candidate@example.com",
                "app_password": "abcd efgh ijkl mnop",
                "days_back": 7,
            }
        }
        self.mock_db = MagicMock(spec=JobDatabase)
        self.mock_db.get_distinct_applied_companies.return_value = ["Stripe", "Airbnb", "Google", "Deloitte"]
        self.tracker = EmailTracker(self.config_enabled, self.mock_db)

    def test_classify_assessment(self):
        """Tests classification of HackerRank and coding challenges."""
        subject = "Invitation to complete your HackerRank assessment for Stripe"
        body = "Please click here to start your technical test within 48 hours."
        intent = EmailTracker.classify_email(subject, body)
        self.assertEqual(intent, "assessment_received")

        # Codility test
        intent_codility = EmailTracker.classify_email("Your Codility Test Link", "Online coding test details.")
        self.assertEqual(intent_codility, "assessment_received")

    def test_classify_interview_invite(self):
        """Tests classification of interview invitations and calendar links."""
        subject = "Airbnb: Invitation to Interview - DevOps Engineer"
        body = "We would love to schedule a technical discussion via Calendly: https://calendly.com/airbnb-team"
        intent = EmailTracker.classify_email(subject, body)
        self.assertEqual(intent, "interview_invite")

    def test_classify_rejection(self):
        """Tests classification of rejection notices."""
        subject = "Your application to Google"
        body = "Thank you for your interest. Unfortunately, after careful review, we have decided to pursue other candidates."
        intent = EmailTracker.classify_email(subject, body)
        self.assertEqual(intent, "rejected")

    def test_match_company(self):
        """Tests matching company names from candidate companies list."""
        companies = ["Stripe", "Airbnb", "Google"]

        # Match in subject
        comp = EmailTracker.match_company("jobs@stripe.com", "Your application at Stripe", "", companies)
        self.assertEqual(comp, "Stripe")

        # Match in body
        comp_body = EmailTracker.match_company("recruiter@workday.com", "Job Update", "Welcome to Airbnb recruitment!", companies)
        self.assertEqual(comp_body, "Airbnb")

        # No match
        comp_none = EmailTracker.match_company("newsletter@medium.com", "Daily Digest", "Top 10 tech trends", companies)
        self.assertIsNone(comp_none)

    def test_decode_mime_header(self):
        """Tests decoding of plain text and mime-encoded headers."""
        plain = EmailTracker.decode_mime_header("Simple Subject")
        self.assertEqual(plain, "Simple Subject")

        empty = EmailTracker.decode_mime_header(None)
        self.assertEqual(empty, "")


if __name__ == "__main__":
    unittest.main()
