# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Initialize tracker Excel + see next steps
python -m src.main init

# Core commands (require config.yaml with at least profile + smtp)
python -m src.main discover-boards              # Probe Greenhouse/Ashby APIs for board URLs
python -m src.main discover-boards --input f.txt # Probe companies from file (one per line)
python -m src.main monitor                       # Scrape Greenhouse + Ashby boards
python -m src.main contacts --all                # Enrich contacts for all companies
python -m src.main contacts --company "Name"     # Single company
python -m src.main outreach --preview            # Preview pending emails
python -m src.main outreach --send               # Send emails (requires confirmation)
python -m src.main outreach --send -y            # Send without confirmation
python -m src.main pipeline                      # monitor -> contacts -> outreach --preview
python -m src.main pipeline --send               # Full pipeline with sending
python -m src.main pipeline --send -y            # Full pipeline, no confirmation
python -m src.main test-email                    # Verify SMTP works
python -m src.main status                        # Print dashboard stats
python -m src.main status --notify               # Print stats + send digest email

# Systemd timers (CachyOS)
bash scripts/setup-timers.sh                     # Install & enable timers
systemctl --user list-timers                     # Check timer schedules

# All commands support: --config path/to/config.yaml  --verbose/-v
```

Python 3.11+ required. No test suite exists yet — `tests/` directory is empty.

## Architecture

**Pipeline flow:** Job Monitor (Greenhouse + Ashby only) -> Contact Finder (Hunter.io + email guessing) -> Email Outreach (template-based)

**Single source of truth:** `outreach_tracker.xlsx` (4 sheets) + `seen_jobs.json` for dedup. No database.

**Key pattern — Global singletons:** Every module exposes a module-level singleton instance (`config`, `tracker`, `monitor`, `contact_finder`, `outreach`, `notifier`, `board_discoverer`). These are imported directly (e.g., `from .tracker import tracker`).

**Critical constraint — `tracker.py` is the ONLY module that touches Excel.** All other modules call tracker functions. Uses `filelock` to prevent concurrent write corruption.

**Config resolution:** `config.py` loads `config.yaml`, resolves `${ENV_VAR}` references from environment (or `.env` via python-dotenv), exposes properties for each section. Singleton pattern — first instantiation wins.

**Rate limiting:** `@rate_limit(min, max)` decorator in `utils.py` adds randomized `time.sleep` after each call. Applied to scraping and email sending methods.

**Job board scrapers** (`monitor.py`): Greenhouse (JSON API) and Ashby (JSON API) ONLY. Board type auto-detected from URL or read from Companies sheet. Companies with unsupported board types are skipped.

**Board discovery** (`discover.py`): Probes Greenhouse and Ashby APIs with company name token variations to find board URLs for companies that don't have one.

**Email composition** (`outreach.py`): Template-based only (no LLM). Uses Jinja2 templates from `templates/`. Three types: cold_hm, cold_recruiter, role_specific. Subject lines are embedded in template files (first line).

**Digest notifications** (`notify.py`): Sends HTML email digest grouped by tier -> company -> roles using `templates/digest.html`.

**Systemd timers** (`systemd/`): 2 user-level timers — monitor (every 6h, runs full pipeline) and outreach (weekdays 9AM, catch-up send). Setup via `scripts/setup-timers.sh`.

## Directory Structure

```
job_search/
├── src/
│   ├── main.py          # CLI (7 subcommands: init, monitor, contacts, outreach, pipeline, discover-boards, status)
│   ├── config.py         # Config loading + validation
│   ├── tracker.py        # Excel I/O (4 sheets: Companies, New Roles, Contacts, Outreach Log)
│   ├── monitor.py        # Greenhouse + Ashby scraping ONLY
│   ├── contacts.py       # Hunter.io + email pattern guessing
│   ├── outreach.py       # Template-based sending (no LLM)
│   ├── notify.py         # HTML digest notifications
│   ├── discover.py       # Board URL discovery (probes Greenhouse + Ashby APIs)
│   └── utils.py          # Helpers (logging, rate limiting, keyword matching, scoring)
├── templates/
│   ├── cold_hm.txt       # Cold email to hiring manager
│   ├── cold_recruiter.txt # Cold email to recruiter
│   ├── role_specific.txt  # Template for role-matched outreach
│   ├── digest.html        # Tier-grouped role digest email
│   └── notification.html  # Generic HTML notification template
├── systemd/               # 2 timers (monitor + outreach)
├── scripts/
│   └── setup-timers.sh    # Install systemd timers
└── tests/
```

## Excel Tracker (4 sheets)

1. **Companies** — Target list: Company, Tier, Sector, Careers URL, Board Type (Greenhouse/Ashby/Other), Sponsors H-1B, Domain, Notes
2. **New Roles** — Found jobs: Date Found, Company, Role Title, Location, URL, Department, Board Type, Status, HM Name, HM Email, Outreach Sent?, Notes
3. **Contacts** — Discovered HMs and recruiters: Company, Name, Title, Email, LinkedIn, Type, Source, Confidence, Email Verified, Date Found
4. **Outreach Log** — 9 columns: Date Sent, Company, Contact Name, Contact Email, Email Type, Subject Line, Role Referenced, Status, Notes

## What was removed (simplified)

- LLM email personalization (`llm.py`, Anthropic API)
- Adzuna job aggregator (`aggregator.py`)
- Lever, Workday, Generic HTML scrapers
- Email draft queue (Email Drafts sheet)
- Global Tracker sheet and Dashboard sheet
- Follow-up system
- Apollo.io integration stub
