"""
Notification Manager for real-time WhatsApp mobile push alerts.
Supports:
1. CallMeBot WhatsApp API (Free, instant personal WhatsApp bot, zero sign-up required)
2. Twilio WhatsApp API (Official Twilio Programmable Messaging)
3. Custom WhatsApp Webhook / Gateway (Evolution API, Green-API, UltraMsg, etc.)

Built with Python standard library (urllib.request & urllib.parse) with zero external pip dependencies.
"""

from datetime import datetime, timezone
import base64
import json
import os
import re
from typing import Any, Dict, Optional
import urllib.error
import urllib.parse
import urllib.request

from utils.logger import logger


class NotificationManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.notif_cfg = self.config.get("notifications", {})
        self.enabled = self.notif_cfg.get("enabled", False)

        # WhatsApp configuration
        self.wa_cfg = self.notif_cfg.get("whatsapp", {})
        self.wa_enabled = self.wa_cfg.get("enabled", False)

        # CallMeBot configuration (Default / Free)
        raw_phone = (
            self.wa_cfg.get("phone")
            or os.environ.get("WHATSAPP_PHONE")
            or self.config.get("profile", {}).get("phone", "")
        )
        # Normalize phone: keep only numeric digits
        self.phone = re.sub(r"[^\d]", "", str(raw_phone))

        self.api_key = (
            self.wa_cfg.get("api_key")
            or os.environ.get("WHATSAPP_API_KEY")
            or os.environ.get("CALLMEBOT_API_KEY")
            or ""
        ).strip()

        # Twilio WhatsApp configuration (Optional)
        self.twilio_sid = (
            self.wa_cfg.get("twilio_account_sid")
            or os.environ.get("TWILIO_ACCOUNT_SID")
            or ""
        ).strip()
        self.twilio_token = (
            self.wa_cfg.get("twilio_auth_token")
            or os.environ.get("TWILIO_AUTH_TOKEN")
            or ""
        ).strip()
        self.twilio_from = (
            self.wa_cfg.get("twilio_from")
            or os.environ.get("TWILIO_FROM")
            or "whatsapp:+14155238886"
        ).strip()
        self.twilio_to = (
            self.wa_cfg.get("twilio_to")
            or os.environ.get("TWILIO_TO")
            or (f"whatsapp:+{self.phone}" if self.phone else "")
        ).strip()

        # Custom Webhook / Gateway (Optional)
        self.webhook_url = (
            self.wa_cfg.get("webhook_url")
            or os.environ.get("WHATSAPP_WEBHOOK_URL")
            or ""
        ).strip()

    def is_enabled(self) -> bool:
        """Returns True if WhatsApp notifications are enabled and configured."""
        if not self.enabled or not self.wa_enabled:
            return False
        has_callmebot = bool(self.phone and self.api_key)
        has_twilio = bool(self.twilio_sid and self.twilio_token and self.twilio_to)
        has_webhook = bool(self.webhook_url)
        return has_callmebot or has_twilio or has_webhook

    def send_message(self, text: str, title: Optional[str] = None) -> bool:
        """Dispatches notification to the configured WhatsApp service."""
        if not self.is_enabled():
            return False

        # Format WhatsApp message with title
        msg = f"{title}\n\n{text}" if title else text

        # Prioritize provider: Twilio > CallMeBot > Generic Webhook
        if self.twilio_sid and self.twilio_token and self.twilio_to:
            return self._send_twilio(msg)
        elif self.webhook_url:
            return self._send_webhook(msg)
        elif self.phone and self.api_key:
            return self._send_callmebot(msg)

        return False

    def _send_callmebot(self, message: str) -> bool:
        """Sends WhatsApp message via free CallMeBot API."""
        try:
            params = urllib.parse.urlencode({
                "phone": self.phone,
                "text": message,
                "apikey": self.api_key,
            })
            url = f"https://api.callmebot.com/whatsapp.php?{params}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "JobApplyAutomation/1.0"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                status = resp.status
                body = resp.read().decode("utf-8", errors="ignore")
                if status == 200:
                    logger.debug(f"WhatsApp alert sent successfully via CallMeBot. Response: {body[:100]}")
                    return True
                else:
                    logger.warning(f"CallMeBot WhatsApp returned status {status}: {body[:100]}")
        except Exception as e:
            logger.warning(f"Failed to send WhatsApp notification via CallMeBot: {e}")
        return False

    def _send_twilio(self, message: str) -> bool:
        """Sends WhatsApp message via Twilio Programmable Messaging API."""
        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_sid}/Messages.json"
            from_num = self.twilio_from if self.twilio_from.startswith("whatsapp:") else f"whatsapp:{self.twilio_from}"
            to_num = self.twilio_to if self.twilio_to.startswith("whatsapp:") else f"whatsapp:{self.twilio_to}"

            payload = urllib.parse.urlencode({
                "From": from_num,
                "To": to_num,
                "Body": message,
            }).encode("utf-8")

            # Basic HTTP Auth
            auth_str = f"{self.twilio_sid}:{self.twilio_token}"
            auth_b64 = base64.b64encode(auth_str.encode("utf-8")).decode("ascii")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {auth_b64}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status in (200, 201):
                    logger.debug("WhatsApp alert sent successfully via Twilio.")
                    return True
                else:
                    logger.warning(f"Twilio WhatsApp returned status {resp.status}")
        except Exception as e:
            logger.warning(f"Failed to send WhatsApp notification via Twilio: {e}")
        return False

    def _send_webhook(self, message: str) -> bool:
        """Sends WhatsApp message to a custom gateway/webhook."""
        try:
            payload = json.dumps({
                "phone": self.phone,
                "message": message,
                "text": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }).encode("utf-8")

            req = urllib.request.Request(
                self.webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status in (200, 201, 202, 204):
                    logger.debug("WhatsApp alert sent successfully via custom webhook.")
                    return True
        except Exception as e:
            logger.warning(f"Failed to send WhatsApp notification via webhook: {e}")
        return False

    # High-level event notifiers formatted for WhatsApp
    def notify_application_submitted(
        self,
        platform: str,
        job_title: str,
        company: str,
        job_url: str = "",
        today_count: int = 1,
        max_daily: int = 50,
    ):
        """Notifies user via WhatsApp when an application is successfully submitted."""
        title = f"🚀 *Applied: {job_title} at {company}*"
        text = (
            f"• *Platform:* {platform.capitalize()}\n"
            f"• *Company:* {company}\n"
            f"• *Role:* {job_title}\n"
            f"• *Today's Progress:* {today_count}/{max_daily}\n"
        )
        if job_url:
            text += f"• *Link:* {job_url}\n"
        self.send_message(text, title=title)

    def notify_daily_limit_reached(self, platform: str, total_applied: int):
        """Notifies user via WhatsApp when a platform's daily quota has been fulfilled."""
        title = f"🛑 *Quota Reached: {platform.capitalize()}*"
        text = (
            f"Daily quota for *{platform.capitalize()}* has been reached!\n"
            f"• Total jobs applied today: *{total_applied}*\n"
            f"• Status: Session safely closed until tomorrow."
        )
        self.send_message(text, title=title)

    def notify_interview_invite(self, company: str, role: str, subject: str, snippet: str = ""):
        """High-priority WhatsApp alert when an interview invitation or assessment is detected in email."""
        title = f"🎉 *INTERVIEW / ASSESSMENT INVITE: {company}*"
        text = (
            f"A new recruitment email was received!\n"
            f"• *Company:* {company}\n"
            f"• *Role:* {role}\n"
            f"• *Subject:* {subject}\n"
        )
        if snippet:
            text += f"\n_\"{snippet[:200]}...\"_"
        self.send_message(text, title=title)
