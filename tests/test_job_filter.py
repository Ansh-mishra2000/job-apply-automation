"""
Automated unit tests for Job Filter: Title Relevance & Freshness Matching.
Verifies that:
1. Unwanted / non-target roles (Social Media Intern, Content Creator, Data Scientist, etc.) are strictly rejected.
2. Target DevOps, SRE, and Cloud roles are properly accepted.
3. Posted date freshness filter (24h) strictly rejects jobs older than 1 day.
"""

import unittest
from utils.job_filter import is_title_relevant, is_posted_within_window, parse_posted_days


class TestJobFilter(unittest.TestCase):
    def setUp(self):
        self.target_keywords = [
            "DevOps Engineer",
            "Site Reliability Engineer",
            "Cloud Infrastructure Engineer",
            "Cloud Engineer",
            "AWS Engineer",
        ]

    def test_01_reject_unwanted_non_target_roles(self):
        """Tests that completely unwanted roles are strictly rejected."""
        unwanted_roles = [
            "Social Media Intern",
            "Content Creator",
            "Scalefox Media Content Creator",
            "AI Scientist",
            "Principal Data Scientist/ Senior Data Scientist",
            "Principal Data Scientist/Sr Data Scientist/Data Scientist",
            "Principal Data Scientist / Senior Data Scientist / Data Scientist- NLP",
            "Quantitative Developer",
            "Fullstack Software Developer",
            "Java Developer",
            "Associate Senior Executive",
            "Fresher / Junior .Net Developer",
            "HR Recruiter",
            "Business Development Executive",
            "Graphic Designer",
            "Digital Marketing Specialist",
            "Telecaller / Customer Support",
        ]

        for role in unwanted_roles:
            is_rel = is_title_relevant(role, self.target_keywords)
            self.assertFalse(
                is_rel,
                f"Role '{role}' should have been rejected as irrelevant, but was accepted!",
            )

    def test_02_accept_desired_target_roles(self):
        """Tests that configured target DevOps, SRE, and Cloud roles are accepted."""
        valid_roles = [
            "DevOps Engineer",
            "Devops Engineer",
            "Senior DevOps Engineer",
            "Cloud & DevOps Engineer",
            "Site Reliability Engineer",
            "Tech & Digital-Lead Site Reliability Engineer",
            "Lead Site Reliability Engineer (SRE)",
            "Cloud Infrastructure Engineer",
            "Cloud Engineer",
            "AWS Cloud Engineer",
            "AWS Solutions Engineer",
            "Platform Engineer (DevOps / Kubernetes)",
            "Systems Engineer",
            "Infrastructure Engineer",
        ]

        for role in valid_roles:
            is_rel = is_title_relevant(role, self.target_keywords)
            self.assertTrue(
                is_rel,
                f"Role '{role}' should have been accepted, but was rejected!",
            )

    def test_03_freshness_filter_24h(self):
        """Tests that only jobs posted within 24 hours are accepted when filter is '24h'."""
        fresh_cases = [
            "Just Now",
            "Just now",
            "Few Hours Ago",
            "few hours ago",
            "1 hour ago",
            "3 hours ago",
            "18 hours ago",
            "Today",
            "1 day ago",
            "1 Day Ago",
            "1d ago",
            "Recently",
        ]

        for text in fresh_cases:
            self.assertTrue(
                is_posted_within_window(text, "24h"),
                f"Freshness '{text}' should be accepted for 24h filter",
            )

        older_cases = [
            "Posted: 3+ weeks ago",
            "3+ weeks ago",
            "20 days ago",
            "25 days ago",
            "2 days ago",
            "2 Days Ago",
            "3 days ago",
            "4 days ago",
            "7 days ago",
            "1 week ago",
            "2 weeks ago",
            "30+ days ago",
            "30+ Days Ago",
            "1 month ago",
            "2 months ago",
        ]

        for text in older_cases:
            self.assertFalse(
                is_posted_within_window(text, "24h"),
                f"Older date '{text}' should be REJECTED for 24h filter",
            )

    def test_04_freshness_filter_longer_windows(self):
        """Tests 7d, 15d, and 30d windows."""
        # 7 days window:
        self.assertTrue(is_posted_within_window("3 days ago", "7d"))
        self.assertTrue(is_posted_within_window("7 days ago", "7d"))
        self.assertFalse(is_posted_within_window("8 days ago", "7d"))
        self.assertFalse(is_posted_within_window("2 weeks ago", "7d"))
        self.assertFalse(is_posted_within_window("3+ weeks ago", "7d"))
        self.assertFalse(is_posted_within_window("Posted: 3+ weeks ago", "7d"))
        self.assertFalse(is_posted_within_window("20 days ago", "7d"))

        # 15 days window:
        self.assertTrue(is_posted_within_window("2 weeks ago", "15d"))  # 14 days <= 15
        self.assertFalse(is_posted_within_window("3+ weeks ago", "15d")) # 21 days > 15
        self.assertFalse(is_posted_within_window("Posted: 3+ weeks ago", "15d"))
        self.assertFalse(is_posted_within_window("20 days ago", "15d"))

        # 30 days window:
        self.assertTrue(is_posted_within_window("15 days ago", "30d"))
        self.assertTrue(is_posted_within_window("20 days ago", "30d"))
        self.assertTrue(is_posted_within_window("3+ weeks ago", "30d"))  # 21 days <= 30
        self.assertFalse(is_posted_within_window("30+ days ago", "30d"))
        self.assertFalse(is_posted_within_window("2 months ago", "30d"))

    def test_05_experience_eligibility_enforcement(self):
        """Tests that experience levels are strictly checked against candidate's 2-year background (0-3 max min exp)."""
        from utils.job_filter import is_experience_eligible, parse_experience_range

        # Parse experience ranges
        self.assertEqual(parse_experience_range("0-2 Yrs"), (0.0, 2.0))
        self.assertEqual(parse_experience_range("1 - 3 years"), (1.0, 3.0))
        self.assertEqual(parse_experience_range("2-5 Yrs"), (2.0, 5.0))
        self.assertEqual(parse_experience_range("5-10 Yrs"), (5.0, 10.0))
        self.assertEqual(parse_experience_range("8+ Yrs"), (8.0, 99.0))

        # Eligible roles (min experience <= 3.0 years)
        eligible_cases = [
            "0-2 Yrs",
            "1-3 Yrs",
            "0-3 Yrs",
            "2-4 Yrs",
            "2-5 Yrs",
            "3-5 Yrs",
            "Fresher",
            "Entry Level Engineer",
            "Associate DevOps Engineer",
            "Junior Cloud Engineer (1-2 yrs)",
        ]
        for case in eligible_cases:
            self.assertTrue(
                is_experience_eligible(case, max_allowed_min_exp=3.0),
                f"Experience '{case}' should be ELIGIBLE for candidate with 2 years exp",
            )

        # Ineligible roles (min experience > 3.0 years, or senior executive titles)
        ineligible_cases = [
            "4-6 Yrs",
            "5-8 Yrs",
            "5-10 Yrs",
            "6-11 Yrs",
            "8-12 Yrs",
            "10-15 Yrs",
            "5+ years of experience required",
            "Director of Engineering",
            "Vice President Cloud Infrastructure",
            "Principal DevOps Architect",
        ]
        for case in ineligible_cases:
            self.assertFalse(
                is_experience_eligible(case, max_allowed_min_exp=3.0),
                f"Experience '{case}' should be INELIGIBLE and rejected",
            )

        # Ensure card metadata and company history are NEVER misclassified as candidate experience
        metadata_cases = [
            "10+ applicants",
            "5+ days ago",
            "5+ connections work here",
            "10+ company alumni work here",
            "We are a leading firm with 15+ years of industry excellence in cloud solutions.",
            "Established 10 years ago, our team provides DevOps services.",
        ]
        for meta in metadata_cases:
            self.assertTrue(
                is_experience_eligible(meta, max_allowed_min_exp=3.0),
                f"Card metadata/company history '{meta}' must NOT be rejected as requiring >3 yrs experience",
            )

        # Verify expanded role aliases
        from utils.job_filter import is_title_relevant
        self.assertTrue(is_title_relevant("Kubernetes / Infrastructure Automation Engineer", ["DevOps Engineer"]))
        self.assertTrue(is_title_relevant("DevSecOps / Cloud Security Engineer", ["DevSecOps Engineer"]))
        self.assertTrue(is_title_relevant("Backend Engineer (Python / FastAPI)", ["Backend Engineer"]))
        self.assertTrue(is_title_relevant("FastAPI Developer", ["Backend Engineer"]))
        self.assertTrue(is_title_relevant("Cloud Infrastructure / Systems Engineer (AWS)", ["Cloud Infrastructure Engineer"]))
        self.assertTrue(is_title_relevant("Platform Engineer / Cloud Platform Engineer", ["Platform Engineer"]))
        self.assertTrue(is_title_relevant("Linux Administrator", ["Cloud Engineer"]))
        self.assertTrue(is_title_relevant("Cloud Operations Engineer", ["DevOps Engineer"]))

    def test_06_sap_and_blacklisted_skills_exclusion(self):
        """Tests that SAP and other blacklisted skills are strictly identified and rejected."""
        from utils.job_filter import has_blacklisted_skills

        blacklisted = ["SAP", "SAP MM", "SAP SD", "SAP ABAP", "SAP HANA", "SAP ERP", "SnapLogic", "Salesforce"]

        # Rejected cases (mentioning SAP)
        rejected_cases = [
            ["SAP MM Consultant"],
            ["SAP SD Lead Engineer"],
            ["SAP DevOps Engineer"],
            ["Senior SAP ABAP Developer"],
            ["SAP HANA Cloud Administrator"],
            ["DevOps Engineer with strong SAP ERP background"],
            ["SnapLogic Developer"],
            ["Salesforce Administrator"],
        ]
        for tags in rejected_cases:
            self.assertTrue(
                has_blacklisted_skills(tags, blacklisted),
                f"Job with tags {tags} must be flagged as blacklisted!",
            )

        # Accepted cases (no SAP)
        accepted_cases = [
            ["DevOps Engineer", "AWS", "Kubernetes", "Docker", "Terraform"],
            ["Cloud Infrastructure Engineer", "Linux", "Python", "CI/CD"],
            ["Site Reliability Engineer", "Prometheus", "Grafana"],
        ]
        for tags in accepted_cases:
            self.assertFalse(
                has_blacklisted_skills(tags, blacklisted),
                f"Target job {tags} must NOT be flagged as blacklisted!",
            )

    def test_07_cv_skills_match_prioritization(self):
        """Tests that skills from candidate's CV are correctly detected and scored."""
        from utils.job_filter import calculate_cv_skills_match

        cv_skills = [
            "AWS", "EKS", "EC2", "RDS", "VPC", "S3", "Kubernetes", "Docker",
            "Helm", "Terraform", "Jenkins", "GitHub Actions", "Ansible",
            "Prometheus", "Grafana", "Python", "FastAPI", "Linux", "CI/CD"
        ]

        # High match posting (e.g. 6 skills matched)
        card_tags_high = ["AWS", "Docker", "Kubernetes", "Terraform", "Jenkins", "Python", "Golang"]
        count_high, matched_high = calculate_cv_skills_match(card_tags_high, cv_skills)
        self.assertGreaterEqual(count_high, 5)
        self.assertIn("aws", matched_high)
        self.assertIn("kubernetes", matched_high)

        # Low match posting
        card_tags_low = ["C++", "Qt", "Linux", "Embedded Systems"]
        count_low, matched_low = calculate_cv_skills_match(card_tags_low, cv_skills)
        self.assertEqual(count_low, 1)
        self.assertIn("linux", matched_low)

    def test_08_cascading_time_filter_normalization(self):
        """Tests normalizing date_posted filters for left-to-right cascading search."""
        from main import normalize_time_filters

        mock_config = {"search": {"date_posted": ["24h", "7d"]}}

        # CLI list argument
        self.assertEqual(normalize_time_filters(["24h", "7d"], mock_config), ["24h", "7d"])
        # CLI comma-separated argument
        self.assertEqual(normalize_time_filters("24h, 7d", mock_config), ["24h", "7d"])
        # Single argument
        self.assertEqual(normalize_time_filters("24h", mock_config), ["24h"])
        # Default fallback to config
        self.assertEqual(normalize_time_filters(None, mock_config), ["24h", "7d"])

    def test_09_work_modes_filter_all_three_modes(self):
        """Tests that LinkedIn search URL explicitly targets all 3 work modes: On-site (1), Remote (2), Hybrid (3)."""
        from unittest.mock import MagicMock
        from platforms.linkedin import LinkedInPlatform
        from config_loader import load_config

        config = load_config()
        linkedin = LinkedInPlatform(config, MagicMock(), headless=True)

        # Default configuration should generate f_WT=1,2,3 (covering On-site, Remote, and Hybrid)
        url = linkedin._build_search_url("DevOps Engineer", "Noida")
        self.assertIn("f_WT=1%2C2%2C3", url.replace(",", "%2C") or url)

        # Test custom subset: only Remote
        custom_cfg = {"search": {"work_modes": ["remote"]}}
        custom_linkedin = LinkedInPlatform(custom_cfg, MagicMock(), headless=True)
        custom_url = custom_linkedin._build_search_url("DevOps Engineer", "Noida")
        self.assertIn("f_WT=2", custom_url)

    def test_10_multi_page_pagination_and_apply_sorting(self):
        """Tests that LinkedIn and Naukri build correct multi-page URLs and prioritize native apply."""
        from unittest.mock import MagicMock
        from platforms.linkedin import LinkedInPlatform
        from platforms.naukri import NaukriPlatform
        from config_loader import load_config

        config = load_config()

        # 1. LinkedIn Multi-Page URLs and f_AL=true
        linkedin = LinkedInPlatform(config, MagicMock(), headless=True)
        url_p0 = linkedin._build_search_url("DevOps Engineer", "Noida", page_no=0)
        url_p1 = linkedin._build_search_url("DevOps Engineer", "Noida", page_no=1)
        url_p2 = linkedin._build_search_url("DevOps Engineer", "Noida", page_no=2)

        self.assertIn("start=0", url_p0)
        self.assertIn("start=25", url_p1)
        self.assertIn("start=50", url_p2)
        self.assertIn("f_AL=true", url_p0, "LinkedIn search must strictly include f_AL=true for Easy Apply")

        # 2. Naukri Multi-Page URLs
        naukri = NaukriPlatform(config, MagicMock(), headless=True)
        naukri_p1 = naukri._build_search_url("DevOps Engineer", "Noida", page_no=1)
        naukri_p2 = naukri._build_search_url("DevOps Engineer", "Noida", page_no=2)

        self.assertNotIn("-2", naukri_p1)
        self.assertNotIn("pageNo=2", naukri_p1)
        self.assertIn("-2?", naukri_p2)
        self.assertIn("pageNo=2", naukri_p2)

        # 3. Naukri Job Sorting (Native 1-click apply must precede external redirect hints)
        jobs = [
            {"title": "DevOps Job A", "is_external_hint": True, "is_priority": False, "skill_match_count": 5},
            {"title": "DevOps Job B", "is_external_hint": False, "is_priority": False, "skill_match_count": 2},
            {"title": "DevOps Job C", "is_external_hint": False, "is_priority": True, "skill_match_count": 1},
        ]
        sorted_jobs = sorted(
            jobs,
            key=lambda j: (not j.get("is_external_hint", False), j["is_priority"], j["skill_match_count"]),
            reverse=True,
        )
        # First should be Job C (Native + Priority), second Job B (Native), last Job A (External)
        self.assertEqual(sorted_jobs[0]["title"], "DevOps Job C")
        self.assertEqual(sorted_jobs[1]["title"], "DevOps Job B")
        self.assertEqual(sorted_jobs[2]["title"], "DevOps Job A")


if __name__ == "__main__":
    unittest.main(verbosity=2)


