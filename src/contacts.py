"""Contact finding and email enrichment."""
import logging
import re
import smtplib
import dns.resolver
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import requests

from .config import config
from .tracker import tracker
from .utils import rate_limit, generate_email_patterns

logger = logging.getLogger(__name__)

# Known company domains
KNOWN_DOMAINS = {
    "jane street": "janestreet.com",
    "citadel securities": "citadelsecurities.com",
    "citadel": "citadel.com",
    "hudson river trading": "hudsonrivertrading.com",
    "two sigma": "twosigma.com",
    "tower research capital": "tower-research.com",
    "virtu financial": "virtu.com",
    "imc trading": "imc.com",
    "drw": "drw.com",
    "jump trading": "jumptrading.com",
    "de shaw": "deshaw.com",
    "d.e. shaw": "deshaw.com",
    "optiver": "optiver.com",
    "wolverine trading": "wolve.com",
    "akuna capital": "akunacapital.com",
    "five rings": "fiverings.com",
    "cloudflare": "cloudflare.com",
    "databricks": "databricks.com",
}

HM_TITLES = [
    "engineering manager", "head of engineering", "director of engineering",
    "vp engineering", "tech lead", "team lead", "head of infrastructure",
    "head of systems", "head of platform", "engineering lead"
]

RECRUITER_TITLES = [
    "technical recruiter", "talent acquisition", "university recruiter",
    "campus recruiter", "recruiter", "talent partner"
]


class ContactFinder:
    """Finds hiring manager and recruiter contact information."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })

    def enrich_all_companies(self):
        """Find contacts for all companies missing them."""
        companies = tracker.get_companies()
        logger.info(f"Starting contact enrichment for {len(companies)} companies...")

        for company in companies:
            company_name = company['Company']
            domain = company.get('Domain')

            if not domain:
                logger.warning(f"Skipping {company_name} - no domain set")
                continue

            try:
                self.enrich_company(company_name, domain)
            except Exception as e:
                logger.error(f"Failed to enrich {company_name}: {e}")
                continue

    @rate_limit(5, 7)
    def enrich_company(self, company_name: str, domain: str):
        """Find contacts for a single company."""
        logger.info(f"Enriching contacts for {company_name}...")

        contacts = []

        # Try Hunter.io
        hunter_contacts = self._search_hunter(domain)
        contacts.extend(hunter_contacts)

        # Classify and save contacts
        for contact in contacts:
            contact['company'] = company_name
            contact['date_found'] = datetime.now().isoformat()
            tracker.add_contact(contact)

        logger.info(f"Found {len(contacts)} contacts for {company_name}")

    # ── Hunter.io ──

    def _search_hunter(self, domain: str) -> List[Dict]:
        """Search for contacts using Hunter.io."""
        api_key = config.apis.get('hunter_key')
        if not api_key:
            logger.debug("Hunter.io API key not set, skipping")
            return []

        url = "https://api.hunter.io/v2/domain-search"
        params = {
            'domain': domain,
            'api_key': api_key,
            'limit': 10
        }

        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            contacts = []
            for person in data.get('data', {}).get('emails', []):
                position = person.get('position', '').lower()
                contact_type = self._classify_title(position)

                if contact_type != 'Other':
                    contacts.append({
                        'name': f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
                        'title': person.get('position', ''),
                        'email': person.get('value'),
                        'linkedin': person.get('linkedin', ''),
                        'type': contact_type,
                        'source': 'Hunter.io',
                        'confidence': 'High',
                        'email_verified': person.get('confidence', 0) > 80,
                    })

            logger.debug(f"Hunter.io found {len(contacts)} contacts for {domain}")
            return contacts

        except Exception as e:
            logger.warning(f"Hunter.io search failed: {e}")
            return []

    # ── Helpers ──

    def _classify_title(self, title: str) -> str:
        """Classify a job title as HM, Recruiter, Engineer, or Other."""
        title_lower = title.lower()

        for hm_title in HM_TITLES:
            if hm_title in title_lower:
                return 'Hiring Manager'

        for rec_title in RECRUITER_TITLES:
            if rec_title in title_lower:
                return 'Recruiter'

        if 'engineer' in title_lower or 'developer' in title_lower:
            return 'Engineer'

        return 'Other'

    def verify_email_smtp(self, email: str) -> bool:
        """Verify email exists using SMTP RCPT TO command."""
        domain = email.split('@')[1]

        try:
            # Get MX record
            mx_records = dns.resolver.resolve(domain, 'MX')
            mx_host = str(mx_records[0].exchange)

            # Connect to SMTP server
            server = smtplib.SMTP(timeout=10)
            server.set_debuglevel(0)
            server.connect(mx_host)
            server.helo()
            server.mail('verify@example.com')
            code, _ = server.rcpt(email)
            server.quit()

            # 250 = mailbox exists
            return code == 250

        except Exception as e:
            logger.debug(f"SMTP verification failed for {email}: {e}")
            return False

    def guess_email(self, first_name: str, last_name: str, domain: str) -> Optional[str]:
        """Guess email using common patterns and SMTP verification."""
        patterns = generate_email_patterns(first_name, last_name, domain)

        # Try SMTP verification for each pattern
        for pattern in patterns:
            if self.verify_email_smtp(pattern):
                logger.info(f"Verified email: {pattern}")
                return pattern

        # If SMTP verification didn't work, return most common pattern
        return patterns[0] if patterns else None


# Global instance
contact_finder = ContactFinder()
