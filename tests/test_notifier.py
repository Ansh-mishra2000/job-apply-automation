"""
Unit tests for notification manager (utils/notifier.py).
Tests WhatsApp push alerts (CallMeBot, Twilio, Webhook) dispatch logic with mocks.
"""

import unittest
from unittest.mock import MagicMock, patch

from utils.notifier import NotificationManager


class TestNotificationManager(unittest.TestCase):
    def setUp(self):
        self.config_disabled = {
            "notifications": {
                "enabled": False,
                "whatsapp": {"enabled": False, "phone": "", "api_key": ""},
            }
        }
        self.config_callmebot = {
            "notifications": {
                "enabled": True,
                "whatsapp": {
                    "enabled": True,
                    "phone": "+91 98765 43210",
                    "api_key": "987654",
                },
            }
        }
        self.config_twilio = {
            "notifications": {
                "enabled": True,
                "whatsapp": {
                    "enabled": True,
                    "twilio_account_sid": "AC1234567890abcdef",
                    "twilio_auth_token": "secret_token_123",
                    "twilio_from": "whatsapp:+14155238886",
                    "twilio_to": "whatsapp:+919876543210",
                },
            }
        }
        self.config_webhook = {
            "notifications": {
                "enabled": True,
                "whatsapp": {
                    "enabled": True,
                    "webhook_url": "https://whatsapp.gateway.internal/send",
                },
            }
        }

    def test_disabled_by_default(self):
        """Tests that notifier is inactive when credentials are blank or disabled."""
        mgr = NotificationManager(self.config_disabled)
        self.assertFalse(mgr.is_enabled())
        self.assertFalse(mgr.send_message("Test message"))

    def test_enabled_status(self):
        """Tests that notifier is active when WhatsApp credentials are provided."""
        mgr_bot = NotificationManager(self.config_callmebot)
        self.assertTrue(mgr_bot.is_enabled())
        self.assertEqual(mgr_bot.phone, "919876543210")

        mgr_tw = NotificationManager(self.config_twilio)
        self.assertTrue(mgr_tw.is_enabled())

        mgr_wh = NotificationManager(self.config_webhook)
        self.assertTrue(mgr_wh.is_enabled())

    def test_callmebot_dispatch(self):
        """Tests CallMeBot WhatsApp API request formatting and phone normalization."""
        mgr = NotificationManager(self.config_callmebot)

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b"Message queued successfully"
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok = mgr.send_message("Hello WhatsApp!", title="🔔 *Alert*")
            self.assertTrue(ok)
            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            self.assertIn("api.callmebot.com/whatsapp.php", req.full_url)
            self.assertIn("phone=919876543210", req.full_url)
            self.assertIn("apikey=987654", req.full_url)

    def test_twilio_dispatch(self):
        """Tests Twilio WhatsApp API request formatting with Basic Auth."""
        mgr = NotificationManager(self.config_twilio)

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 201
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok = mgr.send_message("Hello Twilio WhatsApp!", title="🔔 *Alert*")
            self.assertTrue(ok)
            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            self.assertIn("api.twilio.com", req.full_url)
            self.assertIn("Authorization", req.headers)
            self.assertIn("Basic", req.headers["Authorization"])

    def test_webhook_dispatch(self):
        """Tests custom WhatsApp webhook request formatting."""
        mgr = NotificationManager(self.config_webhook)

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok = mgr.send_message("Hello Gateway!", title="🔔 *Alert*")
            self.assertTrue(ok)
            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            self.assertEqual(req.full_url, "https://whatsapp.gateway.internal/send")

    def test_high_level_notifiers(self):
        """Tests application submitted, quota reached, and interview invite WhatsApp alerts."""
        mgr = NotificationManager(self.config_callmebot)

        with patch.object(mgr, "send_message", return_value=True) as mock_send:
            mgr.notify_application_submitted("indeed", "DevOps Engineer", "Google", "https://indeed.com/job/1", 5, 50)
            mock_send.assert_called_once()
            self.assertIn("Applied: DevOps Engineer at Google", mock_send.call_args[1]["title"])

            mock_send.reset_mock()
            mgr.notify_daily_limit_reached("linkedin", 50)
            mock_send.assert_called_once()
            self.assertIn("Quota Reached: Linkedin", mock_send.call_args[1]["title"])

            mock_send.reset_mock()
            mgr.notify_interview_invite("Microsoft", "Senior SRE", "Interview Confirmation", "Please select a slot")
            mock_send.assert_called_once()
            self.assertIn("INTERVIEW / ASSESSMENT INVITE: Microsoft", mock_send.call_args[1]["title"])


if __name__ == "__main__":
    unittest.main()
