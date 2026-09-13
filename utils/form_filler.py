"""
Smart form filler for LinkedIn Easy Apply and Naukri questionnaires.
Uses regex heuristics and user configuration to answer common recruiter screening questions.
"""

import re
from typing import Any, Dict, Optional
from playwright.sync_api import Locator, Page
from utils.logger import logger


class FormFiller:
    def __init__(self, profile_config: Dict[str, Any]):
        self.profile = profile_config
        self.skills_exp = {
            k.lower().strip(): v for k, v in self.profile.get("skills_experience", {}).items()
        }
        self.gender = str(self.profile.get("gender", "Male")).strip()
        self.ethnicity = str(self.profile.get("ethnicity", "Asian")).strip()
        self.veteran_status = str(self.profile.get("veteran_status", "No")).strip()
        self.disability_status = str(self.profile.get("disability_status", "No")).strip()
        self.cover_letter_template = str(self.profile.get("cover_letter", "")).strip()
        self.account_password = str(
            self.profile.get("account_password")
            or self.profile.get("password")
            or "AutoApply@2026!"
        ).strip()

    def get_cover_letter(self, job_title: str = "DevOps Engineer", company: str = "your company") -> str:
        """Generates or retrieves tailored professional cover letter."""
        clean_title = job_title if job_title and "unknown" not in job_title.lower() else "DevOps Engineer"
        clean_company = company if company and "unknown" not in company.lower() else "your organization"

        if self.cover_letter_template:
            try:
                return self.cover_letter_template.format(job_title=clean_title, company=clean_company)
            except Exception:
                return self.cover_letter_template

        name = self.profile.get("full_name", "Candidate")
        phone = self.profile.get("phone", "")
        email = self.profile.get("email", "")
        exp = self.profile.get("total_experience_years", 2)

        return (
            f"Dear Hiring Manager,\n\n"
            f"I am writing to express my strong interest in the {clean_title} role at {clean_company}. "
            f"With over {exp} years of hands-on technical experience in DevOps, Cloud Infrastructure, and Site Reliability Engineering (SRE), "
            f"I specialize in architecting, automating, and maintaining high-availability environments across AWS, Kubernetes (Amazon EKS), Terraform, Docker, and CI/CD pipelines (Jenkins, GitHub Actions).\n\n"
            f"My expertise includes Infrastructure as Code (IaC) modularization, Kubernetes pod orchestration, and production observability using Prometheus and Grafana to guarantee system uptime. "
            f"I am enthusiastic about contributing my automation mindset and technical skills to accelerate delivery and reliability for your engineering team.\n\n"
            f"Thank you for considering my application. I look forward to the opportunity to speak with you.\n\n"
            f"Sincerely,\n"
            f"{name}\n"
            f"{email} | {phone}"
        )

    def get_answer_for_text_question(
        self, label_text: str, job_title: str = "DevOps Engineer", company: str = "your company"
    ) -> Optional[str]:
        """Determines the appropriate answer for a given question label."""
        text = label_text.lower().strip()

        # Skip sensitive ID numbers for manual user review
        if re.search(r"\bpan\b|pan\s*card|pan\s*number|\baadhaar\b|\bssn\b|\bpassport\b", text):
            return None

        # 0. Cover letter & Candidate pitch textareas
        if re.search(
            r"cover\s*letter|why\s*(should\s*we\s*hire|are\s*you\s*interested|apply|fit)|statement\s*of\s*interest|introduce\s*yourself|tell\s*us\s*about|summary|note\s*to\s*hiring",
            text,
        ):
            return self.get_cover_letter(job_title=job_title, company=company)

        # 1. Notice Period
        if re.search(r"notice\s*period|how\s*(soon|many\s*days)\s*can\s*you\s*join|availability", text):
            days = str(self.profile.get("notice_period_days", 30))
            if "month" in text:
                return str(max(1, int(days) // 30))
            return days

        # 2. Current CTC / Salary
        if re.search(r"current.*?(ctc|salary|package|compensation|annual|earning|income)", text):
            ctc = str(self.profile.get("current_ctc", "600000"))
            if "lakh" in text or "lpa" in text:
                try:
                    return str(round(float(ctc) / 100000, 1))
                except Exception:
                    return "6"
            return ctc

        # 3. Expected CTC / Salary
        if re.search(r"expected.*?(ctc|salary|package|compensation|desired|remuneration)", text):
            ctc = str(self.profile.get("expected_ctc", "1000000"))
            if "lakh" in text or "lpa" in text:
                try:
                    return str(round(float(ctc) / 100000, 1))
                except Exception:
                    return "10"
            return ctc

        # 4. Specific Skill Experience (e.g. "How many years of work experience do you have with Python?")
        skill_match = re.search(
            r"experience\s*(do\s*you\s*have\s*)?(with|in|using)?\s*([a-zA-Z0-9\.\#\+\s]+)\??$",
            text,
        )
        if skill_match:
            candidate_skill = skill_match.group(3).strip().lower()
            for skill, years in self.skills_exp.items():
                if skill in candidate_skill or candidate_skill in skill:
                    try:
                        return str(int(round(float(years))))
                    except Exception:
                        return str(years)

        # 5. Open-ended technical pitch / Describe experience / Achievements
        if re.search(r"describe|summariz|tell\s*us|overview|explain|achievement|strength|project|responsibilit|challeng", text):
            return (
                "Over 2 years of hands-on DevOps and Cloud Engineering experience specializing in AWS, "
                "Kubernetes (Amazon EKS), Terraform, Docker, and CI/CD pipelines (GitHub Actions, Jenkins). "
                "Skilled in infrastructure as code, container orchestration, and production monitoring with Prometheus and Grafana."
            )

        # 6. General / Total Experience (Numeric)
        if re.search(r"total\s*(years\s*of\s*)?experience|overall\s*experience", text):
            try:
                return str(int(round(float(self.profile.get("total_experience_years", 2)))))
            except Exception:
                return "2"

        if re.search(r"years\s*(of\s*)?experience|experience\s*\(in\s*years\)|^experience\b|\bexperience\s*in\s*years\b|experience", text):
            try:
                return str(int(round(float(self.profile.get("relevant_experience_years", 2)))))
            except Exception:
                return "2"

        # 7. Country / Nationality
        if re.search(r"country|nationality", text):
            return "India"

        # 8. Current City / Location / State
        if re.search(r"city|current\s*location|state|where\s*are\s*you\s*(currently\s*)?located", text):
            return str(self.profile.get("current_city", "Bengaluru"))

        # 8. Phone Number
        if re.search(r"phone|mobile|contact\s*number", text):
            return str(self.profile.get("phone", ""))

        # 9. Names (Split or Full)
        if re.search(r"first\s*name|given\s*name", text):
            return str(self.profile.get("first_name", ""))

        if re.search(r"last\s*name|surname|family\s*name", text):
            return str(self.profile.get("last_name", ""))

        if re.search(r"full\s*name|candidate\s*name|your\s*name|^name\s*($|[:\(])|^name\s+and\s+", text) or text.strip() in ("name", "name:"):
            return str(self.profile.get("full_name", ""))

        # 10. Address / Location Breakdown
        if re.search(r"street|address\s*line|residential\s*address|^address\b", text):
            return str(self.profile.get("street_address", ""))

        if re.search(r"postal|zip|pin\s*code|pincode", text):
            return str(self.profile.get("postal_code", ""))

        if re.search(r"\bstate\b|province|region", text):
            return str(self.profile.get("state", "Uttar Pradesh"))

        if re.search(r"\bcity\b|town", text):
            return str(self.profile.get("current_city", "Noida"))

        # 11. Current Organization / Employer & Title
        if re.search(r"current\s*(company|employer|organization)|most\s*recent\s*(company|employer)|^company\b", text):
            return str(self.profile.get("current_company", "Freelance / Cloud Infrastructure"))

        if re.search(r"current\s*(title|role|position)|headline", text):
            return str(self.profile.get("current_title", "DevOps Engineer"))

        # 12. Account Password (e.g. for Workday candidate portal registration)
        if re.search(r"password|verify\s*password|confirm\s*password", text):
            return str(self.profile.get("account_password", "AutoApply@2026!"))

        # 13. Email
        if re.search(r"email", text):
            return str(self.profile.get("email", ""))

        # 14. Education / Degree / Qualification
        if re.search(r"degree|qualification|highest\s*education|field\s*of\s*study|major", text):
            return "Bachelor of Technology in Computer Science & Engineering"

        # 15. University / College / School
        if re.search(r"university|college|institute|school", text):
            return "Galgotias University"

        # 16. Certifications / Licenses
        if re.search(r"certif|license|credential", text):
            return "AWS Certified Solutions Architect, Certified Kubernetes Administrator"

        # 17. LinkedIn URL / Profile
        if re.search(r"linkedin.*(url|profile|link)", text) or (re.search(r"linkedin", text) and "http" in text) or re.search(r"linkedin", text):
            return str(self.profile.get("linkedin_url", ""))

        # 18. GitHub / Portfolio / Website URL
        if re.search(r"github|portfolio|website|blog|repository|personal\s*link", text):
            return str(self.profile.get("github_url", ""))

        # 19. Graduation / Passing Year
        if re.search(r"graduation\s*year|passing\s*year|year\s*of\s*completion", text):
            return "2024"

        # 20. GPA / Percentage / Marks
        if re.search(r"gpa|cgpa|percentage|marks|grade", text):
            return "7.8"

        # Default fallback for numeric question fields
        if re.search(r"numeric|number|years|count", text):
            return "2"

        return None

    def get_radio_choice(self, question_text: str) -> str:
        """Determines whether 'Yes' or 'No' is the suitable response."""
        text = question_text.lower().strip()

        # Questions where 'No' is desired:
        # e.g., sponsorship requirement, criminal background, non-compete
        if re.search(r"require\s*(visa\s*)?sponsorship|will\s*you.*sponsorship|disciplinary|criminal|felony|non-compete", text):
            return "No"

        # Questions where 'Yes' is desired:
        # e.g., authorization, 18+ years old, relocate, background check, drug test
        if re.search(
            r"authorized\s*to\s*work|legally\s*authorized|eligible\s*to\s*work|relocate|background\s*check|comfortable|commute|18\s*years|negotiab|flexible",
            text,
        ):
            return "Yes"

        return "Yes"

    def get_choice_for_question(self, question_text: str, candidate_options: List[str]) -> Optional[str]:
        """
        Smartly resolves questions into exact options for:
        - Gender / Sex
        - Race / Ethnicity / Demographic / EEO
        - Veteran Status
        - Disability Status
        - Work Authorization & Sponsorship
        - Notice Period
        - General Yes/No screening
        """
        opts_clean = [
            o.strip()
            for o in candidate_options
            if o.strip()
            and o.strip()
            not in ("Select an option", "Please select", "-- Select --", "Choose an option", "Select", "None")
        ]
        if not opts_clean:
            return None

        ql = question_text.lower().strip()

        # 1. Gender / Sex Questions
        if re.search(r"gender|sex|gender\s*identity", ql):
            g = self.gender.lower()
            if g == "male":
                for o in opts_clean:
                    ol = o.lower()
                    if re.search(r"\b(male|man)\b", ol) and not re.search(r"\b(female|woman)\b", ol):
                        return o
            elif g == "female":
                for o in opts_clean:
                    ol = o.lower()
                    if re.search(r"\b(female|woman)\b", ol):
                        return o
            # Fallback to decline / prefer not to say
            for o in opts_clean:
                if re.search(r"decline|prefer\s*not|choose\s*not|undisclosed", o.lower()):
                    return o
            return opts_clean[0]

        # 2. Race / Ethnicity / Demographic (EEO-1) Questions
        if re.search(r"race|ethnicity|ethnic|origin|demographic|eeo|equal\s*opportunity", ql):
            # Target Asian / South Asian / Indian (excluding American Indian)
            for o in opts_clean:
                ol = o.lower()
                if "american indian" in ol:
                    continue
                if re.search(r"\basian\b|south\s*asian|indian\s*subcontinent", ol):
                    return o
            for o in opts_clean:
                ol = o.lower()
                if "american indian" not in ol and re.search(r"\bindian\b", ol):
                    return o
            # Fallback to decline / prefer not to say
            for o in opts_clean:
                if re.search(r"decline|prefer\s*not|choose\s*not|undisclosed", o.lower()):
                    return o
            return opts_clean[0]

        # 3. Veteran Status
        if re.search(r"veteran|military|armed\s*forces", ql):
            for o in opts_clean:
                if re.search(r"not\s*a\s*(protected\s*)?veteran|^no\b", o.lower()):
                    return o
            for o in opts_clean:
                if re.search(r"decline|prefer\s*not|choose\s*not", o.lower()):
                    return o
            return opts_clean[0]

        # 4. Disability Status
        if re.search(r"disability|handicap|impairment", ql):
            for o in opts_clean:
                if re.search(r"no.*disability|^no\b|do\s*not\s*have", o.lower()):
                    return o
            for o in opts_clean:
                if re.search(r"decline|prefer\s*not|choose\s*not", o.lower()):
                    return o
            return opts_clean[0]

        # 5. Sponsorship (Answer: No)
        if re.search(r"require\s*(visa\s*)?sponsorship|will\s*you.*sponsorship", ql):
            for o in opts_clean:
                if re.match(r"^no\b", o.lower()):
                    return o

        # 6. Authorization, relocation, commute, 18+ (Answer: Yes)
        if re.search(r"authorized|legally|eligible|relocate|commute|18\s*years|flexible|negotiab", ql):
            for o in opts_clean:
                if re.match(r"^yes\b", o.lower()):
                    return o

        # 7. Notice Period
        if re.search(r"notice\s*period|availability|how\s*soon", ql):
            days = int(self.profile.get("notice_period_days", 30))
            if days <= 15:
                keywords = ["immediate", "15", "less than"]
            elif days <= 30:
                keywords = ["30", "1 month", "1-month", "month"]
            elif days <= 60:
                keywords = ["60", "2 month", "2-month"]
            else:
                keywords = ["90", "3 month", "3-month"]

            for kw in keywords:
                for o in opts_clean:
                    if kw in o.lower():
                        return o

        # 8. Generic Yes/No selection
        has_yes = any(re.match(r"^yes\b", o.lower()) for o in opts_clean)
        has_no = any(re.match(r"^no\b", o.lower()) for o in opts_clean)
        if has_yes and has_no:
            choice = self.get_radio_choice(ql)
            for o in opts_clean:
                if o.lower().startswith(choice.lower()):
                    return o

        return opts_clean[0]

    def fill_all_inputs_on_page(
        self, container: Locator, job_title: str = "DevOps Engineer", company: str = "the company"
    ) -> bool:
        """
        Inspects all input fields, textareas, selects, comboboxes, checkboxes, and radio groups
        inside container, filling them with appropriate candidate responses.
        """
        try:
            # 1. Handle Text / Number / Email / Password inputs and textareas
            text_inputs = container.locator(
                "input[type='text']:not([role='combobox']), input[type='number'], input[type='tel'], input[type='email'], input[type='password'], input:not([type]):not([role='combobox']), textarea"
            ).all()
            for inp in text_inputs:
                try:
                    if not inp.is_visible():
                        continue
                    current_val = inp.input_value()
                    if current_val and current_val.strip():
                        # Already filled
                        continue

                    # Direct Attributes
                    inp_type = (inp.get_attribute("type") or "").lower()
                    tag_name = inp.evaluate("el => el.tagName.toLowerCase()")
                    name_attr = (inp.get_attribute("name") or "").strip()
                    inp_id = (inp.get_attribute("id") or "").strip()
                    aria_label = (inp.get_attribute("aria-label") or "").strip()
                    placeholder = (inp.get_attribute("placeholder") or "").strip()
                    autocomplete = (inp.get_attribute("autocomplete") or "").strip()
                    data_testid = (inp.get_attribute("data-testid") or inp.get_attribute("data-qa") or inp.get_attribute("data-automation-id") or "").strip()

                    own_attrs = [name_attr, inp_id, aria_label, placeholder, autocomplete, data_testid]
                    own_text = " ".join([v for v in own_attrs if v]).lower()

                    context_parts = list(own_attrs)

                    # Explicit <label for="id">
                    if inp_id:
                        lbl_for = container.locator(f"label[for='{inp_id}']")
                        if lbl_for.count() > 0:
                            txt = lbl_for.first.inner_text().strip()
                            if txt:
                                context_parts.append(txt)

                    # Preceding sibling label or span
                    try:
                        sib = inp.locator("xpath=preceding-sibling::label | preceding-sibling::span").first
                        if sib.count() > 0:
                            txt = sib.inner_text().strip()
                            if txt:
                                context_parts.append(txt)
                    except Exception:
                        pass

                    # Ancestor <label>
                    try:
                        anc_lbl = inp.locator("xpath=ancestor::label").first
                        if anc_lbl.count() > 0:
                            txt = anc_lbl.inner_text().strip()
                            if txt:
                                context_parts.append(txt)
                    except Exception:
                        pass

                    # Closest parent container label or heading (stay within ancestor::div[1] to avoid bleeding from sibling fields)
                    try:
                        parent_lbl = inp.locator("xpath=ancestor::div[1]//label").first
                        if parent_lbl.count() > 0:
                            txt = parent_lbl.inner_text().strip()
                            if txt:
                                context_parts.append(txt)
                        else:
                            # Only if ancestor::div[1] has no label, check ancestor::div[2] direct child label
                            parent_lbl2 = inp.locator("xpath=ancestor::div[2]/label").first
                            if parent_lbl2.count() > 0:
                                txt = parent_lbl2.inner_text().strip()
                                if txt:
                                    context_parts.append(txt)
                    except Exception:
                        pass

                    # Fallback: Immediate parent text
                    try:
                        parent_div = inp.locator("xpath=ancestor::div[1]").first
                        if parent_div.count() > 0:
                            txt = parent_div.inner_text().strip()
                            if txt and len(txt) < 300:
                                context_parts.append(txt)
                    except Exception:
                        pass

                    combined_context = " ".join([v for v in context_parts if v]).lower()

                    ans = None

                    # 1. Direct check on input's OWN attributes first (highest fidelity)
                    if inp_type == "password" or re.search(r"password|passwd|pwd|passphrase", own_text):
                        ans = self.account_password
                    elif inp_type == "email" or re.search(r"\bemail\b|\be-mail\b|\bemailaddress\b", own_text):
                        ans = str(self.profile.get("email", ""))
                    elif inp_type == "tel" or re.search(r"\bphone\b|\bmobile\b|\btelephone\b|\bcontact[\s_\-]*number\b|\bcell\b", own_text):
                        ans = str(self.profile.get("phone", ""))
                    elif re.search(r"\blast[\s_\-]*name\b|\bsurname\b|\bfamily[\s_\-]*name\b|\blname\b", own_text):
                        ans = str(self.profile.get("last_name", ""))
                    elif re.search(r"\bfirst[\s_\-]*name\b|\bgiven[\s_\-]*name\b|\bfname\b", own_text):
                        ans = str(self.profile.get("first_name", ""))
                    elif re.search(r"\bfull[\s_\-]*name\b|\bcandidate[\s_\-]*name\b|\byour[\s_\-]*name\b", own_text):
                        ans = str(self.profile.get("full_name", ""))

                    # Skip sensitive or identification numbers that user wants to inspect manually
                    if re.search(r"\bpan\b|pan\s*card|pan\s*number|\baadhaar\b|\bssn\b|\bpassport\b", own_text) or re.search(r"\bpan\b|pan\s*card|pan\s*number|\baadhaar\b|\bssn\b|\bpassport\b", combined_context):
                        continue

                    # 2. If not determined by own attributes, check surrounding combined context
                    if not ans:
                        if re.search(r"password|passwd|pwd|passphrase", combined_context):
                            ans = self.account_password
                        elif re.search(r"\bemail\b|\be-mail\b|\bemailaddress\b", combined_context):
                            ans = str(self.profile.get("email", ""))
                        elif re.search(r"\bphone\b|\bmobile\b|\btelephone\b|\bcontact[\s_\-]*number\b|\bcell\b", combined_context):
                            ans = str(self.profile.get("phone", ""))
                        elif re.search(r"\blast[\s_\-]*name\b|\bsurname\b|\bfamily[\s_\-]*name\b|\blname\b", combined_context):
                            ans = str(self.profile.get("last_name", ""))
                        elif re.search(r"\bfirst[\s_\-]*name\b|\bgiven[\s_\-]*name\b|\bfname\b", combined_context):
                            ans = str(self.profile.get("first_name", ""))
                        elif re.search(r"\bfull[\s_\-]*name\b|\bcandidate[\s_\-]*name\b|\byour[\s_\-]*name\b", combined_context) or (
                            re.search(r"\bname\b", combined_context) and not re.search(r"company|user|school|university|first|last", combined_context)
                        ):
                            ans = str(self.profile.get("full_name", ""))
                        else:
                            ans = self.get_answer_for_text_question(combined_context, job_title=job_title, company=company)

                    if ans:
                        # If label mentions years, experience, count, or whole number, ensure integer
                        if re.search(r"year|experience|how\s*many|numeric|number|count|whole\s*number", combined_context):
                            try:
                                if "." in ans:
                                    ans = str(int(round(float(ans))))
                            except Exception:
                                pass
                        elif inp_type == "number":
                            step = inp.get_attribute("step")
                            if (not step or step == "1") and "." in ans:
                                try:
                                    ans = str(int(round(float(ans))))
                                except Exception:
                                    pass
                        inp.fill(ans)
                    else:
                        if inp_type == "number":
                            inp.fill("2")
                        elif tag_name == "textarea":
                            # Multi-line textarea: provide professional technical summary
                            inp.fill(
                                f"I have over 2 years of hands-on experience in {job_title} roles, specializing in "
                                "cloud infrastructure (AWS), Kubernetes, Docker, Terraform, and CI/CD pipelines. "
                                "Committed to delivering reliable, scalable systems and automated workflows."
                            )
                        elif re.search(r"^(are|do|will|have|can|is|would|did|should)\s+you\b|\b(yes[\s/]+no)\b|\bauthorized\b|\beligible\b|\bwilling\b|\bcomfortable\b", combined_context):
                            inp.fill("Yes")
                        # Do not blindly fill "Yes" into generic text inputs to avoid corrupting candidate profile data
                except Exception:
                    continue

            # 2. Handle Checkboxes (Required agreements, terms, privacy, authorization)
            checkboxes = container.locator("input[type='checkbox']").all()
            for cb in checkboxes:
                try:
                    cb_id = (cb.get_attribute("id") or "").lower()
                    name_attr = (cb.get_attribute("name") or "").lower()
                    aria_label = (cb.get_attribute("aria-label") or "").lower()
                    cb_context = [cb_id, name_attr, aria_label]

                    # Check explicit label for this checkbox
                    if cb_id:
                        lbl = container.locator(f"label[for='{cb_id}']")
                        if lbl.count() > 0:
                            cb_context.append(lbl.first.inner_text().strip().lower())

                    # Check enclosing ancestor label (e.g. <label><input type="checkbox"> Terms</label>)
                    try:
                        anc_lbl = cb.locator("xpath=ancestor::label").first
                        if anc_lbl.count() > 0:
                            cb_context.append(anc_lbl.inner_text().strip().lower())
                    except Exception:
                        pass

                    # Check adjacent sibling label or span
                    try:
                        sib_lbl = cb.locator("xpath=preceding-sibling::label | following-sibling::label | preceding-sibling::span | following-sibling::span").first
                        if sib_lbl.count() > 0:
                            cb_context.append(sib_lbl.inner_text().strip().lower())
                    except Exception:
                        pass

                    # Check direct parent wrapper text ONLY if it represents this single field group
                    try:
                        p_div = cb.locator("xpath=ancestor::div[1]").first
                        if p_div.count() > 0 and p_div.locator("input[type='checkbox']").count() <= 1:
                            txt = p_div.inner_text().strip().lower()
                            if txt and len(txt) < 300:
                                cb_context.append(txt)
                    except Exception:
                        pass

                    full_cb_text = " ".join(c for c in cb_context if c)

                    # Only treat as follow if the checkbox's own label or attributes specifically mention follow
                    is_follow = bool(
                        re.search(r"\bfollow\b", f"{cb_id} {name_attr} {aria_label}")
                        or re.search(r"\bfollow\s*(the\s*)?company\b|\bfollow\b", full_cb_text)
                    )

                    if is_follow:
                        if cb.is_checked():
                            cb.uncheck(force=True)
                        continue

                    is_required = (
                        cb.get_attribute("required") is not None
                        or cb.get_attribute("aria-required") == "true"
                        or re.search(r"agree|acknowledg|certif|confirm|authoriz|consent|terms|privacy|policy|eligible|legally|conditions|service", full_cb_text)
                    )
                    if is_required and not cb.is_checked():
                        cb.check(force=True)
                except Exception:
                    continue

            # 3. Handle Radio button groups (Grouped by name to cover all DOM structures)
            all_radios = container.locator("input[type='radio']").all()
            radio_groups: Dict[str, list] = {}
            for r in all_radios:
                try:
                    name = r.get_attribute("name") or "default_group"
                    radio_groups.setdefault(name, []).append(r)
                except Exception:
                    continue

            for name, radios in radio_groups.items():
                try:
                    if any(r.is_checked() for r in radios):
                        continue

                    first_r = radios[0]
                    group_container = first_r.locator(
                        "xpath=ancestor::fieldset | ancestor::div[@role='radiogroup'] | ancestor::div[contains(@class, 'jobs-easy-apply-form-section__grouping')] | ancestor::div[contains(@class, 'form')]"
                    ).first

                    question_text = ""
                    if group_container.count() > 0:
                        legend = group_container.locator("legend, [class*='title'], [class*='label'], h3, span.t-14").first
                        if legend.count() > 0:
                            question_text = legend.inner_text().strip()

                    labels_map = {}
                    for r in radios:
                        r_id = r.get_attribute("id") or ""
                        r_label = ""
                        if r_id:
                            lbl = container.locator(f"label[for='{r_id}']")
                            if lbl.count() > 0:
                                r_label = lbl.first.inner_text().strip()
                        if not r_label:
                            r_label = r.get_attribute("value") or ""
                        if r_label:
                            labels_map[r_label] = r

                    chosen_label = self.get_choice_for_question(question_text, list(labels_map.keys()))
                    if chosen_label and chosen_label in labels_map:
                        labels_map[chosen_label].check(force=True)
                    else:
                        yes_radio = None
                        for lbl, r_elem in labels_map.items():
                            if re.match(r"^yes\b", lbl.lower()):
                                yes_radio = r_elem
                                break
                        if yes_radio:
                            yes_radio.check(force=True)
                        elif radios:
                            radios[0].check(force=True)
                except Exception:
                    continue

            # 4. Handle Standard Select Dropdowns
            selects = container.locator("select").all()
            for sel in selects:
                try:
                    if not sel.is_visible():
                        continue
                    val = sel.input_value()
                    if val and val != "Select an option" and val != "":
                        continue

                    label_id = sel.get_attribute("id") or ""
                    label_text = sel.get_attribute("aria-label") or ""
                    if label_id and not label_text:
                        lbl = container.locator(f"label[for='{label_id}']")
                        if lbl.count() > 0:
                            label_text = lbl.first.inner_text()
                    if not label_text:
                        try:
                            label_text = sel.locator("xpath=ancestor::div[contains(@class, 'form')]").first.inner_text()
                        except Exception:
                            label_text = ""

                    options = sel.locator("option").all()
                    opt_texts = [o.inner_text().strip() for o in options]
                    chosen_opt = self.get_choice_for_question(label_text, opt_texts)
                    if chosen_opt:
                        sel.select_option(label=chosen_opt)
                except Exception:
                    continue

            # 5. Handle Comboboxes / Custom Artdeco dropdowns
            comboboxes = container.locator("input[role='combobox'], [data-test-text-entity-list-form-select] input").all()
            for cb in comboboxes:
                try:
                    if not cb.is_visible():
                        continue
                    val = cb.input_value().strip()
                    if val:
                        continue

                    label_text = cb.get_attribute("aria-label") or cb.get_attribute("placeholder") or ""
                    cb_id = cb.get_attribute("id") or ""
                    if cb_id and not label_text:
                        lbl = container.locator(f"label[for='{cb_id}']")
                        if lbl.count() > 0:
                            label_text = lbl.first.inner_text()
                    if not label_text:
                        try:
                            label_text = cb.locator("xpath=ancestor::div[contains(@class, 'form')]").first.inner_text()
                        except Exception:
                            label_text = ""

                    lt = label_text.lower()
                    if "country" in lt:
                        fill_val = "India"
                    elif "city" in lt or "location" in lt:
                        fill_val = "Bengaluru"
                    elif "degree" in lt or "education" in lt:
                        fill_val = "Bachelor's Degree"
                    elif "proficiency" in lt or "language" in lt:
                        fill_val = "Professional working"
                    else:
                        fill_val = self.get_answer_for_text_question(label_text, job_title=job_title, company=company) or "India"

                    cb.fill(fill_val)
                    cb.press("Enter")
                except Exception:
                    continue

            # 6. Self-healing check for active inline error messages (e.g. 'Enter a whole number between 0 and 99')
            error_feedbacks = container.locator(
                ".artdeco-inline-feedback--error, [data-test-form-element-error-messages], .fb-form-element__error-text, [aria-invalid='true']"
            ).all()
            for err in error_feedbacks:
                try:
                    if not err.is_visible():
                        continue
                    err_txt = err.inner_text().lower()
                    parent = err.locator(
                        "xpath=ancestor::div[contains(@class, 'form-element') or contains(@class, 'fb-') or contains(@class, 'jobs-easy-apply-form-section__grouping')]"
                    ).first
                    if parent.count() > 0:
                        err_input = parent.locator("input, textarea").first
                        if err_input.count() > 0 and err_input.is_visible():
                            val = err_input.input_value().strip()
                            if "whole number" in err_txt or "between 0 and 99" in err_txt or "valid number" in err_txt:
                                try:
                                    clean_num = str(int(round(float(val))))
                                    err_input.fill(clean_num)
                                except Exception:
                                    err_input.fill("2")
                            elif not val:
                                err_input.fill("2" if err_input.get_attribute("type") == "number" else "Yes")
                except Exception:
                    pass

            return True
        except Exception as e:
            logger.warning(f"Error while auto-filling form: {e}")
            return False
