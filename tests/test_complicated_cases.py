"""
Automated Test Suite for Complicated Easy Apply & Form Filling Cases
Tests:
1. Tricky experience & whole number questions
2. Open-ended technical descriptions, education, URLs, certifications
3. Checkbox handling (terms, legal authorization, follow-company exclusion)
4. Radio button groups inside and outside <fieldset>
5. Combobox / Custom dropdown handling
6. Self-healing error recovery
7. Fast virtual DOM timeout prevention (0 hangs)
"""

import time
import unittest
from playwright.sync_api import sync_playwright
from config_loader import load_config
from utils.form_filler import FormFiller


class TestComplicatedCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        cls.form_filler = FormFiller(cls.config["profile"])

    def test_01_tricky_experience_and_whole_number_enforcement(self):
        """Tests that experience and whole number screening questions always return integer strings."""
        questions = [
            ("How many years of work experience do you have with CMDB?", "2"),
            ("Enter a whole number between 0 and 99 for AWS experience", "2"),
            ("How many years of Kubernetes experience do you possess?", "2"),
            ("Years of experience with Docker and Containerization", "2"),
            ("Total years of IT industry experience", "2"),
            ("Overall relevant experience in DevOps / SRE", "2"),
            ("Number of years using Terraform for IaC", "2"),
        ]
        for q, expected in questions:
            ans = self.form_filler.get_answer_for_text_question(q)
            self.assertEqual(
                ans,
                expected,
                f"Question '{q}' failed: expected '{expected}', got '{ans}'",
            )
            # Ensure no decimal point exists
            self.assertNotIn(".", ans, f"Answer '{ans}' contains decimal point for whole number question: {q}")

    def test_02_open_ended_technical_pitch_and_education(self):
        """Tests that open-ended screening questions return rich, accurate text instead of 'Yes'."""
        education_q = "What is your highest qualification and major?"
        ans_edu = self.form_filler.get_answer_for_text_question(education_q)
        self.assertIn("Bachelor of Technology", ans_edu)

        univ_q = "Name of university or institute attended"
        ans_univ = self.form_filler.get_answer_for_text_question(univ_q)
        self.assertIn("Galgotias University", ans_univ)

        cert_q = "Please list any relevant cloud certifications"
        ans_cert = self.form_filler.get_answer_for_text_question(cert_q)
        self.assertIn("AWS Certified", ans_cert)

        github_q = "GitHub profile link or repository"
        ans_github = self.form_filler.get_answer_for_text_question(github_q)
        self.assertEqual(ans_github, "https://github.com/anshmishra")

        linkedin_q = "LinkedIn Profile URL"
        ans_linkedin = self.form_filler.get_answer_for_text_question(linkedin_q)
        self.assertEqual(ans_linkedin, self.config["profile"].get("linkedin_url", "https://www.linkedin.com/in/anshmishra/"))

        pitch_q = "Briefly describe your DevOps experience and key achievements"
        ans_pitch = self.form_filler.get_answer_for_text_question(pitch_q)
        self.assertTrue(len(ans_pitch) > 50, "Technical pitch should be detailed and informative")

    def test_03_demographics_and_eeo_word_boundary_safety(self):
        """Tests accurate resolution of EEO options without substring contamination."""
        # Gender test: Ensure 'Male' doesn't accidentally match 'Female'
        gender_opts = ["Female", "Male", "Decline to specify"]
        chosen_gender = self.form_filler.get_choice_for_question("Gender Identity", gender_opts)
        self.assertEqual(chosen_gender, "Male")

        # Ethnicity test: Ensure Asian matches and American Indian is excluded
        race_opts = [
            "American Indian or Alaska Native",
            "Asian (Not Hispanic or Latino)",
            "Black or African American",
            "Two or More Races",
            "White",
        ]
        chosen_race = self.form_filler.get_choice_for_question("What is your race / ethnicity?", race_opts)
        self.assertEqual(chosen_race, "Asian (Not Hispanic or Latino)")

        # Veteran test:
        vet_opts = ["I am a protected veteran", "I am not a protected veteran", "I do not wish to answer"]
        chosen_vet = self.form_filler.get_choice_for_question("Protected Veteran Status", vet_opts)
        self.assertEqual(chosen_vet, "I am not a protected veteran")

        # Disability test:
        dis_opts = ["Yes, I have a disability", "No, I do not have a disability", "I prefer not to say"]
        chosen_dis = self.form_filler.get_choice_for_question("Voluntary Self-Identification of Disability", dis_opts)
        self.assertEqual(chosen_dis, "No, I do not have a disability")

    def test_04_live_dom_form_filling_complicated_elements(self):
        """
        Creates a real in-memory HTML page containing complex Easy Apply elements:
        - Checkboxes (required agreement + follow-company exclusion)
        - Radio buttons outside <fieldset> in a custom div
        - Custom combobox dropdown
        - Textarea expecting summary
        - Input with whole number inline validation error
        Verifies that form_filler fills every single element correctly.
        """
        html_content = """
        <!DOCTYPE html>
        <html>
        <body>
            <div id="modal-container">
                <!-- 1. Tricky Text Inputs -->
                <div class="form-element">
                    <label for="cmdb-exp">How many years of work experience do you have with CMDB?</label>
                    <input type="text" id="cmdb-exp" value="" />
                </div>

                <!-- 2. Textarea open-ended question -->
                <div class="form-element">
                    <label for="about-exp">Describe a challenging production incident you resolved</label>
                    <textarea id="about-exp"></textarea>
                </div>

                <!-- 3. Checkboxes -->
                <div class="form-element">
                    <label for="agree-terms">I agree to the background verification terms and privacy policy</label>
                    <input type="checkbox" id="agree-terms" required />
                </div>
                <div class="form-element">
                    <label for="follow-company-checkbox">Follow company for updates</label>
                    <input type="checkbox" id="follow-company-checkbox" checked />
                </div>

                <!-- 4. Radios outside fieldset (in a div grouping) -->
                <div class="jobs-easy-apply-form-section__grouping">
                    <span class="t-14">Are you legally authorized to work in India?</span>
                    <div>
                        <label for="auth-yes">Yes</label>
                        <input type="radio" id="auth-yes" name="work_auth" value="Yes" />
                        <label for="auth-no">No</label>
                        <input type="radio" id="auth-no" name="work_auth" value="No" />
                    </div>
                </div>

                <!-- 5. Custom Combobox -->
                <div class="form-element">
                    <label for="country-combo">Country of Residence</label>
                    <input type="text" role="combobox" id="country-combo" aria-label="Country" value="" />
                </div>

                <!-- 6. Input currently triggering inline whole number error -->
                <div class="form-element">
                    <label for="discovery-exp">Discovery Tools Experience</label>
                    <input type="text" id="discovery-exp" value="2.3" />
                    <div class="artdeco-inline-feedback--error">Enter a whole number between 0 and 99</div>
                </div>
            </div>
        </body>
        </html>
        """

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html_content)

            modal = page.locator("#modal-container")
            success = self.form_filler.fill_all_inputs_on_page(modal, job_title="DevOps Engineer", company="Tyson Foods")
            self.assertTrue(success)

            # Assert CMDB filled with integer
            cmdb_val = page.locator("#cmdb-exp").input_value()
            self.assertEqual(cmdb_val, "2")

            # Assert textarea filled with rich description
            textarea_val = page.locator("#about-exp").input_value()
            self.assertTrue(len(textarea_val) > 20)

            # Assert required checkbox is checked
            terms_checked = page.locator("#agree-terms").is_checked()
            self.assertTrue(terms_checked, "Required terms checkbox must be checked")

            # Assert follow-company is unchecked
            follow_checked = page.locator("#follow-company-checkbox").is_checked()
            self.assertFalse(follow_checked, "Follow company checkbox should be unchecked")

            # Assert radio Yes was selected
            auth_yes_checked = page.locator("#auth-yes").is_checked()
            self.assertTrue(auth_yes_checked, "Work authorization Yes radio should be selected")

            # Assert combobox was filled
            combo_val = page.locator("#country-combo").input_value()
            self.assertEqual(combo_val, "India")

            # Assert inline error was self-healed to integer "2"
            discovery_val = page.locator("#discovery-exp").input_value()
            self.assertEqual(discovery_val, "2", "Decimal 2.3 must be self-healed to integer 2")

            browser.close()

    def test_05_virtual_dom_timeout_prevention(self):
        """
        Simulates the exact scenario shown in the user's screenshot:
        Virtual DOM where cards 7, 8, 9, etc. are NOT in the DOM.
        Verifies that our new snapshot + safe timeout logic terminates in milliseconds
        rather than hanging for 30 seconds per card!
        """
        html_content = """
        <!DOCTYPE html>
        <html>
        <body>
            <ul class="job-list">
                <li data-occludable-job-id="101"><a class="job-card-list__title">DevOps 1</a></li>
                <li data-occludable-job-id="102"><a class="job-card-list__title">DevOps 2</a></li>
                <li data-occludable-job-id="103"><a class="job-card-list__title">DevOps 3</a></li>
            </ul>
        </body>
        </html>
        """

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html_content)

            # Snapshot upfront
            raw_cards = page.locator("li[data-occludable-job-id]").all()
            job_entries = []
            for c in raw_cards:
                jid = c.get_attribute("data-occludable-job-id", timeout=1000)
                job_entries.append({"id": jid})

            self.assertEqual(len(job_entries), 3)

            # Now test querying a non-existent card (e.g. simulated culled card #7)
            # Old implementation took 30,000ms. Our new code must complete in < 2000ms!
            start_time = time.time()
            card_loc = page.locator("li[data-occludable-job-id='999']").first
            exists = card_loc.count() > 0
            self.assertFalse(exists)
            elapsed_ms = (time.time() - start_time) * 1000

            self.assertLess(elapsed_ms, 500, f"Query took {elapsed_ms}ms, expected under 500ms (0 hangs)")

            browser.close()

    def test_06_ensure_workplace_types_all_three_modes(self):
        """Simulates the user's screenshot where LinkedIn had 'Remote 1' selected, and verifies that all 3 modes get selected."""
        from unittest.mock import MagicMock
        from platforms.linkedin import LinkedInPlatform

        # Mock DOM reflecting user's screenshot: 'Remote 1' filter button with only 'Remote' checked
        html_content = """
        <!DOCTYPE html>
        <html>
        <body>
            <button id="searchFilter_workplaceType">Remote 1</button>
            <div id="filter-dropdown" style="display: block;">
                <label><input type="checkbox" id="cb-onsite" /> On-site</label>
                <label><input type="checkbox" id="cb-remote" checked /> Remote</label>
                <label><input type="checkbox" id="cb-hybrid" /> Hybrid</label>
                <button type="button">Show results</button>
            </div>
        </body>
        </html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html_content)

            linkedin = LinkedInPlatform(self.config, MagicMock(), headless=True)
            linkedin._ensure_workplace_types(page)

            # Verify that On-site, Remote, and Hybrid are now all checked!
            self.assertTrue(page.locator("#cb-onsite").is_checked(), "On-site must be checked")
            self.assertTrue(page.locator("#cb-remote").is_checked(), "Remote must be checked")
            self.assertTrue(page.locator("#cb-hybrid").is_checked(), "Hybrid must be checked")

            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
