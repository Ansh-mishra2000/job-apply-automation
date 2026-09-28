"""
Notification Manager for real-time mobile push alerts.
Supports:
1. Telegram Bot API (Instant push notifications to phone)
2. Discord Webhook (Channel alerts with rich embeds)
Built with Python standard library urllib.request (zero external dependencies).
"""

from datetime import datetime, timezone
import json
import os
from typing import Any, Dict, Optional
import urllib.error
import urllib.request

from utils.logger import logger


class NotificationManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.notif_cfg = self.config.get("notifications", {})

        # Telegram configuration
        self.tg_cfg = self.notif_cfg.get("telegram", {})
        self.tg_enabled = self.tg_cfg.get("enabled", False)
        self.tg_token = (
            self.tg_cfg.get("bot_token")
            or os.environ.get("TELEGRAM_BOT_TOKEN")
            or ""
        ).strip()
        self.tg_chat_id = (
            self.tg_cfg.get("chat_id")
            or os.environ.get("TELEGRAM_CHAT_ID")
            or ""
        ).strip()

        # Discord configuration
        self.dc_cfg = self.notif_cfg.get("discord", {})
        self.dc_enabled = self.dc_cfg.get("enabled", False)
        self.dc_webhook_url = (
            self.dc_cfg.get("webhook_url")
            or os.environ.get("DISCORD_WEBHOOK_URL")
            or ""
        ).strip()

    def is_enabled(self) -> bool:
        """Returns True if at least one notification channel is active."""
        return bool((self.tg_enabled and self.tg_token and self.tg_chat_id) or (self.dc_enabled and self.dc_webhook_url))

    def send_message(self, text: str, title: Optional[str] = None) -> bool:
        """Dispatches notification to all enabled channels."""
        if not self.is_enabled():
            return False

        tg_ok = True
        dc_ok = True

        if self.tg_enabled and self.tg_token and self.tg_chat_id:
            tg_ok = self._send_telegram(text, title)

        if self.dc_enabled and self.dc_webhook_url:
            dc_ok = self._send_discord(text, title)

        return tg_ok and dc_ok

    def _send_telegram(self, text: str, title: Optional[str] = None) -> bool:
        """Sends message via Telegram Bot API."""
        msg = f"<b>{title}</b>\n\n{text}" if title else text
        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        payload = {
            "chat_id": self.tg_chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    logger.debug("Telegram alert sent successfully.")
                    return True
        except Exception as e:
            logger.warning(f"Failed to send Telegram notification: {e}")
        return False

    def _send_discord(self, text: str, title: Optional[str] = None) -> bool:
        """Sends rich embed via Discord Webhook."""
        payload = {
            "embeds": [
                {
                    "title": title or "Automated Recruitment Engine Alert",
                    "description": text,
                    "color": 3447003,  # Blue
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "footer": {"text": "Auto Apply Bot"},
                }
            ]
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.dc_webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 204):
                    logger.debug("Discord webhook alert sent successfully.")
                    return True
        except Exception as e:
            logger.warning(f"Failed to send Discord webhook: {e}")
        return False

    # High-level event notifiers
    def notify_application_submitted(
        self,
        platform: str,
        job_title: str,
        company: str,
        job_url: str = "",
        today_count: int = 1,
        max_daily: int = 50,
    ):
        """Notifies user when an application is successfully submitted."""
        title = f"🚀 Applied: {job_title} at {company}"
        text = (
            f"• <b>Platform:</b> {platform.capitalize()}\n"
            f"• <b>Company:</b> {company}\n"
            f"• <b>Role:</b> {job_title}\n"
            f"• <b>Today's Progress:</b> {today_count}/{max_daily}\n"
        )
        if job_url:
            text += f"• <b>Link:</b> {job_url}\n"
        self.send_message(text, title=title)

    def notify_daily_limit_reached(self, platform: str, total_applied: int):
        """Notifies when a platform's daily quota has been fulfilled."""
        title = f"🛑 Quota Reached: {platform.capitalize()}"
        text = (
            f"Daily quota for <b>{platform.capitalize()}</b> has been reached!\n"
            f"• Total jobs applied today: <b>{total_applied}</b>\n"
            f"• Status: Session safely closed until tomorrow."
        )
        self.send_message(text, title=title)

    def notify_interview_invite(self, company: str, role: str, subject: str, snippet: str = ""):
        """High-priority phone push when an interview invitation or assessment is detected in email."""
        title = f"🎉 INTERVIEW / ASSESSMENT INVITE: {company}"
        text = (
            f"A new recruitment email was received!\n"
            f"• <b>Company:</b> {company}\n"
            f"• <b>Role:</b> {role}\n"
            f"• <b>Subject:</b> {subject}\n"
        )
        if snippet:
            text += f"\n<i>\"{snippet[:200]}...\"</i>"
        self.send_message(text, title=title)
