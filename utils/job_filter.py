"""
Job relevance and freshness filter.
Ensures applications are only submitted to roles matching config.yaml keywords,
and enforces exact posting time-windows (24h, 7d, 15d, 30d).
"""

import re
from typing import List, Optional, Tuple, Union

# Roles that should NEVER be applied to for a DevOps / SRE / Cloud candidate
# unless explicitly requested by the user in config.yaml keywords
DEFAULT_BLACKLIST_ROLES = [
    "social media",
    "content creator",
    "content writer",
    "copywriter",
    "sales",
    "marketing",
    "business development",
    "telecaller",
    "telesales",
    "bpo",
    "recruiter",
    "talent acquisition",
    "human resources",
    "data scientist",
    "data science",
    "data analyst",
    "business analyst",
    "graphic designer",
    "ui/ux",
    "video editor",
    "accountant",
    "finance",
    "auditor",
    "fullstack",
    "full stack",
    "frontend",
    "react",
    "angular",
    "java developer",
    ".net developer",
    "php developer",
    "flutter",
    "ios developer",
    "android developer",
    "intern",
    "trainee",
    "apprentice",
    "volunteer",
    "tutor",
    "nurse",
    "medical",
    "receptionist",
    "office assistant",
    "executive assistant",
    "snaplogic",
    "salesforce",
    "sap",
    "sap mm",
    "sap sd",
    "sap abap",
    "sap hana",
    "sap erp",
    "sap basis",
    "sap consultant",
    "director",
    "vice president",
]

# Blacklisted skills that should immediately disqualify a job posting
DEFAULT_BLACKLIST_SKILLS = [
    "sap",
    "sap mm",
    "sap sd",
    "sap abap",
    "sap hana",
    "sap erp",
    "sap basis",
    "snaplogic",
    "salesforce",
]

# Candidate technical skills extracted from CV (for priority match scoring)
DEFAULT_CV_SKILLS = [
    "aws",
    "amazon eks",
    "eks",
    "ec2",
    "ecr",
    "rds",
    "postgresql",
    "vpc",
    "s3",
    "iam",
    "dynamodb",
    "boto3",
    "ccm",
    "kubernetes",
    "k8s",
    "docker",
    "helm",
    "rbac",
    "cronjobs",
    "minikube",
    "terraform",
    "jenkins",
    "github actions",
    "git",
    "ansible",
    "ci/cd",
    "cicd",
    "irsa",
    "least-privilege",
    "prometheus",
    "grafana",
    "alertmanager",
    "sre",
    "monitoring",
    "python",
    "fastapi",
    "bash",
    "shell scripting",
    "sql",
    "rest api",
    "linux",
    "ubuntu",
    "devsecops",
    "cloud security",
    "infrastructure automation",
    "platform engineer",
]

# Role alias mappings for flexible match of DevOps/SRE/Cloud/Backend/Platform roles
ROLE_ALIASES = {
    "devops": [
        "devops",
        "devsecops",
        "site reliability",
        "sre",
        "cloud",
        "infrastructure",
        "platform engineer",
        "systems engineer",
        "sysops",
        "build and release",
        "release engineer",
        "kubernetes",
        "k8s",
        "cloud operations",
        "operations engineer",
    ],
    "site reliability": [
        "sre",
        "site reliability",
        "reliability",
        "devops",
        "production support engineer",
        "systems engineer",
    ],
    "cloud": [
        "cloud",
        "aws",
        "azure",
        "gcp",
        "cloud infrastructure",
        "cloud engineer",
        "cloud architect",
        "cloud specialist",
        "cloud operations",
        "systems engineer",
        "linux administrator",
        "cloud security",
        "cloud platform",
    ],
    "aws": [
        "aws",
        "cloud",
        "amazon web services",
        "systems engineer",
        "cloud infrastructure",
    ],
    "infrastructure": [
        "infrastructure",
        "infra",
        "cloud infrastructure",
        "systems engineer",
        "platform engineer",
        "linux administrator",
        "infrastructure automation",
        "automation engineer",
    ],
    "kubernetes": [
        "kubernetes",
        "k8s",
        "infrastructure automation",
        "container",
        "cloud native",
        "devops",
    ],
    "devsecops": [
        "devsecops",
        "cloud security",
        "security engineer",
        "secops",
        "devops",
        "appsec",
    ],
    "security": [
        "security",
        "devsecops",
        "cloud security",
        "cloud security engineer",
        "information security",
        "cyber security",
    ],
    "backend": [
        "backend",
        "back-end",
        "python",
        "fastapi",
        "python developer",
        "api engineer",
        "software engineer",
    ],
    "python": [
        "python",
        "fastapi",
        "backend",
        "django",
        "flask",
        "python developer",
        "python engineer",
    ],
    "fastapi": [
        "fastapi",
        "python",
        "backend",
        "api developer",
        "backend engineer",
    ],
    "platform": [
        "platform",
        "platform engineer",
        "cloud platform",
        "cloud platform engineer",
        "internal platform",
        "devops",
        "infrastructure",
    ],
    "systems": [
        "systems",
        "systems engineer",
        "system engineer",
        "infrastructure engineer",
        "cloud systems",
        "sysops",
        "linux administrator",
    ],
    "automation": [
        "automation",
        "infrastructure automation",
        "ansible",
        "terraform",
        "devops",
        "automation engineer",
    ],
}


def is_title_relevant(job_title: str, target_keywords: List[str]) -> bool:
    """
    Returns True only if job_title aligns with configured target roles
    and does not match blacklisted/unwanted roles.
    """
    if not job_title or not job_title.strip():
        return False

    title_clean = job_title.lower().strip()
    target_clean = [k.lower().strip() for k in target_keywords if k and k.strip()]

    # 1. Check Blacklist:
    # If title has any blacklisted skill like SAP, reject immediately
    if has_blacklisted_skills(title_clean):
        return False

    # If a blacklist term is in the title, only allow it if the user EXPLICITLY
    # included that term in target_keywords (e.g. if user asked for "Data Scientist")
    for bl in DEFAULT_BLACKLIST_ROLES:
        if re.search(r"\b" + re.escape(bl) + r"\b", title_clean):
            explicitly_requested = any(bl in tk for tk in target_clean)
            if not explicitly_requested:
                return False

    # 2. Check Positive Match against target keywords
    for tk in target_clean:
        # Direct substring match
        if tk in title_clean:
            return True

        # Check alias / stem matching
        tk_words = [
            w for w in re.findall(r"[a-z]+", tk)
            if w not in ("engineer", "developer", "lead", "senior", "jr", "sr")
        ]
        for word in tk_words:
            aliases = ROLE_ALIASES.get(word, [word])
            for alias in aliases:
                if re.search(r"\b" + re.escape(alias) + r"\b", title_clean):
                    return True

    return False


def has_blacklisted_skills(
    text_or_tags: Union[str, List[str]],
    blacklisted_skills: Optional[List[str]] = None,
) -> bool:
    """
    Returns True if any blacklisted skill (such as SAP, Salesforce) appears in the text or list of tags.
    Uses strict word boundaries so 'whatsapp' doesn't match 'sap', but 'SAP MM' or 'SAP' does.
    """
    if not text_or_tags:
        return False

    bl_skills = [
        s.lower().strip()
        for s in (blacklisted_skills or DEFAULT_BLACKLIST_SKILLS)
        if s and s.strip()
    ]

    if isinstance(text_or_tags, list):
        combined = " " + " ".join(str(t).lower().strip() for t in text_or_tags) + " "
    else:
        combined = " " + str(text_or_tags).lower().strip() + " "

    for bl in bl_skills:
        pattern = r"\b" + re.escape(bl) + r"\b"
        if re.search(pattern, combined):
            return True

    return False


def parse_experience_range(exp_text: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Parses experience text (e.g. '0-2 Yrs', '1-3 Yrs', '3-5 Yrs', '5-10 Yrs', '5+ Yrs', 'Freshers')
    into (min_years, max_years).
    Requires explicit year unit (yrs, years, y) so that metadata like '10+ applicants',
    '5+ days ago', '5+ connections' are NEVER falsely parsed as required experience.
    """
    if not exp_text:
        return None, None

    txt = exp_text.lower().strip()

    # If text is multi-word or long (e.g. card snippet or job description > 30 chars),
    # explicitly look for candidate experience requirements rather than company metadata
    if len(txt) > 30:
        # Pattern 1: 'requires 3-5 years', 'minimum 2 years experience', 'at least 5+ yrs'
        m_req = re.search(
            r"(?:experience|exp|require[sd]?|minimum|min|at\s+least|candidate\s+must\s+have|background\s+of)[\s\w,:\-–]{0,35}?"
            r"(\d+(?:\.\d+)?\s*(?:-|to|\+)\s*(?:\d+(?:\.\d+)?\s*)?(?:yrs?|years?|y)\b)",
            txt,
        )
        if not m_req:
            # Pattern 2: '3-5 years of experience', '5+ years experience', '2 yrs exp'
            m_req = re.search(
                r"(\d+(?:\.\d+)?\s*(?:-|to|\+)\s*(?:\d+(?:\.\d+)?\s*)?(?:yrs?|years?|y)\b)[\s\w]{0,25}?(?:exp(?:erience)?)\b",
                txt,
            )

        if m_req:
            txt = m_req.group(1)
        elif re.search(r"\b(?:freshers?|entry\s*level|graduate|0\s*yrs?)\b", txt):
            return 0.0, 1.0
        else:
            return None, None

    # Check for freshers using strict word boundaries
    if re.search(r"\b(?:freshers?|entry\s*level|graduate|0\s*yrs?)\b", txt):
        if not re.search(r"\d+\s*(?:-|to)\s*\d+\s*(?:yrs?|years?|y)\b", txt):
            return 0.0, 1.0

    # Range pattern with explicit year marker: '0-2 Yrs', '1 - 3 yrs', '2 to 5 years', '0 - 3 y'
    m_range = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(?:yrs?|years?|y)\b", txt)
    if m_range:
        return float(m_range.group(1)), float(m_range.group(2))

    # Plus pattern with explicit year marker: '5+ yrs', '3+ years', '8+ y', '5+ years of experience'
    m_plus = re.search(r"(\d+(?:\.\d+)?)\s*\+\s*(?:yrs?|years?|y)\b", txt)
    if m_plus:
        return float(m_plus.group(1)), 99.0

    # Single number with explicit year marker: '2 yrs', '3 years'
    m_single = re.search(r"(\d+(?:\.\d+)?)\s*(?:yrs?|years?|y)\b", txt)
    if m_single:
        val = float(m_single.group(1))
        return val, val

    return None, None


def is_experience_eligible(
    exp_text: str,
    max_allowed_min_exp: float = 3.0,
    candidate_exp: float = 2.0,
) -> bool:
    """
    Returns True if the required experience range aligns with the candidate's profile (0-3 years).
    Rejects jobs where minimum required experience > max_allowed_min_exp (e.g. 4-6 yrs, 5-10 yrs, 8-12 yrs, 5+ yrs).
    Also rejects executive/director levels.
    """
    if not exp_text:
        return True

    txt = exp_text.lower().strip()

    # Reject executive levels
    if any(w in txt for w in ("director", "vice president", "vp", "head of", "principal", "chief")):
        return False

    min_exp, max_exp = parse_experience_range(exp_text)
    if min_exp is not None:
        # If minimum required experience exceeds candidate's maximum allowed threshold (3.0 yrs), reject!
        if min_exp > max_allowed_min_exp:
            return False

    return True


def calculate_cv_skills_match(
    text_or_tags: Union[str, List[str]],
    cv_skills: Optional[List[str]] = None,
) -> Tuple[int, List[str]]:
    """
    Calculates how many technical skills from the candidate's CV appear in the job's tags or text.
    Returns (match_count, matched_skills_list).
    """
    if not text_or_tags:
        return 0, []

    skills_to_check = [s.lower().strip() for s in (cv_skills or DEFAULT_CV_SKILLS) if s and s.strip()]

    if isinstance(text_or_tags, list):
        combined = " " + " ".join(str(t).lower().strip() for t in text_or_tags) + " "
    else:
        combined = " " + str(text_or_tags).lower().strip() + " "

    matched = []
    for skill in skills_to_check:
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, combined):
            if skill not in matched:
                matched.append(skill)

    return len(matched), matched


def extract_posted_time_from_text(text: str) -> str:
    """
    Extracts posted time snippet (e.g. '3+ weeks ago', 'Posted: 3+ weeks ago', '20 days ago', '1 day ago', 'just now')
    from raw card text or page header.
    """
    if not text:
        return ""
    m = re.search(
        r"(?:posted:?\s*)?(\d+\s*\+?\s*(?:days?|weeks?|months?|years?|hours?|mins?|d|w|m|y)\s*ago|just\s*now|today|yesterday|few\s*hours?\s*ago|\d+\s*\+\s*days?)",
        text,
        re.I,
    )
    if m:
        return m.group(1).strip()
    return ""


def parse_posted_days(posted_text: str) -> int:
    """
    Parses posted time string into approximate number of days elapsed.
    Accurately handles patterns like '3+ weeks ago', '20 days ago', '30+ days ago', etc.
    """
    txt = posted_text.lower().strip()
    if not txt:
        return 999

    # Clean leading 'posted:' prefix if present
    txt = re.sub(r"^posted:?\s*", "", txt)

    # 1. Fresh indicators (<24 hours)
    if any(w in txt for w in ("hour", "minute", "sec", "just now", "few hour", "today")):
        return 0

    if "yesterday" in txt:
        return 1

    # 2. Year check
    m_year = re.search(r"(\d+)\s*\+?\s*(?:years?|y|yrs?)\b", txt)
    if m_year:
        return int(m_year.group(1)) * 365
    if "year" in txt:
        return 365

    # 3. Month check (handles '1 month', '2+ months', '30+ days', '+30 days')
    if "30+" in txt or "+30" in txt or "30 +" in txt:
        return 35

    m_month = re.search(r"(\d+)\s*\+?\s*(?:months?|m)\b", txt)
    if m_month:
        return int(m_month.group(1)) * 30
    if "month" in txt:
        return 30

    # 4. Week check (handles '1 week', '2 weeks', '3+ weeks ago', '3+w', '+3 weeks')
    m_week = re.search(r"(\d+)\s*\+?\s*(?:weeks?|w)\b", txt)
    if m_week:
        return int(m_week.group(1)) * 7
    if "week" in txt:
        return 7

    # 5. Day check (handles '1 day', '3 days', '5+ days', '20 days ago')
    m_day = re.search(r"(\d+)\s*\+?\s*(?:days?|d)\b", txt)
    if m_day:
        return int(m_day.group(1))
    if "day" in txt:
        return 2

    # 6. 'Recently' fallback
    if "recently" in txt:
        return 1

    # Default fallback for unknown text: treat as older so it does not falsely pass fresh filters
    return 999


def is_posted_within_window(posted_text: str, time_filter: str = "24h") -> bool:
    """Returns True if the job was posted within the time_filter window."""
    tf = str(time_filter).lower().strip()
    max_days = 1
    if tf in ("24h", "1d", "day", "past_24h"):
        max_days = 1
    elif tf in ("7d", "week", "past_7d", "past_week"):
        max_days = 7
    elif tf in ("15d", "15days", "past_15d"):
        max_days = 15
    elif tf in ("30d", "month", "past_30d", "past_month"):
        max_days = 30

    extracted = extract_posted_time_from_text(posted_text) or posted_text
    days = parse_posted_days(extracted)
    return days <= max_days


