"""
Email Recruitment Lifecycle & Assessment Tracker.
Connects via secure IMAP (SSL) to candidate inbox in READ-ONLY mode.
Features:
1. Scans incoming recruiter emails for HackerRank, Codility, Glider online tests.
2. Identifies interview invitations and technical round calendar invites.
3. Tracks status updates (interview_invite, assessment_received, rejected) in database.
4. Dispatches instant phone push alerts for actionable recruiter messages.
Zero external dependencies (uses standard library imaplib and email).
"""

from datetime import datetime, timedelta, timezone
import email
from email.header import decode_header
import imaplib
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from database import JobDatabase
from utils.logger import logger
from utils.notifier import NotificationManager


class EmailTracker:
    def __init__(
        self,
        config: Dict[str, Any],
        db: JobDatabase,
        notifier: Optional[NotificationManager] = None,
    ):
        self.config = config
        self.db = db
        self.notifier = notifier or NotificationManager(self.config)
        self.email_cfg = self.config.get("email_tracker", {})

        self.enabled = self.email_cfg.get("enabled", False)
        self.imap_server = self.email_cfg.get("imap_server", "imap.gmail.com").strip()
        self.email_user = (
            self.email_cfg.get("email")
            or os.environ.get("RECRUITER_TRACKER_EMAIL")
            or ""
        ).strip()
        self.app_password = (
            self.email_cfg.get("app_password")
            or os.environ.get("RECRUITER_TRACKER_PASSWORD")
            or ""
        ).strip()
        self.folder = self.email_cfg.get("folder", "INBOX").strip()
        self.days_back = self.email_cfg.get("days_back", 7)

    def is_configured(self) -> bool:
        """Returns True if email credentials are provided."""
        return bool(self.enabled and self.email_user and self.app_password)

    @staticmethod
    def decode_mime_header(header_val: Optional[str]) -> str:
        """Decodes RFC 2047 MIME encoded email headers."""
        if not header_val:
            return ""
        decoded_parts = []
        try:
            for part, encoding in decode_header(header_val):
                if isinstance(part, bytes):
                    decoded_parts.append(part.decode(encoding or "utf-8", errors="replace"))
                else:
                    decoded_parts.append(str(part))
            return "".join(decoded_parts)
        except Exception:
            return str(header_val)

    @staticmethod
    def classify_email(subject: str, body: str) -> Optional[str]:
        """
        Classifies incoming email intent:
        - 'assessment_received' (HackerRank, Codility, coding challenges)
        - 'interview_invite' (Technical rounds, screening calls, calendar invites)
        - 'rejected' (Application not selected)
        """
        text = f"{subject} {body}".lower()

        # 1. Assessment / Coding test detection (Highest priority)
        assessment_patterns = [
            r"hackerrank",
            r"codility",
            r"glider\.ai",
            r"mettl",
            r"testgorilla",
            r"codesignal",
            r"online\s*assessment",
            r"coding\s*(test|challenge|assessment)",
            r"technical\s*(test|assessment)",
            r"take[- ]home\s*(test|assignment|project)",
            r"assessment\s*link",
            r"complete\s*the\s*test",
        ]
        for pat in assessment_patterns:
            if re.search(pat, text):
                return "assessment_received"

        # 2. Interview Invitation detection
        interview_patterns = [
            r"invitation\s*to\s*interview",
            r"schedule\s*(an?|your)\s*interview",
            r"interview\s*invitation",
            r"technical\s*discussion",
            r"virtual\s*interview",
            r"round\s*[123]",
            r"screening\s*call",
            r"meet\s*with\s*(the\s*)?team",
            r"calendly\.com",
            r"select\s*a\s*time\s*for\s*(a\s*)?call",
            r"zoom\.us/j/",
            r"teams\.microsoft\.com/l/meetup",
        ]
        for pat in interview_patterns:
            if re.search(pat, text):
                return "interview_invite"

        # 3. Rejection notice detection
        rejection_patterns = [
            r"unfortunately",
            r"not\s*moving\s*forward",
            r"decided\s*to\s*pursue",
            r"other\s*candidates",
            r"not\s*selected",
            r"will\s*keep\s*your\s*resume\s*on\s*file",
            r"decided\s*not\s*to\s*move",
        ]
        for pat in rejection_patterns:
            if re.search(pat, text):
                return "rejected"

        return None

    @staticmethod
    def match_company(
        sender: str, subject: str, body: str, candidate_companies: List[str]
    ) -> Optional[str]:
        """Matches email content to any applied company name."""
        combined = f"{sender} {subject} {body[:500]}".lower()
        for comp in candidate_companies:
            c_clean = comp.strip().lower()
            if len(c_clean) < 3 or c_clean in ("company", "unknown", "confidential"):
                continue
            # Match whole word boundary of company name
            if re.search(rf"\b{re.escape(c_clean)}\b", combined):
                return comp
        return None

    def scan_inbox(self) -> List[Dict[str, Any]]:
        """
        Connects to IMAP server, checks recent emails, and updates application statuses.
        Returns list of matched application updates.
        """
        if not self.is_configured():
            logger.warning(
                "Email tracker is not configured. Enable 'email_tracker' in config.yaml and supply your email and App Password."
            )
            return []

        applied_companies = self.db.get_distinct_applied_companies()
        if not applied_companies:
            logger.info("No applied companies in database to match emails against.")
            return []

        logger.step(f"Connecting to {self.imap_server} (Read-Only) for {self.email_user}...")
        results: List[Dict[str, Any]] = []

        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, 993)
            mail.login(self.email_user, self.app_password)
            mail.select(self.folder, readonly=True)

            since_date = (datetime.now(timezone.utc) - timedelta(days=self.days_back)).strftime("%d-%b-%Y")
            status, search_data = mail.search(None, f'(SINCE "{since_date}")')

            if status != "OK" or not search_data or not search_data[0]:
                logger.info(f"No emails received since {since_date}.")
                mail.logout()
                return []

            email_ids = search_data[0].split()
            logger.info(f"Scanning {len(email_ids)} recent recruiter email(s) from past {self.days_back} days...")

            for eid in reversed(email_ids[-50:]):  # Scan up to the most recent 50 emails
                res, msg_data = mail.fetch(eid, "(RFC822)")
                if res != "OK" or not msg_data:
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = self.decode_mime_header(msg.get("Subject", ""))
                sender = self.decode_mime_header(msg.get("From", ""))

                # Extract plain text content
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disp = str(part.get("Content-Disposition", ""))
                        if content_type == "text/plain" and "attachment" not in content_disp:
                            try:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    body += payload.decode("utf-8", errors="replace")
                            except Exception:
                                pass
                else:
                    try:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="replace")
                    except Exception:
                        pass

                intent = self.classify_email(subject, body)
                if not intent:
                    continue

                matched_company = self.match_company(sender, subject, body, applied_companies)
                if matched_company:
                    rows_updated = self.db.update_application_status(
                        company=matched_company,
                        status=intent,
                        reason=f"Email: {subject[:80]}",
                    )
                    record = {
                        "company": matched_company,
                        "status": intent,
                        "subject": subject,
                        "sender": sender,
                        "rows_updated": rows_updated,
                    }
                    results.append(record)

                    if intent == "assessment_received":
                        logger.success(f"🎯 CODING ASSESSMENT RECEIVED from {matched_company}!")
                        self.notifier.notify_interview_invite(
                            company=matched_company,
                            role="Applied Position",
                            subject=subject,
                            snippet=body[:200],
                        )
                    elif intent == "interview_invite":
                        logger.success(f"🎉 INTERVIEW INVITATION RECEIVED from {matched_company}!")
                        self.notifier.notify_interview_invite(
                            company=matched_company,
                            role="Applied Position",
                            subject=subject,
                            snippet=body[:200],
                        )
                    elif intent == "rejected":
                        logger.info(f"Update: Application at {matched_company} marked as rejected.")

            mail.close()
            mail.logout()

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP Authentication failure: {e}")
        except Exception as e:
            logger.error(f"Error scanning inbox: {e}")

        return results
