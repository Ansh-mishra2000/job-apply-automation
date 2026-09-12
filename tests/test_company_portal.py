"""
Unit tests for Universal Company Career Portal Scanner (Deloitte SuccessFactors, Workday, Generic Portals).
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from playwright.sync_api import sync_playwright
from config_loader import load_config
from database import JobDatabase
from platforms.company_portal import CompanyPortalScanner
from utils.ats_filler import ExternalATSHandler


class TestCompanyPortal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_portal.db"
        cls.db = JobDatabase(str(cls.db_path))

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
            cls.playwright.stop()
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_portal_detection_vs_direct_posting(self):
        """Tests that career portals with search bars are distinguished from direct postings."""
        page = self.browser.new_page()
        try:
            # Case A: Deloitte SuccessFactors Portal Search page
            sf_html = """
            <html>
                <body>
                    <input name="q" class="keywordsearch-q" />
                    <input name="locationsearch" />
                    <input type="submit" class="keywordsearch-button" value="Search Jobs" />
                    <table id="searchresults">
                        <tr class="data-row"><td><a class="jobTitle-link" href="/job/123">DevOps Engineer</a></td></tr>
                    </table>
                </body>
            </html>
            """
            page.set_content(sf_html)
            self.assertTrue(
                CompanyPortalScanner.is_search_portal(page, "https://southasiacareers.deloitte.com/go/Deloitte-India/718244/"),
                "Deloitte search portal page should be recognized as a search portal.",
            )

            # Case B: Direct single job application page (no search inputs)
            job_html = """
            <html>
                <body>
                    <h1>Senior DevOps Engineer</h1>
                    <div id="job-description">We are hiring...</div>
                    <a href="/apply" class="applyButton">Apply now »</a>
                </body>
            </html>
            """
            page.set_content(job_html)
            self.assertFalse(
                CompanyPortalScanner.is_search_portal(page, "https://southasiacareers.deloitte.com/job/Bengaluru-DevOps/123/"),
                "Direct job description page should NOT be detected as a search portal.",
            )
        finally:
            page.close()

    def test_02_company_name_inference(self):
        """Tests inferring company names from various career portal domains."""
        scanner1 = CompanyPortalScanner("https://southasiacareers.deloitte.com/go/Deloitte-India/718244/", config=self.config, db=self.db)
        self.assertEqual(scanner1.company_name, "Deloitte")

        scanner2 = CompanyPortalScanner("https://invesco.wd1.myworkdayjobs.com/IVZ", config=self.config, db=self.db)
        self.assertEqual(scanner2.company_name, "Invesco")

        scanner3 = CompanyPortalScanner("https://careers.google.com/jobs/results", config=self.config, db=self.db, company_override="Google")
        self.assertEqual(scanner3.company_name, "Google")

    def test_03_job_filtering_and_deduplication(self):
        """Tests relevance matching, location check, and database deduplication."""
        scanner = CompanyPortalScanner("https://southasiacareers.deloitte.com/go/Deloitte-India/718244/", config=self.config, db=self.db)

        # Seed an applied job in DB
        self.db.record_application(
            job_id="99999",
            platform="direct",
            title="Senior Consultant | DevOps",
            company="Deloitte",
            job_url="https://southasiacareers.deloitte.com/job/99999/",
            status="applied",
        )

        mock_jobs = [
            {
                "id": "59416044",
                "title": "Senior Consultant | DevOps | Bengaluru",
                "company": "Deloitte",
                "location": "Bengaluru, India",
                "posted_date": "Recently",
                "url": "https://southasiacareers.deloitte.com/job/59416044/",
            },
            {
                "id": "99999",
                "title": "Senior Consultant | DevOps",
                "company": "Deloitte",
                "location": "Bengaluru, India",
                "posted_date": "Recently",
                "url": "https://southasiacareers.deloitte.com/job/99999/",
            },
            {
                "id": "88888",
                "title": "DevOps Engineer - SAP Infrastructure",
                "company": "Deloitte",
                "location": "Mumbai, India",
                "posted_date": "Recently",
                "url": "https://southasiacareers.deloitte.com/job/88888/",
            },
            {
                "id": "77777",
                "title": "DevOps Engineer",
                "company": "Deloitte",
                "location": "London, UK",
                "posted_date": "Recently",
                "url": "https://southasiacareers.deloitte.com/job/77777/",
            },
        ]

        filtered = scanner.filter_jobs(mock_jobs, keywords=["DevOps Engineer"], target_location="India")
        statuses = {j["id"]: j["status"] for j in filtered}

        self.assertEqual(statuses["59416044"], "Eligible")
        self.assertEqual(statuses["99999"], "Already Applied")
        self.assertEqual(statuses["88888"], "Excluded Skill")
        self.assertEqual(statuses["77777"], "Location Mismatch (London, UK)")

    def test_04_non_application_page_rejected_by_ats_filler(self):
        """Verifies that non-application pages (e.g. Terms / What to know) return False without DB recording."""
        page = self.browser.new_page()
        try:
            terms_html = """
            <html>
                <body>
                    <h1>What to know before you apply</h1>
                    <p>Terms and conditions for applying to Deloitte...</p>
                    <a href="/jobs">Click here to view the jobs</a>
                </body>
            </html>
            """
            page.set_content(terms_html)

            ats = ExternalATSHandler(self.config)
            dummy_resume = Path(self.temp_dir.name) / "cv.pdf"
            dummy_resume.write_text("Dummy CV")

            success = ats.apply_generic(page, "DevOps Engineer", "Deloitte", dummy_resume)
            self.assertFalse(success, "apply_generic should return False when no application form or fields exist.")
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
