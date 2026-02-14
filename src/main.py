"""CLI entrypoint for job outreach automation."""
import argparse
import logging
import sys
from pathlib import Path

from .utils import setup_logging
from .config import config
from .tracker import tracker
from .monitor import monitor
from .contacts import contact_finder
from .outreach import outreach
from .notify import notifier

logger = logging.getLogger(__name__)


def cmd_init(args):
    """Initialize the tracker Excel file and config template."""
    logger.info("Initializing job search automation...")

    # Create tracker
    tracker.create_tracker()

    # Check if config exists
    config_path = Path("config.yaml")
    if not config_path.exists():
        logger.warning("config.yaml not found. Copy config.example.yaml to config.yaml and fill in your values.")
        logger.info("Example: cp config.example.yaml config.yaml")

    logger.info("✓ Initialization complete!")
    logger.info("")
    logger.info("Next steps:")
    logger.info("1. Copy config.example.yaml to config.yaml")
    logger.info("2. Fill in your SMTP credentials and API keys (optional)")
    logger.info("3. Add careers URLs to the Companies sheet in outreach_tracker.xlsx")
    logger.info("4. Run: python -m src.main monitor")


def cmd_monitor(args):
    """Monitor job boards for new postings."""
    logger.info("Starting job board monitoring...")

    new_jobs = monitor.monitor_all_companies()

    if new_jobs:
        logger.info(f"✓ Found {len(new_jobs)} new matching jobs")

        # Send notification
        if not args.no_notify:
            notifier.send_new_roles_alert(new_jobs)

        # Print summary
        print(f"\nNew jobs found: {len(new_jobs)}")
        for job in new_jobs[:10]:  # Show first 10
            print(f"  - {job['company']}: {job['title']}")
        if len(new_jobs) > 10:
            print(f"  ... and {len(new_jobs) - 10} more")
    else:
        logger.info("No new jobs found")


def cmd_contacts(args):
    """Find contacts for companies."""
    if args.company:
        logger.info(f"Enriching contacts for {args.company}...")
        companies = tracker.get_companies()
        company = next((c for c in companies if c['Company'].lower() == args.company.lower()), None)

        if not company:
            logger.error(f"Company not found: {args.company}")
            return

        contact_finder.enrich_company(company['Company'], company.get('Domain', ''))
    else:
        logger.info("Enriching contacts for all companies...")
        contact_finder.enrich_all_companies()

    logger.info("✓ Contact enrichment complete")


def cmd_outreach(args):
    """Send outreach emails."""
    if args.preview:
        logger.info("Previewing pending outreach...")
        outreach.preview_outreach()

    elif args.send:
        logger.info("Sending outreach emails...")

        # Confirmation
        if not args.yes:
            response = input("Are you sure you want to send emails? (yes/no): ")
            if response.lower() != 'yes':
                logger.info("Cancelled")
                return

        stats = outreach.send_outreach(dry_run=False)
        logger.info(f"✓ Outreach complete: {stats['sent']} sent, {stats['failed']} failed, {stats['skipped']} skipped")

        # Send summary
        if stats['sent'] > 0 and not args.no_notify:
            notifier.send_outreach_summary(stats)

    elif args.followup:
        logger.info("Sending follow-up emails...")
        # TODO: Implement follow-up logic
        logger.warning("Follow-up feature not yet implemented")

    else:
        logger.error("Must specify --preview, --send, or --followup")


def cmd_pipeline(args):
    """Run full pipeline: monitor → contacts → outreach."""
    logger.info("Running full pipeline...")

    # Step 1: Monitor
    logger.info("Step 1: Monitoring job boards...")
    new_jobs = monitor.monitor_all_companies()
    logger.info(f"Found {len(new_jobs)} new jobs")

    # Step 2: Contacts
    logger.info("Step 2: Enriching contacts...")
    contact_finder.enrich_all_companies()

    # Step 3: Outreach
    if args.send:
        logger.info("Step 3: Sending outreach...")
        if not args.yes:
            response = input("Send outreach emails? (yes/no): ")
            if response.lower() != 'yes':
                logger.info("Skipping outreach")
                return

        stats = outreach.send_outreach(dry_run=False)
        logger.info(f"✓ Pipeline complete: {stats['sent']} emails sent")
    else:
        logger.info("Step 3: Preview outreach...")
        outreach.preview_outreach()

    logger.info("✓ Pipeline complete")


def cmd_test_email(args):
    """Test SMTP configuration."""
    logger.info("Testing SMTP configuration...")

    smtp_config = config.smtp
    if not smtp_config.get('user') or not smtp_config.get('password'):
        logger.error("SMTP credentials not configured in config.yaml")
        return

    try:
        import smtplib
        server = smtplib.SMTP(smtp_config['server'], smtp_config['port'])
        server.starttls()
        server.login(smtp_config['user'], smtp_config['password'])
        server.quit()
        logger.info("✓ SMTP configuration is valid")
    except Exception as e:
        logger.error(f"✗ SMTP test failed: {e}")


def cmd_status(args):
    """Print dashboard statistics."""
    logger.info("Fetching status...")

    companies = tracker.get_companies()
    print(f"\n📊 Job Search Status\n")
    print(f"Companies tracked: {len(companies)}")

    # More stats would come from reading the tracker
    # For now, just show basic info
    print("\nFor detailed stats, open outreach_tracker.xlsx")


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Job Outreach Automation - Find jobs and reach out to hiring managers"
    )
    parser.add_argument('--config', type=str, help='Path to config.yaml')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # init
    parser_init = subparsers.add_parser('init', help='Initialize tracker and config')

    # monitor
    parser_monitor = subparsers.add_parser('monitor', help='Monitor job boards')
    parser_monitor.add_argument('--no-notify', action='store_true', help='Don\'t send notification email')

    # contacts
    parser_contacts = subparsers.add_parser('contacts', help='Find hiring manager contacts')
    parser_contacts.add_argument('--company', type=str, help='Specific company to enrich')

    # outreach
    parser_outreach = subparsers.add_parser('outreach', help='Send outreach emails')
    parser_outreach.add_argument('--preview', action='store_true', help='Preview pending emails')
    parser_outreach.add_argument('--send', action='store_true', help='Send pending emails')
    parser_outreach.add_argument('--followup', action='store_true', help='Send follow-up emails')
    parser_outreach.add_argument('--yes', '-y', action='store_true', help='Skip confirmation')
    parser_outreach.add_argument('--no-notify', action='store_true', help='Don\'t send summary email')

    # pipeline
    parser_pipeline = subparsers.add_parser('pipeline', help='Run full pipeline')
    parser_pipeline.add_argument('--send', action='store_true', help='Send emails (default: preview)')
    parser_pipeline.add_argument('--yes', '-y', action='store_true', help='Skip confirmation')

    # test-email
    parser_test = subparsers.add_parser('test-email', help='Test SMTP configuration')

    # status
    parser_status = subparsers.add_parser('status', help='Show dashboard status')

    args = parser.parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose)

    # Load config (if not init command)
    if args.command != 'init':
        if args.config:
            from .config import Config
            global config
            config = Config(args.config)

        # Check if config was loaded
        if not config._loaded:
            logger.error("Config file not found. Run: python -m src.main init")
            sys.exit(1)

        if not config.validate():
            logger.error("Config validation failed")
            sys.exit(1)

    # Dispatch commands
    if args.command == 'init':
        cmd_init(args)
    elif args.command == 'monitor':
        cmd_monitor(args)
    elif args.command == 'contacts':
        cmd_contacts(args)
    elif args.command == 'outreach':
        cmd_outreach(args)
    elif args.command == 'pipeline':
        cmd_pipeline(args)
    elif args.command == 'test-email':
        cmd_test_email(args)
    elif args.command == 'status':
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
