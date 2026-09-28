"""
Unit tests for AI Agent module (utils/ai_agent.py).
Tests both Gemini API integration (mocked) and offline heuristic fallbacks.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from utils.ai_agent import AIAgent


class TestAIAgent(unittest.TestCase):
    def setUp(self):
        self.config_disabled = {
            "ai": {
                "enabled": False,
                "api_key": "",
                "model": "gemini-2.5-flash",
            },
            "profile": {
                "full_name": "Ansh Mishra",
                "phone": "9876543210",
                "email": "ansh@example.com",
                "total_experience_years": 2,
                "current_ctc": "600000",
                "expected_ctc": "1000000",
                "notice_period_days": 30,
                "skills_experience": {
                    "aws": 2,
                    "kubernetes": 2,
                    "docker": 2,
                    "python": 2,
                    "terraform": 2,
                },
            },
        }

        self.config_enabled = {
            "ai": {
                "enabled": True,
                "api_key": "dummy_test_api_key",
                "model": "gemini-2.5-flash",
            },
            "profile": self.config_disabled["profile"],
        }

    def test_availability_flags(self):
        """Tests that is_available accurately reflects config and key presence."""
        agent_disabled = AIAgent(self.config_disabled)
        self.assertFalse(agent_disabled.is_available())

        agent_enabled = AIAgent(self.config_enabled)
        self.assertTrue(agent_enabled.is_available())

    def test_offline_fallback_for_text_questions(self):
        """Tests that when AI is disabled, it seamlessly uses FormFiller heuristics."""
        agent = AIAgent(self.config_disabled)

        # Question about experience
        ans_exp = agent.answer_screening_question("How many years of experience do you have with AWS?")
        self.assertEqual(ans_exp, "2")

        # Question about notice period
        ans_notice = agent.answer_screening_question("What is your notice period?")
        self.assertEqual(ans_notice, "30")

        # Question about CTC
        ans_ctc = agent.answer_screening_question("What is your expected salary?")
        self.assertEqual(ans_ctc, "1000000")

    def test_gemini_api_mock_answer(self):
        """Tests question answering when Gemini returns an AI-crafted response."""
        agent = AIAgent(self.config_enabled)

        mock_resp = "I have managed multi-node Kubernetes clusters on AWS EKS with Helm."
        with patch.object(agent, "_call_gemini_api", return_value=mock_resp):
            ans = agent.answer_screening_question(
                "Describe your production Kubernetes experience",
                job_title="DevOps Engineer",
                company="Stripe",
            )
            self.assertEqual(ans, mock_resp)

    def test_gemini_api_option_selection(self):
        """Tests multiple choice selection with Gemini matching."""
        agent = AIAgent(self.config_enabled)
        options = ["0-1 years", "2-4 years", "5+ years"]

        with patch.object(agent, "_call_gemini_api", return_value="2-4 years"):
            ans = agent.answer_screening_question(
                "Experience range in Cloud Automation",
                options=options,
            )
            self.assertEqual(ans, "2-4 years")

    def test_tailor_cover_letter_offline_fallback(self):
        """Tests cover letter generation when AI is offline."""
        agent = AIAgent(self.config_disabled)
        letter = agent.tailor_cover_letter(
            job_description="Seeking a DevOps Engineer with AWS and Kubernetes experience.",
            job_title="DevOps Engineer",
            company="Google",
        )
        self.assertIn("Ansh Mishra", letter)
        self.assertIn("DevOps Engineer", letter)
        self.assertIn("Google", letter)

    def test_tailor_cover_letter_with_ai(self):
        """Tests customized cover letter generation when AI is enabled."""
        agent = AIAgent(self.config_enabled)
        mock_custom_letter = (
            "Dear Hiring Manager,\n\nI am thrilled to apply for the DevOps Engineer role at Netflix. "
            "My experience with AWS, Kubernetes, and Terraform directly aligns with your infrastructure needs."
        )
        with patch.object(agent, "_call_gemini_api", return_value=mock_custom_letter):
            letter = agent.tailor_cover_letter(
                job_description="We need an engineer experienced with Netflix Spinnaker and AWS.",
                job_title="DevOps Engineer",
                company="Netflix",
            )
            self.assertEqual(letter, mock_custom_letter)

    def test_extract_ats_keywords_offline_and_online(self):
        """Tests keyword extraction via heuristics and AI."""
        # Offline heuristic
        agent_offline = AIAgent(self.config_disabled)
        jd = "Looking for a DevOps Engineer with Terraform, Docker, Kubernetes, and Python skills."
        keywords = agent_offline.extract_ats_keywords(jd)
        self.assertIn("terraform", keywords)
        self.assertIn("kubernetes", keywords)
        self.assertIn("docker", keywords)
        self.assertIn("python", keywords)

        # Online AI
        agent_online = AIAgent(self.config_enabled)
        with patch.object(agent_online, "_call_gemini_api", return_value='["AWS", "ArgoCD", "Kubernetes"]'):
            ai_keywords = agent_online.extract_ats_keywords(jd)
            self.assertEqual(ai_keywords, ["AWS", "ArgoCD", "Kubernetes"])


if __name__ == "__main__":
    unittest.main()
