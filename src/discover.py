"""Board discovery — probes Greenhouse + Ashby APIs with token variations."""
import logging
import re
from typing import List, Dict, Optional, Tuple
import requests

from .config import config
from .tracker import tracker
from .utils import rate_limit, normalize_company_name

logger = logging.getLogger(__name__)

# Common token patterns: company name variations used as board slugs
def _generate_tokens(company_name: str) -> List[str]:
    """Generate possible board token variations from a company name."""
    name = company_name.lower().strip()

    # Remove common suffixes
    for suffix in [' inc', ' llc', ' ltd', ' corp', ' co', ' group', ' capital',
                   ' trading', ' financial', ' securities', ' partners']:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()

    tokens = set()

    # As-is (spaces removed)
    tokens.add(name.replace(' ', ''))
    # Hyphenated
    tokens.add(name.replace(' ', '-'))
    # Underscored
    tokens.add(name.replace(' ', '_'))
    # Camel-ish
    tokens.add(name.replace(' ', ''))
    # First word only
    first_word = name.split()[0] if name.split() else name
    tokens.add(first_word)
    # Initials (for multi-word names)
    words = name.split()
    if len(words) > 1:
        tokens.add(''.join(w[0] for w in words))

    # Remove empty strings
    tokens.discard('')
    return list(tokens)


class BoardDiscoverer:
    """Probes Greenhouse and Ashby APIs to discover board URLs for companies."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })

    def discover_all(self, company_names: List[str] = None) -> List[Dict]:
        """Discover board URLs for companies without a Careers URL.

        Args:
            company_names: Optional list of company names to probe.
                           If None, uses all companies from tracker missing a Careers URL.

        Returns:
            List of dicts with company, board_type, careers_url, token.
        """
        if company_names is None:
            companies = tracker.get_companies()
            company_names = [
                c['Company'] for c in companies
                if not c.get('Careers URL')
            ]

        if not company_names:
            logger.info("All companies already have Careers URLs")
            return []

        logger.info(f"Probing boards for {len(company_names)} companies...")
        results = []

        for name in company_names:
            try:
                result = self._probe_company(name)
                if result:
                    results.append(result)
                    logger.info(f"Found {result['board_type']} board for {name}: {result['careers_url']}")

                    # Update tracker
                    tracker.update_company_url(
                        name, result['careers_url'], result['board_type']
                    )
                else:
                    logger.info(f"No board found for {name}")
            except Exception as e:
                logger.error(f"Failed to probe {name}: {e}")

        return results

    def _probe_company(self, company_name: str) -> Optional[Dict]:
        """Try Greenhouse then Ashby for a single company."""
        tokens = _generate_tokens(company_name)

        # Try Greenhouse first (more common)
        for token in tokens:
            result = self._try_greenhouse(token, company_name)
            if result:
                return result

        # Try Ashby
        for token in tokens:
            result = self._try_ashby(token, company_name)
            if result:
                return result

        return None

    @rate_limit(1, 2)
    def _try_greenhouse(self, token: str, company_name: str) -> Optional[Dict]:
        """Probe Greenhouse API with a token."""
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

        try:
            resp = self.session.get(api_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                job_count = len(data.get('jobs', []))
                if job_count > 0:
                    return {
                        'company': company_name,
                        'board_type': 'Greenhouse',
                        'careers_url': f"https://boards.greenhouse.io/{token}",
                        'token': token,
                        'job_count': job_count,
                    }
        except Exception:
            pass
        return None

    @rate_limit(1, 2)
    def _try_ashby(self, token: str, company_name: str) -> Optional[Dict]:
        """Probe Ashby API with a token."""
        api_url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"

        try:
            resp = self.session.get(api_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                job_count = len(data.get('jobs', []))
                if job_count > 0:
                    return {
                        'company': company_name,
                        'board_type': 'Ashby',
                        'careers_url': f"https://jobs.ashbyhq.com/{token}",
                        'token': token,
                        'job_count': job_count,
                    }
        except Exception:
            pass
        return None


# Global singleton
board_discoverer = BoardDiscoverer()
