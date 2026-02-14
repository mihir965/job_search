"""Email outreach composition and sending."""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from .config import config
from .tracker import tracker
from .llm import llm_generator
from .utils import extract_first_name, is_business_hours, add_business_days, rate_limit

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class EmailOutreach:
    """Handles email composition and sending."""

    def __init__(self):
        self.jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
        self.emails_sent_today = 0
        self.daily_limit = config.outreach.get('daily_email_limit', 12)

    def preview_outreach(self, limit: int = 5):
        """Preview pending outreach emails."""
        # For now, just log a message
        # TODO: Implement after we have contact data
        logger.info("Preview not yet implemented - need to populate contacts first")

    def send_outreach(self, dry_run: bool = False) -> Dict[str, int]:
        """Send pending outreach emails."""
        if not self._check_smtp_configured():
            logger.error("SMTP not configured - cannot send emails")
            return {"sent": 0, "failed": 0, "skipped": 0}

        # Check business hours
        now = datetime.now()
        start_hour = int(config.outreach.get('send_window_start', '08:00').split(':')[0])
        end_hour = int(config.outreach.get('send_window_end', '17:00').split(':')[0])

        if not is_business_hours(now, start_hour, end_hour):
            logger.warning(f"Outside business hours ({start_hour}:00-{end_hour}:00) - skipping send")
            return {"sent": 0, "failed": 0, "skipped": 0}

        # Get pending outreach
        pending = tracker.get_pending_outreach()
        logger.info(f"Found {len(pending)} pending outreach emails")

        stats = {"sent": 0, "failed": 0, "skipped": 0}

        for contact in pending:
            if self.emails_sent_today >= self.daily_limit:
                logger.warning(f"Hit daily limit ({self.daily_limit}) - stopping")
                break

            try:
                success = self._send_email(contact, dry_run=dry_run)
                if success:
                    stats["sent"] += 1
                    self.emails_sent_today += 1
                else:
                    stats["failed"] += 1
            except Exception as e:
                logger.error(f"Failed to send to {contact.get('email')}: {e}")
                stats["failed"] += 1

        return stats

    @rate_limit(3, 5)
    def _send_email(self, contact: Dict, dry_run: bool = False) -> bool:
        """Send a single outreach email."""
        # Compose email
        email_data = self._compose_email(contact)
        if not email_data:
            logger.warning(f"Failed to compose email for {contact.get('name')}")
            return False

        subject, body, email_type, llm_generated = email_data

        if dry_run:
            logger.info(f"[DRY RUN] Would send to {contact.get('email')}:")
            logger.info(f"Subject: {subject}")
            logger.info(f"Body preview: {body[:200]}...")
            return True

        # Send via SMTP
        try:
            self._send_smtp(contact['email'], subject, body)

            # Log to tracker
            tracker.log_outreach({
                'company': contact.get('company'),
                'contact_name': contact.get('name'),
                'contact_email': contact['email'],
                'email_type': email_type,
                'subject': subject,
                'role_referenced': contact.get('role', ''),
                'llm_generated': llm_generated,
                'followup_due': add_business_days(
                    datetime.now(),
                    config.outreach.get('followup_after_days', 5)
                ).isoformat(),
                'notes': ''
            })

            logger.info(f"Sent {email_type} email to {contact.get('name')} at {contact.get('company')}")
            return True

        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return False

    def _compose_email(self, contact: Dict) -> Optional[tuple]:
        """Compose email based on contact type and role."""
        contact_type = contact.get('type', 'Other')
        role = contact.get('role')
        company = contact.get('company')
        first_name = extract_first_name(contact.get('name', ''))

        template_vars = {
            'first_name': first_name,
            'company': company,
            'role': role,
        }

        # Determine email type
        if role:
            # Role-specific email - try LLM first
            llm_email = llm_generator.generate_email(
                hm_name=contact.get('name'),
                hm_title=contact.get('title', ''),
                company=company,
                role_title=role,
                role_url=contact.get('role_url', ''),
                role_description=contact.get('role_description')
            )

            if llm_email:
                subject = f"{role} at {company} – Rutgers MS CS Candidate"
                return (subject, llm_email, "Role-Specific", True)
            else:
                # Fallback to template
                template = self.jinja_env.get_template('role_specific.txt')
                body = template.render(**template_vars)
                subject = f"{role} at {company} – Rutgers MS CS Candidate"
                return (subject, body, "Role-Specific", False)

        elif contact_type == 'Hiring Manager':
            template = self.jinja_env.get_template('cold_hm.txt')
            content = template.render(**template_vars)
            # Extract subject from template (first line)
            lines = content.strip().split('\n')
            subject = lines[0].replace('Subject: ', '')
            body = '\n'.join(lines[2:])  # Skip subject and blank line
            return (subject, body, "Cold HM", False)

        elif contact_type == 'Recruiter':
            template = self.jinja_env.get_template('cold_recruiter.txt')
            content = template.render(**template_vars)
            lines = content.strip().split('\n')
            subject = lines[0].replace('Subject: ', '')
            body = '\n'.join(lines[2:])
            return (subject, body, "Cold Recruiter", False)

        else:
            logger.warning(f"Unknown contact type: {contact_type}")
            return None

    def _send_smtp(self, to_email: str, subject: str, body: str):
        """Send email via SMTP."""
        smtp_config = config.smtp

        msg = MIMEMultipart()
        msg['From'] = f"{smtp_config.get('from_name')} <{smtp_config['user']}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(smtp_config['server'], smtp_config['port'])
        server.starttls()
        server.login(smtp_config['user'], smtp_config['password'])
        server.send_message(msg)
        server.quit()

    def _check_smtp_configured(self) -> bool:
        """Check if SMTP is properly configured."""
        smtp_config = config.smtp
        return bool(smtp_config.get('user') and smtp_config.get('password'))


# Global instance
outreach = EmailOutreach()
