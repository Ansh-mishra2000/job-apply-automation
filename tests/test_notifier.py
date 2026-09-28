"""
Unit tests for notification manager (utils/notifier.py).
Tests Telegram Bot API and Discord Webhook dispatch logic with mocks.
"""

import unittest
from unittest.mock import MagicMock, patch

from utils.notifier import NotificationManager


class TestNotificationManager(unittest.TestCase):
    def setUp(self):
        self.config_disabled = {
            "notifications": {
                "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
                "discord": {"enabled": False, "webhook_url": ""},
            }
        }
        self.config_enabled = {
            "notifications": {
                "telegram": {
                    "enabled": True,
                    "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
                    "chat_id": "987654321",
                },
                "discord": {
                    "enabled": True,
                    "webhook_url": "https://discord.com/api/webhooks/123/xyz",
                },
            }
        }

    def test_disabled_by_default(self):
        """Tests that notifier is inactive when tokens/urls are blank."""
        mgr = NotificationManager(self.config_disabled)
        self.assertFalse(mgr.is_enabled())
        self.assertFalse(mgr.send_message("Test message"))

    def test_enabled_status(self):
        """Tests that notifier is active when credentials are provided."""
        mgr = NotificationManager(self.config_enabled)
        self.assertTrue(mgr.is_enabled())

    def test_telegram_dispatch(self):
        """Tests Telegram API request formatting."""
        mgr = NotificationManager(self.config_enabled)

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok = mgr._send_telegram("Hello Telegram!", title="Alert")
            self.assertTrue(ok)
            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            self.assertIn("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/sendMessage", req.full_url)

    def test_discord_dispatch(self):
        """Tests Discord Webhook request formatting."""
        mgr = NotificationManager(self.config_enabled)

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 204
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok = mgr._send_discord("Hello Discord!", title="Webhook Alert")
            self.assertTrue(ok)
            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            self.assertEqual(req.full_url, "https://discord.com/api/webhooks/123/xyz")

    def test_high_level_notifiers(self):
        """Tests application submitted and limit reached high-level helpers."""
        mgr = NotificationManager(self.config_enabled)

        with patch.object(mgr, "send_message", return_value=True) as mock_send:
            mgr.notify_application_submitted("indeed", "DevOps Engineer", "Google", "https://indeed.com/job/1", 5, 50)
            mock_send.assert_called_once()
            self.assertIn("Applied: DevOps Engineer at Google", mock_send.call_args[1]["title"])

            mock_send.reset_mock()
            mgr.notify_daily_limit_reached("linkedin", 50)
            mock_send.assert_called_once()
            self.assertIn("Quota Reached: Linkedin", mock_send.call_args[1]["title"])


if __name__ == "__main__":
    unittest.main()
