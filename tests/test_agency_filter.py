"""
Automated unit tests for Staffing Agency and Consultancy detection in utils/job_filter.py.
Verifies that:
1. Third-party staffing agencies and contract body shops are detected.
2. Direct corporate employers and whitelisted consulting firms are accepted.
3. Descriptions with 'hiring for client', 'C2H', or 'third party payroll' are flagged.
"""

import unittest
from utils.job_filter import is_staffing_agency


class TestAgencyFilter(unittest.TestCase):
    def test_01_detect_staffing_agency_names(self):
        """Tests identifying companies with agency/recruitment naming patterns."""
        agency_companies = [
            "Apex Staffing Solutions",
            "Global Manpower Consultancy",
            "Zenith Placement Services",
            "Pinnacle Talent Solutions",
            "Synergy Workforce Solutions",
            "Career Track Recruitment Consultants",
            "Elite HR Solutions Pvt Ltd",
        ]
        for name in agency_companies:
            self.assertTrue(
                is_staffing_agency(name),
                f"Company '{name}' should be flagged as a staffing agency",
            )

    def test_02_whitelist_legitimate_employers(self):
        """Tests that major enterprises and consulting firms are not falsely flagged."""
        legit_employers = [
            "Deloitte Consulting India",
            "Accenture",
            "PwC",
            "Tata Consultancy Services (TCS)",
            "Infosys Limited",
            "Wipro",
            "IBM India",
            "HCLTech",
            "Cognizant",
        ]
        for name in legit_employers:
            self.assertFalse(
                is_staffing_agency(name),
                f"Legitimate employer '{name}' should NOT be flagged as a staffing agency",
            )

    def test_03_detect_agency_description_text(self):
        """Tests flagging jobs whose descriptions state they are hiring for third parties or C2H."""
        test_descriptions = [
            "We are hiring for our client, a leading fintech MNC in Bengaluru.",
            "Position is on third-party payroll with option to convert full-time.",
            "Opening for DevOps Engineer - 6 Months C2H Contract.",
            "Candidate will be on our client's payroll upon joining.",
            "Role: SRE. Selected candidate will be deputed at client location.",
        ]
        for desc in test_descriptions:
            self.assertTrue(
                is_staffing_agency("Tech Corp", job_text=desc),
                f"Description '{desc}' should trigger staffing agency detection",
            )

    def test_04_direct_product_job_description(self):
        """Tests that normal direct company job descriptions pass cleanly."""
        direct_descriptions = [
            "Join our core engineering team to build scalable microservices on AWS and Kubernetes.",
            "Razorpay is hiring a Site Reliability Engineer to manage production infrastructure.",
            "You will report directly to our VP of Infrastructure and maintain CI/CD pipelines.",
        ]
        for desc in direct_descriptions:
            self.assertFalse(
                is_staffing_agency("Direct Product Co", job_text=desc),
                f"Direct job description should not be flagged",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
