"""
LinkedIn Direct Recruiter Outreach Engine.
Detects hiring managers and talent recruiters attached to job postings,
generates personalized connection pitch notes, and manages outreach.
"""

from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
from playwright.sync_api import Locator, Page

from database import JobDatabase
from utils.ai_agent import AIAgent
from utils.browser import BrowserManager
from utils.logger import logger


class LinkedInOutreach:
    def __init__(self, config: Dict[str, Any], db: JobDatabase, headless: bool = False):
        self.config = config
        self.db = db
        self.headless = headless
        self.ai_agent = AIAgent(self.config)
        self.profile = self.config.get("profile", {})

    def find_job_poster(self, page: Page) -> Optional[Dict[str, str]]:
        """
        Inspects the active LinkedIn job details pane to detect if the recruiter / hiring manager is visible.
        Returns dict with recruiter 'name', 'headline', 'profile_url' or None.
        """
        poster_selectors = [
            ".hirer-card__hirer-information",
            ".jobs-poster",
            "div:has(> h3:has-text('Meet the hiring team'))",
            "div.job-details-jobs-unified-top-card__hiring-team",
        ]

        for sel in poster_selectors:
            try:
                card = page.locator(sel).first
                if card.count() > 0 and card.is_visible():
                    name_elem = card.locator("a strong, .jobs-poster__name, h3, a[href*='/in/']").first
                    name = name_elem.inner_text().strip() if name_elem.count() > 0 else ""
                    if not name:
                        continue

                    # Extract profile link
                    link_elem = card.locator("a[href*='/in/']").first
                    profile_url = link_elem.get_attribute("href") if link_elem.count() > 0 else ""
                    if profile_url and "?" in profile_url:
                        profile_url = profile_url.split("?")[0]

                    headline_elem = card.locator(".hirer-card__hirer-job-title, .text-body-small").first
                    headline = headline_elem.inner_text().strip() if headline_elem.count() > 0 else "Recruiter"

                    return {
                        "name": name,
                        "headline": headline,
                        "profile_url": profile_url or "",
                    }
            except Exception:
                continue

        return None

    def draft_outreach_note(self, recruiter_name: str, job_title: str, company: str) -> str:
        """
        Generates a concise, high-conversion LinkedIn connection note (< 300 characters limit).
        Uses Gemini AI if enabled, otherwise uses proven high-response template.
        """
        first_name = recruiter_name.split()[0] if recruiter_name else "there"
        clean_title = job_title if job_title and "unknown" not in job_title.lower() else "DevOps Engineer"
        clean_company = company if company and "unknown" not in company.lower() else "your team"

        if self.ai_agent.is_available():
            prompt = (
                f"Candidate Name: {self.profile.get('full_name', 'Ansh Mishra')}\n"
                f"Experience: 2 yrs DevOps / Cloud (AWS, Kubernetes, CI/CD, Terraform)\n"
                f"Recruiter: {first_name} at {clean_company}\n"
                f"Position: {clean_title}\n\n"
                "Write a personalized, polite LinkedIn connection request note to the recruiter. "
                "CRITICAL REQUIREMENT: Must be STRICTLY under 280 characters so it fits LinkedIn's note limit. "
                "Include a warm greeting, mention the role, highlight core tools, and express enthusiasm to connect. "
                "Output ONLY the note text:"
            )
            ai_note = self.ai_agent._call_gemini_api(prompt)
            if ai_note and len(ai_note.strip()) <= 300:
                return ai_note.strip().strip('"')

        # Proven high-response fallback template (< 300 chars)
        note = (
            f"Hi {first_name}, I saw the {clean_title} role at {clean_company} and would love to connect! "
            f"With 2 yrs in DevOps (AWS, Kubernetes, Docker, Terraform & CI/CD), I'd be excited to support your infra goals. Best, Ansh"
        )
        return note[:295]

    def send_outreach_request(self, page: Page, profile_url: str, note: str) -> bool:
        """
        Navigates to recruiter profile and sends a connection invite with personalized note.
        """
        if not profile_url:
            return False

        try:
            logger.step(f"Navigating to recruiter profile: {profile_url}...")
            page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2.5)

            # Look for Connect button
            connect_btn = page.locator("button:has-text('Connect'), button[aria-label*='Invite']:has-text('Connect')").first
            if connect_btn.count() == 0 or not connect_btn.is_visible():
                # May be hidden in "More" actions dropdown
                more_btn = page.locator("button:has-text('More'), button[aria-label*='More actions']").first
                if more_btn.count() > 0 and more_btn.is_visible():
                    more_btn.click()
                    time.sleep(1.0)
                    connect_btn = page.locator("div.artdeco-dropdown__content button:has-text('Connect')").first

            if connect_btn.count() == 0 or not connect_btn.is_visible():
                logger.info("Recruiter profile does not have an active Connect button (or already connected).")
                return False

            connect_btn.click()
            time.sleep(1.5)

            # Add a note modal
            add_note_btn = page.locator("button:has-text('Add a note')").first
            if add_note_btn.count() > 0 and add_note_btn.is_visible():
                add_note_btn.click()
                time.sleep(1.0)

                note_area = page.locator("textarea[name='message'], #custom-message").first
                if note_area.count() > 0 and note_area.is_visible():
                    BrowserManager.human_type(note_area, note)
                    time.sleep(1.0)

                    send_btn = page.locator("button:has-text('Send'), button[aria-label='Send invitation']").first
                    if send_btn.count() > 0 and send_btn.is_visible():
                        send_btn.click()
                        logger.success("Personalized recruiter connection note delivered successfully!")
                        time.sleep(2.0)
                        return True

            # If no note modal was prompted, dismiss or send without note
            send_without = page.locator("button:has-text('Send without a note')").first
            if send_without.count() > 0 and send_without.is_visible():
                send_without.click()
                return True

        except Exception as e:
            logger.warning(f"Could not complete recruiter outreach: {e}")

        return False
