"""
Configuration loader and validator for the job apply automation engine.
Supports experience range parsing and intelligent resume PDF detection.
"""

from pathlib import Path
import re
from typing import Any, Dict, Optional, Tuple
import yaml

DEFAULT_CONFIG: Dict[str, Any] = {
    "search": {
        "keywords": [
            "DevOps Engineer",
            "AWS Engineer",
            "Cloud Engineer",
            "Site Reliability Engineer",
            "Cloud Infrastructure Engineer",
        ],
        "locations": ["India"],
        "work_modes": ["on-site", "remote", "hybrid"],
        "experience_years": "0-3",
        "date_posted": "24h",
    },
    "platforms": {
        "linkedin": {
            "enabled": True,
            "max_daily_applications": 50,
            "easy_apply_only": True,
        },
        "naukri": {
            "enabled": True,
            "max_daily_applications": 50,
        },
    },
    "execution": {
        "display_mode": "prompt",
        "cron_time": "09:30",
        "human_delay_min": 3.0,
        "human_delay_max": 6.5,
    },
    "profile": {
        "resume_path": "resume.pdf",
        "full_name": "",
        "email": "",
        "phone": "",
        "current_city": "India",
        "current_ctc": "600000",
        "expected_ctc": "1000000",
        "notice_period_days": 30,
        "total_experience_years": 2,
        "relevant_experience_years": 2,
        "work_authorization": "Yes",
        "requires_sponsorship": "No",
        "willing_to_relocate": "Yes",
        "remote_work_preference": "Yes",
        "gender": "Male",
        "skills_experience": {},
    },
}


def deep_merge(source: dict, destination: dict) -> dict:
    """Recursively merges source dict into destination dict."""
    result = destination.copy()
    for key, value in source.items():
        if isinstance(value, dict) and key in result and isinstance(result[key], dict):
            result[key] = deep_merge(value, result[key])
        else:
            result[key] = value
    return result


def parse_experience_range(exp_val: Any) -> Tuple[int, int]:
    """
    Parses experience duration string or int (e.g. '0-3', '0-3 years', 2) into (min_years, max_years).
    """
    if exp_val is None:
        return (0, 3)

    if isinstance(exp_val, (int, float)):
        val = int(exp_val)
        return (val, val)

    text = str(exp_val).strip().lower()
    match = re.search(r"(\d+)\s*[-to]+\s*(\d+)", text)
    if match:
        return (int(match.group(1)), int(match.group(2)))

    digit_match = re.search(r"(\d+)", text)
    if digit_match:
        val = int(digit_match.group(1))
        return (val, val)

    return (0, 3)


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Loads configuration from YAML file, merging with default fallbacks."""
    path = Path(config_path)
    if not path.is_absolute():
        path = Path(__file__).parent.resolve() / config_path

    if not path.exists():
        example_path = path.parent / "config.example.yaml"
        if example_path.exists():
            print(f"[Info] '{config_path}' not found. Please copy 'config.example.yaml' to '{config_path}' and set your profile preferences.")
        return DEFAULT_CONFIG.copy()

    try:
        with open(path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[Warning] Failed to read {config_path} ({e}), using default configuration.")
        return DEFAULT_CONFIG.copy()

    return deep_merge(user_config, DEFAULT_CONFIG)


def get_resume_path(config: Dict[str, Any]) -> Optional[Path]:
    """
    Resolves the resume PDF path.
    1. Checks config's `profile.resume_path`.
    2. If not found, intelligently scans workspace for resume/CV PDFs (ignoring guides/manuals).
    """
    base_dir = Path(__file__).parent.resolve()
    configured_path = config.get("profile", {}).get("resume_path", "resume.pdf")

    p = Path(configured_path)
    if not p.is_absolute():
        p = base_dir / p

    if p.exists() and p.is_file():
        return p

    # Fallback: scan workspace for candidate PDFs
    all_pdfs = list(base_dir.glob("*.pdf"))
    # Exclude system guide PDFs
    candidate_pdfs = [
        f for f in all_pdfs
        if not re.search(r"guide|manual|walkthrough|doc", f.name, re.IGNORECASE)
    ]

    if not candidate_pdfs:
        return None

    # Prioritize PDF named with 'resume' or 'cv'
    for c in candidate_pdfs:
        if re.search(r"resume|cv", c.name, re.IGNORECASE):
            return c

    # Return the first available candidate PDF
    return candidate_pdfs[0]
