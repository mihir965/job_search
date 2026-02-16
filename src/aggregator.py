"""Adzuna job aggregator — discovers roles across the job market."""
import logging
from typing import List, Dict, Set
from datetime import datetime
from urllib.parse import urlencode
import requests

from .config import config
from .tracker import tracker
from .utils import rate_limit, matches_keywords, matches_exclude_keywords

logger = logging.getLogger(__name__)


class AdzunaAggregator:
    """Searches Adzuna for relevant job postings."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })

    @property
    def _config(self) -> Dict:
        return config.aggregators.get('adzuna', {})

    @property
    def enabled(self) -> bool:
        cfg = self._config
        return bool(cfg.get('enabled') and cfg.get('app_id') and cfg.get('app_key'))

    def search_jobs(self, seen_jobs: Set[str]) -> List[Dict]:
        """Search Adzuna for jobs matching config keywords. Returns new jobs not in seen_jobs."""
        if not self.enabled:
            logger.warning("Adzuna aggregator not enabled or missing credentials - skipping")
            return []

        keywords = config.monitor.get('search_keywords', [])
        exclude = config.monitor.get('exclude_keywords', [])
        all_jobs: Dict[str, Dict] = {}  # url -> job, for dedup across keywords

        for keyword in keywords:
            try:
                results = self._search_keyword(keyword)
                for job in results:
                    url = job.get('url', '')
                    if url and url not in all_jobs:
                        all_jobs[url] = job
            except Exception as e:
                logger.error(f"Adzuna search failed for keyword '{keyword}': {e}")
                continue

        # Filter
        new_jobs = []
        for url, job in all_jobs.items():
            if url in seen_jobs:
                continue
            if not matches_keywords(job['title'], keywords):
                continue
            if matches_exclude_keywords(job['title'], exclude):
                continue

            job['date_found'] = datetime.now().isoformat()
            job['source'] = 'Adzuna'
            job['status'] = 'New'
            job['notes'] = ''

            # Auto-add company if configured
            if self._config.get('auto_add_companies', True) and job.get('company'):
                self._maybe_add_company(job['company'])

            new_jobs.append(job)

        logger.info(f"Adzuna aggregator found {len(new_jobs)} new jobs across {len(keywords)} keywords")
        return new_jobs

    @rate_limit(1, 2)
    def _search_keyword(self, keyword: str) -> List[Dict]:
        """Query Adzuna API for a single keyword. Returns list of job dicts."""
        cfg = self._config
        country = cfg.get('country', 'us')
        results_per_page = cfg.get('results_per_page', 50)
        max_pages = cfg.get('max_pages', 3)

        all_results = []

        for page in range(1, max_pages + 1):
            params = {
                'app_id': cfg['app_id'],
                'app_key': cfg['app_key'],
                'results_per_page': results_per_page,
                'what': keyword,
                'content-type': 'application/json',
            }

            # Add location filter if configured
            locations = config.monitor.get('preferred_locations', [])
            if locations:
                params['where'] = locations[0]  # Adzuna takes one location

            url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

            try:
                resp = self.session.get(url, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()

                results = data.get('results', [])
                if not results:
                    break

                for result in results:
                    all_results.append(self._parse_result(result))

                # Stop if fewer results than requested (last page)
                if len(results) < results_per_page:
                    break

            except Exception as e:
                logger.warning(f"Adzuna API page {page} failed for '{keyword}': {e}")
                break

        logger.debug(f"Adzuna: '{keyword}' returned {len(all_results)} results")
        return all_results

    def _parse_result(self, result: Dict) -> Dict:
        """Convert Adzuna API result to standard job schema."""
        company_name = result.get('company', {}).get('display_name', 'Unknown')
        location = result.get('location', {}).get('display_name', '')

        return {
            'title': result.get('title', '').replace('<strong>', '').replace('</strong>', ''),
            'url': result.get('redirect_url', ''),
            'company': company_name,
            'location': location,
            'department': result.get('category', {}).get('label', ''),
        }

    def _maybe_add_company(self, name: str):
        """Add company to tracker if not already present and auto_add_companies is on."""
        tracker.add_company(
            name=name,
            tier="Tier 3 - Backup",
            sector="Other",
            notes="Auto-added by Adzuna aggregator"
        )


# Global singleton
adzuna_aggregator = AdzunaAggregator()
