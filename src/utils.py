"""Shared utility functions."""
import logging
import time
import random
from functools import wraps
from typing import Callable
from datetime import datetime, timedelta
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


def add_business_days(start_date: datetime, days: int) -> datetime:
    """Add business days to a date (skips weekends)."""
    current = start_date
    days_added = 0

    while days_added < days:
        current += timedelta(days=1)
        # Monday = 0, Sunday = 6
        if current.weekday() < 5:  # Monday-Friday
            days_added += 1

    return current


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


def truncate_text(text: str, max_words: int = 300) -> str:
    """Truncate text to max_words words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return ' '.join(words[:max_words]) + '...'


# ── URL Utilities ──

def detect_job_board_type(url: str) -> str:
    """Detect job board type from URL."""
    url_lower = url.lower()

    if 'greenhouse.io' in url_lower or 'boards.greenhouse.io' in url_lower:
        return 'Greenhouse'
    elif 'lever.co' in url_lower or 'jobs.lever.co' in url_lower:
        return 'Lever'
    elif 'ashbyhq.com' in url_lower:
        return 'Ashby'
    elif 'myworkdayjobs.com' in url_lower:
        return 'Workday'
    else:
        return 'Generic'


# ── Keyword Matching ──

def matches_keywords(title: str, keywords: list[str]) -> bool:
    """Check if title matches any search keywords (case-insensitive)."""
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


def matches_exclude_keywords(title: str, keywords: list[str]) -> bool:
    """Check if title matches any exclude keywords (case-insensitive)."""
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


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
