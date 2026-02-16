"""Job board monitoring and scraping."""
import logging
import json
import re
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import requests
from bs4 import BeautifulSoup

from .config import config
from .tracker import tracker
from .utils import rate_limit, detect_job_board_type, normalize_company_name, matches_keywords, matches_exclude_keywords
from .aggregator import adzuna_aggregator

logger = logging.getLogger(__name__)

SEEN_JOBS_FILE = Path(__file__).parent.parent / "seen_jobs.json"


class JobMonitor:
    """Monitors job boards for new relevant postings."""

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

    def monitor_all_companies(self, no_aggregators: bool = False,
                               aggregators_only: bool = False) -> List[Dict]:
        """Monitor all companies and return new matching jobs.

        Args:
            no_aggregators: Skip Adzuna aggregator, only scrape company career pages.
            aggregators_only: Only run Adzuna aggregator, skip company career pages.
        """
        all_new_jobs = []

        # Step 1: Scrape company career pages (unless aggregators_only)
        if not aggregators_only:
            companies = tracker.get_companies()
            logger.info(f"Monitoring {len(companies)} companies for new roles...")

            for company in companies:
                if not company.get("Careers URL"):
                    logger.debug(f"Skipping {company['Company']} - no careers URL")
                    continue

                try:
                    jobs = self._scrape_company(company)
                    if jobs:
                        logger.info(f"Found {len(jobs)} new jobs at {company['Company']}")
                        all_new_jobs.extend(jobs)
                except Exception as e:
                    logger.error(f"Failed to scrape {company['Company']}: {e}")
                    continue

        # Step 2: Run Adzuna aggregator (unless no_aggregators)
        if not no_aggregators:
            try:
                adzuna_jobs = adzuna_aggregator.search_jobs(self.seen_jobs)
                if adzuna_jobs:
                    logger.info(f"Adzuna aggregator found {len(adzuna_jobs)} new jobs")
                    all_new_jobs.extend(adzuna_jobs)
                    for job in adzuna_jobs:
                        self.seen_jobs.add(job['url'])
            except Exception as e:
                logger.error(f"Adzuna aggregator failed: {e}")

        # Save to tracker
        if all_new_jobs:
            tracker.add_new_roles(all_new_jobs)
            tracker.add_to_global_tracker(all_new_jobs)
            self._save_seen_jobs()

        logger.info(f"Total new jobs found: {len(all_new_jobs)}")
        return all_new_jobs

    @rate_limit(2, 3)
    def _scrape_company(self, company: Dict) -> List[Dict]:
        """Scrape jobs for a single company."""
        careers_url = company["Careers URL"]
        board_type = company.get("Board Type") or detect_job_board_type(careers_url)

        logger.debug(f"Scraping {company['Company']} ({board_type})...")

        if board_type == "Greenhouse":
            jobs = self._scrape_greenhouse(careers_url)
        elif board_type == "Lever":
            jobs = self._scrape_lever(careers_url)
        elif board_type == "Ashby":
            jobs = self._scrape_ashby(careers_url)
        elif board_type == "Workday":
            jobs = self._scrape_workday(careers_url, company['Company'])
        else:
            jobs = self._scrape_generic(careers_url)

        # Filter jobs
        filtered = []
        for job in jobs:
            # Check if already seen
            if job['url'] in self.seen_jobs:
                continue

            # Check keywords
            if not self._matches_keywords(job['title']):
                continue

            # Check exclude keywords
            if self._matches_exclude_keywords(job['title']):
                continue

            # Add metadata
            job['company'] = company['Company']
            job['date_found'] = datetime.now().isoformat()
            job['source'] = f"{board_type} API" if board_type != "Generic" else "Generic HTML"
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
        """Scrape Greenhouse job board."""
        # Extract board token from URL
        # URL pattern: https://boards.greenhouse.io/company or https://company.greenhouse.io
        match = re.search(r'greenhouse\.io/([^/]+)', url)
        if not match:
            logger.warning(f"Could not extract Greenhouse token from {url}")
            return self._scrape_generic(url)

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
            logger.warning(f"Greenhouse API failed: {e}, falling back to HTML scraping")
            return self._scrape_generic(url)

    # ── Lever ──

    def _scrape_lever(self, url: str) -> List[Dict]:
        """Scrape Lever job board."""
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

            jobs = []
            for posting in soup.find_all(class_='posting'):
                title_elem = posting.find('h5')
                link_elem = posting.find('a', class_='posting-btn-submit')
                location_elem = posting.find(class_='posting-categories')

                if title_elem and link_elem:
                    jobs.append({
                        'title': title_elem.get_text(strip=True),
                        'url': link_elem.get('href', ''),
                        'location': location_elem.get_text(strip=True) if location_elem else '',
                        'department': '',
                    })

            return jobs

        except Exception as e:
            logger.error(f"Lever scraping failed: {e}")
            return []

    # ── Ashby ──

    def _scrape_ashby(self, url: str) -> List[Dict]:
        """Scrape Ashby job board."""
        # Extract board token
        match = re.search(r'ashbyhq\.com/([^/]+)', url)
        if not match:
            return self._scrape_generic(url)

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
            logger.warning(f"Ashby API failed: {e}")
            return []

    # ── Workday ──

    def _scrape_workday(self, url: str, company_name: str) -> List[Dict]:
        """Scrape Workday job board."""
        # Workday URLs are complex - try to find the API endpoint
        # Pattern: https://{company}.wd5.myworkdayjobs.com/wday/cxs/{company}/External/jobs

        # For now, log a warning and skip (Workday is hard to scrape reliably)
        logger.warning(f"Workday scraping not fully implemented for {company_name} - skipping")
        return []

    # ── Generic HTML ──

    def _scrape_generic(self, url: str) -> List[Dict]:
        """Fallback: scrape generic HTML page."""
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

            jobs = []

            # Find all links that might be job postings
            for link in soup.find_all('a', href=True):
                href = link['href']
                text = link.get_text(strip=True)

                # Skip if no text or href
                if not text or not href:
                    continue

                # Look for job-related keywords in the link
                if any(kw in href.lower() for kw in ['job', 'career', 'position', 'role', 'opening']):
                    # Make URL absolute
                    if href.startswith('/'):
                        from urllib.parse import urljoin
                        href = urljoin(url, href)

                    jobs.append({
                        'title': text,
                        'url': href,
                        'location': '',
                        'department': '',
                    })

            # Deduplicate by URL
            seen = set()
            unique_jobs = []
            for job in jobs:
                if job['url'] not in seen:
                    seen.add(job['url'])
                    unique_jobs.append(job)

            return unique_jobs[:50]  # Limit to prevent noise

        except Exception as e:
            logger.error(f"Generic scraping failed for {url}: {e}")
            return []


# Global instance
monitor = JobMonitor()
