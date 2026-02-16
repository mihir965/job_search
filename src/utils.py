"""Shared utility functions."""
import logging
import re
import time
import random
from functools import wraps
from typing import Callable
from datetime import datetime
import sys

# ── Logging Setup ──

def setup_logging(verbose: bool = False):
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # Format
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = []  # Clear existing handlers
    root_logger.addHandler(console_handler)

    # Suppress noisy third-party loggers
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('filelock').setLevel(logging.WARNING)


# ── Rate Limiting ──

def rate_limit(min_delay: float, max_delay: float = None):
    """
    Decorator to add random delay between function calls.

    Args:
        min_delay: Minimum seconds to wait
        max_delay: Maximum seconds to wait (if None, uses min_delay)
    """
    if max_delay is None:
        max_delay = min_delay

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            delay = random.uniform(min_delay, max_delay)
            time.sleep(delay)
            return result
        return wrapper
    return decorator


# ── Date/Time Utilities ──

def is_business_hours(dt: datetime, start_hour: int, end_hour: int) -> bool:
    """Check if datetime falls within business hours."""
    return start_hour <= dt.hour < end_hour



# ── String Utilities ──

def extract_first_name(full_name: str) -> str:
    """Extract first name from full name."""
    if not full_name:
        return ""
    parts = full_name.strip().split()
    return parts[0] if parts else ""


def normalize_company_name(name: str) -> str:
    """Normalize company name for comparison."""
    # Remove common suffixes
    suffixes = [' Inc.', ' Inc', ' LLC', ' Ltd.', ' Ltd', ' Corporation', ' Corp.', ' Corp']
    result = name
    for suffix in suffixes:
        if result.endswith(suffix):
            result = result[:-len(suffix)]
    return result.strip().lower()



# ── URL Utilities ──

def detect_job_board_type(url: str) -> str:
    """Detect job board type from URL. Only Greenhouse and Ashby are supported."""
    url_lower = url.lower()

    if 'greenhouse.io' in url_lower or 'boards.greenhouse.io' in url_lower:
        return 'Greenhouse'
    elif 'ashbyhq.com' in url_lower:
        return 'Ashby'
    else:
        return 'Other'


# ── Keyword Matching ──

def matches_keywords(title: str, keywords: list[str]) -> bool:
    """Check if title matches any search keywords (case-insensitive)."""
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


def matches_exclude_keywords(title: str, keywords: list[str]) -> bool:
    """Check if title matches any exclude keywords (case-insensitive)."""
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


# Valid engineering/technical role keywords — title must contain at least one
_VALID_ROLE_KEYWORDS = [
    "engineer", "developer", "swe", "sde",
    "programmer", "architect",  # architect is exclude but kept here for completeness
    "devops", "sre", "reliability",
    "quant", "quantitative",
    "hft", "trading",  # trading roles at HFT firms
    "kernel", "fpga", "firmware", "embedded",
    "researcher",  # systems researcher
    "linux",
]


def is_valid_engineering_role(title: str) -> bool:
    """Check if a job title represents an actual engineering/dev role.

    Prevents non-engineering roles (HR, marketing, finance, etc.) that happen
    to match a search keyword from slipping through.
    """
    title_lower = title.lower()
    return any(kw in title_lower for kw in _VALID_ROLE_KEYWORDS)


# Regex to detect experience requirements like "5+ years", "5-10 years", "five years"
_EXPERIENCE_RE = re.compile(
    r'(\d+)\s*[\+\-–—]\s*(?:\d+\s*)?(?:years?|yrs?)',
    re.IGNORECASE,
)

_WORD_TO_NUM = {
    "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
}
_WORD_EXPERIENCE_RE = re.compile(
    r'(' + '|'.join(_WORD_TO_NUM.keys()) + r')\s*(?:\+\s*)?(?:years?|yrs?)',
    re.IGNORECASE,
)


def detect_min_experience_years(text: str) -> int:
    """Extract the minimum years of experience required from text. Returns 0 if none found."""
    if not text:
        return 0

    # Try numeric patterns first: "5+ years", "5-10 years"
    matches = _EXPERIENCE_RE.findall(text)
    if matches:
        return min(int(m) for m in matches)

    # Try word patterns: "five years"
    word_matches = _WORD_EXPERIENCE_RE.findall(text.lower())
    if word_matches:
        return min(_WORD_TO_NUM.get(w.lower(), 0) for w in word_matches)

    return 0


# Tier scores for company prioritization
TIER_SCORES = {
    "Tier 1 - Dream": 30,
    "Tier 2 - Strong": 20,
    "Tier 3 - Backup": 5,
}

# Signals that a role is new-grad friendly (bonus points)
NEW_GRAD_SIGNALS = [
    "new grad", "new graduate", "entry level", "entry-level",
    "junior", "associate", "early career", "campus", "university",
    "0-2 years", "0-1 years", "1-2 years", "2026",
]

# Strong role-title matches — systems/low-level get highest score
TIER1_ROLE_SIGNALS = [
    "systems engineer", "quantitative developer", "quant developer",
    "low latency", "infrastructure engineer", "platform engineer",
    "c++ engineer", "c++ developer", "embedded engineer",
    "kernel", "fpga", "firmware",
]

# Good SWE roles — broad match
TIER2_ROLE_SIGNALS = [
    "software engineer", "software developer", "sde",
    "backend engineer", "full stack", "fullstack",
    "site reliability", "sre", "devops",
    "cloud engineer", "production engineer",
    "data engineer", "security engineer",
    "tools engineer", "build engineer", "release engineer",
    "application engineer",
]


def score_job_relevance(job: dict, company_tier: str = "") -> int:
    """Score a job's relevance (higher = better). Used to rank and cap results.

    Scoring breakdown:
      +30/20/5  company tier bonus
      +40       new grad / entry-level signal in title
      +20       tier-1 role match (systems/low-latency)
      +12       tier-2 role match (general SWE)
      -50       non-US location
      -40       internship / co-op
      -30       high experience requirement (5+ years)
      -20       not a recognizable engineering role
    """
    title_lower = (job.get('title') or '').lower()
    location = (job.get('location') or '').lower()
    score = 0

    # Company tier bonus
    score += TIER_SCORES.get(company_tier, 0)

    # New grad signals (strongest positive signal)
    for signal in NEW_GRAD_SIGNALS:
        if signal in title_lower:
            score += 40
            break

    # Tier 1 role match (systems/low-level — Mihir's strength)
    for signal in TIER1_ROLE_SIGNALS:
        if signal in title_lower:
            score += 20
            break

    # Tier 2 role match (general SWE — still good)
    for signal in TIER2_ROLE_SIGNALS:
        if signal in title_lower:
            score += 12
            break

    # ── Penalties ──

    # Non-US location
    if location and not is_us_location(location):
        score -= 50

    # Internship / co-op in title
    _intern_signals = ["intern", "internship", "co-op", "coop", "summer analyst"]
    if any(sig in title_lower for sig in _intern_signals):
        score -= 40

    # High experience requirement in title
    min_exp = detect_min_experience_years(title_lower)
    if min_exp >= 5:
        score -= 30
    elif min_exp >= 3:
        score -= 15

    # Not a recognizable engineering role
    if not is_valid_engineering_role(title_lower):
        score -= 20

    return score


# Known non-US location strings to reject
_NON_US_LOCATIONS = [
    "london", "uk", "united kingdom", "england",
    "dublin", "ireland",
    "singapore",
    "hong kong",
    "tokyo", "japan",
    "sydney", "melbourne", "australia",
    "amsterdam", "netherlands",
    "paris", "france",
    "berlin", "munich", "germany",
    "zurich", "switzerland",
    "toronto", "vancouver", "montreal", "canada",
    "bangalore", "mumbai", "hyderabad", "india",
    "shanghai", "beijing", "china",
    "são paulo", "brazil",
    "aarhus", "denmark",
    "tel aviv", "israel",
    "warsaw", "poland",
    "prague", "czech",
    "budapest", "hungary",
    "bucharest", "romania",
    "dubai", "uae",
    "emea", "apac",
]

# US state abbreviations and cities to confirm as US
_US_SIGNALS = [
    "new york", "ny", "nyc", "manhattan",
    "chicago", "il",
    "san francisco", "sf", "california", "ca",
    "boston", "ma", "massachusetts",
    "new jersey", "nj",
    "seattle", "wa", "washington",
    "austin", "tx", "texas", "dallas", "houston",
    "remote", "united states", "usa", "u.s.",
    "los angeles", "la",
    "atlanta", "ga",
    "denver", "co", "colorado",
    "miami", "fl", "florida",
    "philadelphia", "pa",
    "pittsburgh",
    "portland", "or",
    "raleigh", "nc",
    "minneapolis", "mn",
]


def is_us_location(location: str) -> bool:
    """Check if a job location is in the US. Returns True if US or unknown/empty."""
    if not location:
        return True  # No location info — don't filter out

    loc_lower = location.lower()

    # Explicit non-US match → reject
    for non_us in _NON_US_LOCATIONS:
        if non_us in loc_lower:
            return False

    # If it has a US signal → accept
    for us in _US_SIGNALS:
        if us in loc_lower:
            return True

    # No strong signal either way — keep it (could be US without explicit label)
    return True


# ── Email Utilities ──

def generate_email_patterns(first_name: str, last_name: str, domain: str) -> list[str]:
    """Generate common email pattern variations."""
    first = first_name.lower()
    last = last_name.lower()

    patterns = [
        f"{first}.{last}@{domain}",
        f"{first}{last}@{domain}",
        f"{first[0]}{last}@{domain}",
        f"{first}_{last}@{domain}",
        f"{first}@{domain}",
    ]

    return patterns
