"""
AI Agent Module powered by Google Gemini API.
Features:
1. Dynamic, context-aware screening question resolver for ATS & platform forms.
2. Multiple-choice option evaluator matching candidate eligibility.
3. ATS-optimized tailored cover letter generator using JD keywords.
4. ATS keyword extractor for relevance matching.
5. Seamless zero-dependency REST client with transparent fallback to regex FormFiller.
"""

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from utils.form_filler import FormFiller
from utils.logger import logger


class AIAgent:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.ai_cfg = self.config.get("ai", {})
        self.enabled = self.ai_cfg.get("enabled", False)
        self.api_key = (
            self.ai_cfg.get("api_key")
            or os.environ.get("GEMINI_API_KEY")
            or ""
        ).strip()
        self.model = self.ai_cfg.get("model", "gemini-2.5-flash").strip()
        self.profile = self.config.get("profile", {})
        self.form_filler = FormFiller(self.profile)

    def is_available(self) -> bool:
        """Checks if AI agent is enabled and has an API key configured."""
        return bool(self.enabled and self.api_key)

    def _call_gemini_api(self, prompt: str, system_instruction: Optional[str] = None) -> Optional[str]:
        """
        Executes a prompt against Gemini REST API with zero external dependencies.
        Returns text response or None on failure.
        """
        if not self.is_available():
            return None

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        contents = [{"parts": [{"text": prompt}]}]
        body_dict: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 800,
            },
        }

        if system_instruction:
            body_dict["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        data = json.dumps(body_dict).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status == 200:
                    res_json = json.loads(response.read().decode("utf-8"))
                    candidates = res_json.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
        except urllib.error.HTTPError as e:
            logger.warning(f"Gemini API HTTP Error {e.code}: {e.reason}")
        except Exception as e:
            logger.warning(f"Gemini API request failed: {e}")

        return None

    def _build_candidate_context(self) -> str:
        """Formats the candidate profile into a structured context string for Gemini."""
        p = self.profile
        skills = p.get("skills_experience", {})
        skills_str = ", ".join(f"{k}: {v} yrs" for k, v in skills.items())

        return (
            f"Candidate Name: {p.get('full_name', 'Candidate')}\n"
            f"Target Role: DevOps / SRE / Cloud Engineer\n"
            f"Total Experience: {p.get('total_experience_years', 2)} years\n"
            f"Skills & Experience: {skills_str}\n"
            f"Current CTC (INR/year): {p.get('current_ctc', '600000')}\n"
            f"Expected CTC (INR/year): {p.get('expected_ctc', '1000000')}\n"
            f"Notice Period (Days): {p.get('notice_period_days', 30)}\n"
            f"Work Authorization: {p.get('work_authorization', 'Yes')} (Legally authorized)\n"
            f"Visa Sponsorship Required: {p.get('requires_sponsorship', 'No')}\n"
            f"Willing to Relocate: {p.get('willing_to_relocate', 'Yes')}\n"
            f"Remote Preference: {p.get('remote_work_preference', 'Yes')}\n"
        )

    def answer_screening_question(
        self,
        question_text: str,
        options: Optional[List[str]] = None,
        job_title: str = "DevOps Engineer",
        company: str = "Company",
    ) -> Optional[str]:
        """
        Resolves an application screening question using Gemini AI if available,
        falling back seamlessly to FormFiller heuristics.
        """
        clean_q = question_text.strip()
        if not clean_q:
            return None

        # 1. If AI is available, ask Gemini
        if self.is_available():
            candidate_ctx = self._build_candidate_context()
            sys_inst = (
                "You are an expert recruitment assistant completing job applications on behalf of a job candidate. "
                "You are given the candidate's exact profile details and a screening question from a job portal. "
                "Provide ONLY the direct, final answer to be filled into the form field. "
                "Do NOT include conversational filler, explanations, or quotes."
            )

            if options:
                opts_formatted = "\n".join(f"- {opt}" for opt in options)
                prompt = (
                    f"{candidate_ctx}\n"
                    f"Job: {job_title} at {company}\n"
                    f"Question: {clean_q}\n"
                    f"Available Options:\n{opts_formatted}\n\n"
                    "Select the single best matching option verbatim from the list above that best aligns with the candidate's profile:"
                )
            else:
                prompt = (
                    f"{candidate_ctx}\n"
                    f"Job: {job_title} at {company}\n"
                    f"Question: {clean_q}\n\n"
                    "Provide the concise, professional answer to be typed directly into this form input. "
                    "If asking for a number (years, salary, notice), reply with ONLY the number. "
                    "If open-ended (e.g., describe your experience with X), provide a high-impact 2-sentence response highlighting relevant tools."
                )

            ai_resp = self._call_gemini_api(prompt, system_instruction=sys_inst)
            if ai_resp:
                cleaned_ans = ai_resp.strip().strip('"').strip("'")
                # If options were given, match closest option verbatim
                if options:
                    for opt in options:
                        if opt.lower().strip() == cleaned_ans.lower().strip():
                            return opt
                        if cleaned_ans.lower() in opt.lower() or opt.lower() in cleaned_ans.lower():
                            return opt
                return cleaned_ans

        # 2. Seamless Fallback to FormFiller heuristics
        return self.form_filler.get_answer_for_text_question(
            label_text=question_text,
            job_title=job_title,
            company=company,
        )

    def tailor_cover_letter(
        self,
        job_description: str,
        job_title: str = "DevOps Engineer",
        company: str = "Company",
    ) -> str:
        """
        Generates an ATS-tailored cover letter based on the specific job description keywords.
        Falls back to FormFiller template if AI is unavailable.
        """
        if self.is_available() and job_description and len(job_description.strip()) > 50:
            candidate_ctx = self._build_candidate_context()
            sys_inst = (
                "You are a career consultant tailoring a cover letter for an applicant. "
                "Write a compelling, professional 3-paragraph cover letter tailored to the job description, "
                "emphasizing candidate tools that match requirements (AWS, Kubernetes, CI/CD, Terraform, Python). "
                "Do not invent false credentials; stay aligned with candidate profile."
            )
            prompt = (
                f"{candidate_ctx}\n"
                f"Role: {job_title}\n"
                f"Company: {company}\n"
                f"Job Description:\n{job_description[:2500]}\n\n"
                "Generate the tailored cover letter text:"
            )

            ai_letter = self._call_gemini_api(prompt, system_instruction=sys_inst)
            if ai_letter and len(ai_letter.strip()) > 100:
                return ai_letter.strip()

        # Fallback to standard cover letter template
        return self.form_filler.get_cover_letter(job_title=job_title, company=company)

    def extract_ats_keywords(self, job_description: str) -> List[str]:
        """
        Extracts key technical skills and requirements from a job posting.
        """
        if self.is_available() and job_description and len(job_description.strip()) > 50:
            prompt = (
                f"Extract the top 10 most critical technical skills, tools, and certifications from this job description as a JSON array of strings:\n\n"
                f"{job_description[:2000]}\n\n"
                "Return ONLY a valid JSON array of strings (e.g. [\"AWS\", \"Kubernetes\", \"Terraform\"]):"
            )
            resp = self._call_gemini_api(prompt)
            if resp:
                try:
                    match = re.search(r"\[.*\]", resp, re.DOTALL)
                    if match:
                        keywords = json.loads(match.group(0))
                        if isinstance(keywords, list):
                            return [str(k).strip() for k in keywords if k]
                except Exception:
                    pass

        # Heuristic fallback keyword extraction
        common_tech = [
            "aws", "azure", "gcp", "kubernetes", "docker", "terraform", "ansible",
            "jenkins", "github actions", "gitlab", "python", "bash", "linux",
            "prometheus", "grafana", "helm", "ci/cd", "devops", "sre"
        ]
        found = []
        jd_lower = job_description.lower()
        for t in common_tech:
            if re.search(rf"\b{re.escape(t)}\b", jd_lower):
                found.append(t)
        return found
