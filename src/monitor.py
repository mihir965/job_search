"""Job board monitoring — Greenhouse + Ashby only."""
import logging
import json
import re
from pathlib import Path
from typing import List, Dict
from datetime import datetime
import requests

from .config import config
from .tracker import tracker
from .utils import (rate_limit, detect_job_board_type, matches_keywords,
                    matches_exclude_keywords, score_job_relevance, is_us_location,
                    is_valid_engineering_role)

logger = logging.getLogger(__name__)

SEEN_JOBS_FILE = Path(__file__).parent.parent / "seen_jobs.json"


class JobMonitor:
    """Monitors Greenhouse and Ashby job boards for new relevant postings."""

    def __init__(self):
        self.seen_jobs = self._load_seen_jobs()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })

    def _load_seen_jobs(self) -> set:
        """Load previously seen job URLs."""
        if SEEN_JOBS_FILE.exists():
            with open(SEEN_JOBS_FILE) as f:
                data = json.load(f)
                return set(data.get("seen_urls", []))
        return set()

    def _save_seen_jobs(self):
        """Save seen job URLs to file."""
        with open(SEEN_JOBS_FILE, 'w') as f:
            json.dump({"seen_urls": list(self.seen_jobs)}, f, indent=2)

    def monitor_all_companies(self) -> List[Dict]:
        """Monitor all companies and return new matching jobs."""
        all_new_jobs = []

        # Build company tier lookup for scoring
        companies = tracker.get_companies()
        tier_lookup = {c['Company']: c.get('Tier', '') for c in companies}

        logger.info(f"Monitoring {len(companies)} companies for new roles...")

        for company in companies:
            if not company.get("Careers URL"):
                logger.debug(f"Skipping {company['Company']} - no careers URL")
                continue

            board_type = company.get("Board Type") or detect_job_board_type(company["Careers URL"])
            if board_type not in ("Greenhouse", "Ashby"):
                logger.debug(f"Skipping {company['Company']} - unsupported board type: {board_type}")
                continue

            try:
                jobs = self._scrape_company(company, board_type)
                if jobs:
                    logger.info(f"Found {len(jobs)} new jobs at {company['Company']}")
                    all_new_jobs.extend(jobs)
            except Exception as e:
                logger.error(f"Failed to scrape {company['Company']}: {e}")
                continue

        # Score, rank, and cap results
        max_results = config.monitor.get('max_results', 0)
        if all_new_jobs:
            for job in all_new_jobs:
                tier = tier_lookup.get(job.get('company', ''), '')
                job['_score'] = score_job_relevance(job, tier)

            all_new_jobs.sort(key=lambda j: j['_score'], reverse=True)

            if max_results and len(all_new_jobs) > max_results:
                logger.info(f"Capping results from {len(all_new_jobs)} to top {max_results} by relevance")
                dropped = all_new_jobs[max_results:]
                for job in dropped:
                    self.seen_jobs.discard(job['url'])
                all_new_jobs = all_new_jobs[:max_results]

            # Clean up internal score field before saving
            for job in all_new_jobs:
                del job['_score']

            tracker.add_new_roles(all_new_jobs)
            self._save_seen_jobs()

        logger.info(f"Total new jobs found: {len(all_new_jobs)}")
        return all_new_jobs

    @rate_limit(2, 3)
    def _scrape_company(self, company: Dict, board_type: str) -> List[Dict]:
        """Scrape jobs for a single company."""
        careers_url = company["Careers URL"]
        logger.debug(f"Scraping {company['Company']} ({board_type})...")

        if board_type == "Greenhouse":
            jobs = self._scrape_greenhouse(careers_url)
        elif board_type == "Ashby":
            jobs = self._scrape_ashby(careers_url)
        else:
            return []

        # Filter jobs
        filtered = []
        for job in jobs:
            if job['url'] in self.seen_jobs:
                continue
            if not self._matches_keywords(job['title']):
                continue
            if self._matches_exclude_keywords(job['title']):
                continue
            if not is_us_location(job.get('location', '')):
                continue
            if not is_valid_engineering_role(job['title']):
                logger.debug(f"Skipping non-engineering role: {job['title']}")
                continue

            job['company'] = company['Company']
            job['date_found'] = datetime.now().isoformat()
            job['source'] = f"{board_type} API"
            job['status'] = 'New'
            job['notes'] = ''

            filtered.append(job)
            self.seen_jobs.add(job['url'])

        return filtered

    def _matches_keywords(self, title: str) -> bool:
        """Check if title matches any search keywords."""
        keywords = config.monitor.get('search_keywords', [])
        return matches_keywords(title, keywords)

    def _matches_exclude_keywords(self, title: str) -> bool:
        """Check if title matches any exclude keywords."""
        keywords = config.monitor.get('exclude_keywords', [])
        return matches_exclude_keywords(title, keywords)

    # ── Greenhouse ──

    def _scrape_greenhouse(self, url: str) -> List[Dict]:
        """Scrape Greenhouse job board via JSON API."""
        match = re.search(r'greenhouse\.io/([^/]+)', url)
        if not match:
            logger.warning(f"Could not extract Greenhouse token from {url}")
            return []

        board_token = match.group(1)
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"

        try:
            resp = self.session.get(api_url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            jobs = []
            for job in data.get('jobs', []):
                jobs.append({
                    'title': job.get('title'),
                    'url': job.get('absolute_url'),
                    'location': job.get('location', {}).get('name', ''),
                    'department': ', '.join([dept['name'] for dept in job.get('departments', [])]),
                })

            return jobs

        except Exception as e:
            logger.warning(f"Greenhouse API failed for {url}: {e}")
            return []

    # ── Ashby ──

    def _scrape_ashby(self, url: str) -> List[Dict]:
        """Scrape Ashby job board via JSON API."""
        match = re.search(r'ashbyhq\.com/([^/]+)', url)
        if not match:
            logger.warning(f"Could not extract Ashby token from {url}")
            return []

        board_token = match.group(1)
        api_url = f"https://api.ashbyhq.com/posting-api/job-board/{board_token}"

        try:
            resp = self.session.get(api_url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            jobs = []
            for job in data.get('jobs', []):
                jobs.append({
                    'title': job.get('title'),
                    'url': job.get('jobUrl', ''),
                    'location': job.get('location', ''),
                    'department': job.get('departmentName', ''),
                })

            return jobs

        except Exception as e:
            logger.warning(f"Ashby API failed for {url}: {e}")
            return []


# Global instance
monitor = JobMonitor()
