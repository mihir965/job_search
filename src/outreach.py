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
        """Send pending outreach emails. LLM-generated emails go to draft queue instead."""
        if not self._check_smtp_configured():
            logger.error("SMTP not configured - cannot send emails")
            return {"sent": 0, "failed": 0, "skipped": 0, "drafted": 0}

        # Check business hours
        now = datetime.now()
        start_hour = int(config.outreach.get('send_window_start', '08:00').split(':')[0])
        end_hour = int(config.outreach.get('send_window_end', '17:00').split(':')[0])

        if not is_business_hours(now, start_hour, end_hour):
            logger.warning(f"Outside business hours ({start_hour}:00-{end_hour}:00) - skipping send")
            return {"sent": 0, "failed": 0, "skipped": 0, "drafted": 0}

        # Get pending outreach
        pending = tracker.get_pending_outreach()
        logger.info(f"Found {len(pending)} pending outreach emails")

        stats = {"sent": 0, "failed": 0, "skipped": 0, "drafted": 0}

        for contact in pending:
            if self.emails_sent_today >= self.daily_limit:
                logger.warning(f"Hit daily limit ({self.daily_limit}) - stopping")
                break

            try:
                email_data = self._compose_email(contact)
                if not email_data:
                    logger.warning(f"Failed to compose email for {contact.get('name')}")
                    stats["failed"] += 1
                    continue

                subject, body, email_type, llm_generated = email_data

                # Route LLM-generated emails to draft queue for review
                if llm_generated:
                    tracker.save_draft({
                        'company': contact.get('company'),
                        'contact_name': contact.get('name'),
                        'contact_email': contact.get('email'),
                        'email_type': email_type,
                        'subject': subject,
                        'body': body,
                        'role_referenced': contact.get('role', ''),
                        'notes': '[LLM-generated]',
                    })
                    stats["drafted"] += 1
                    logger.info(f"Drafted LLM email for {contact.get('name')} at {contact.get('company')}")
                    continue

                # Template emails: send immediately
                if dry_run:
                    logger.info(f"[DRY RUN] Would send to {contact.get('email')}: {subject}")
                    stats["sent"] += 1
                    continue

                success = self._send_composed_email(
                    contact, subject, body, email_type, llm_generated
                )
                if success:
                    stats["sent"] += 1
                    self.emails_sent_today += 1
                else:
                    stats["failed"] += 1

            except Exception as e:
                logger.error(f"Failed to process {contact.get('email')}: {e}")
                stats["failed"] += 1

        return stats

    @rate_limit(3, 5)
    def _send_composed_email(self, contact: Dict, subject: str, body: str,
                              email_type: str, llm_generated: bool) -> bool:
        """Send a composed email via SMTP and log to tracker."""
        try:
            self._send_smtp(contact['email'], subject, body)

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

    def send_approved_drafts(self, dry_run: bool = False) -> Dict[str, int]:
        """Send all approved drafts from the draft queue."""
        if not dry_run and not self._check_smtp_configured():
            logger.error("SMTP not configured - cannot send emails")
            return {"sent": 0, "failed": 0}

        approved = tracker.get_approved_drafts()
        logger.info(f"Found {len(approved)} approved drafts to send")

        stats = {"sent": 0, "failed": 0}

        for draft in approved:
            if self.emails_sent_today >= self.daily_limit:
                logger.warning(f"Hit daily limit ({self.daily_limit}) - stopping")
                break

            if dry_run:
                logger.info(f"[DRY RUN] Would send to {draft.get('Contact Email')}: {draft.get('Subject Line')}")
                stats["sent"] += 1
                continue

            try:
                self._send_smtp(draft['Contact Email'], draft['Subject Line'], draft['Body'])

                # Log to outreach log
                tracker.log_outreach({
                    'company': draft.get('Company'),
                    'contact_name': draft.get('Contact Name'),
                    'contact_email': draft['Contact Email'],
                    'email_type': draft.get('Email Type', 'Role-Specific'),
                    'subject': draft['Subject Line'],
                    'role_referenced': draft.get('Role Referenced', ''),
                    'llm_generated': True,
                    'followup_due': add_business_days(
                        datetime.now(),
                        config.outreach.get('followup_after_days', 5)
                    ).isoformat(),
                    'notes': '[LLM-generated, approved]'
                })

                # Mark draft as sent
                tracker.mark_draft_sent(draft['_row'])
                stats["sent"] += 1
                self.emails_sent_today += 1
                logger.info(f"Sent approved draft to {draft.get('Contact Name')} at {draft.get('Company')}")

            except Exception as e:
                logger.error(f"Failed to send draft to {draft.get('Contact Email')}: {e}")
                stats["failed"] += 1

        return stats

    def review_drafts(self):
        """Print all pending drafts to terminal for review."""
        pending = tracker.get_pending_drafts()

        if not pending:
            print("\nNo pending drafts to review.")
            return

        print(f"\n{'='*60}")
        print(f"  {len(pending)} Pending Email Drafts")
        print(f"{'='*60}\n")

        for i, draft in enumerate(pending, 1):
            print(f"--- Draft #{i} (Row {draft['_row']}) ---")
            print(f"To:      {draft.get('Contact Name')} <{draft.get('Contact Email')}>")
            print(f"Company: {draft.get('Company')}")
            print(f"Type:    {draft.get('Email Type')}")
            print(f"Role:    {draft.get('Role Referenced', 'N/A')}")
            print(f"Subject: {draft.get('Subject Line')}")
            print(f"\n{draft.get('Body', '')}\n")
            print(f"{'- '*30}")

        print(f"\nTo approve all: python -m src.main outreach --approve-all")
        print(f"To send approved: python -m src.main outreach --send-approved")

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
