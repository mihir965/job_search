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
python -m src.main monitor                    # Scrape career pages + Adzuna
python -m src.main monitor --no-aggregators   # Skip Adzuna, scrape career pages only
python -m src.main monitor --aggregators-only # Only run Adzuna aggregator
python -m src.main contacts --all             # Enrich contacts for all companies
python -m src.main contacts --company "Name"  # Single company
python -m src.main outreach --preview         # Preview pending emails
python -m src.main outreach --send            # Send (LLM emails go to draft queue)
python -m src.main outreach --send -y         # Send without confirmation
python -m src.main outreach --review-drafts   # Review pending LLM-generated drafts
python -m src.main outreach --approve-all     # Approve all pending drafts
python -m src.main outreach --send-approved   # Send approved drafts
python -m src.main pipeline                   # monitor → contacts → outreach --preview
python -m src.main pipeline --send            # Full pipeline with sending
python -m src.main test-email                 # Verify SMTP works
python -m src.main status                     # Print dashboard stats
python -m src.main status --notify            # Print stats + send digest email

# Systemd timers (CachyOS)
bash scripts/setup-timers.sh                  # Install & enable all timers
systemctl --user list-timers                  # Check timer schedules

# All commands support: --config path/to/config.yaml  --verbose/-v
```

Python 3.11+ required (venv uses 3.14). No test suite exists yet — `tests/` directory is empty.

## Architecture

**Pipeline flow:** Job Monitor (scraper) → Contact Finder (enricher) → Email Outreach (sender)

**Single source of truth:** `outreach_tracker.xlsx` — all state lives here plus `seen_jobs.json` for dedup. No database.

**Key pattern — Global singletons:** Every module exposes a module-level singleton instance (`config`, `tracker`, `monitor`, `contact_finder`, `outreach`, `llm_generator`, `notifier`, `adzuna_aggregator`). These are imported directly (e.g., `from .tracker import tracker`).

**Critical constraint — `tracker.py` is the ONLY module that touches Excel.** All other modules call tracker functions. Uses `filelock` to prevent concurrent write corruption.

**Config resolution:** `config.py` loads `config.yaml`, resolves `${ENV_VAR}` references from environment (or `.env` via python-dotenv), exposes properties for each section. Singleton pattern — first instantiation wins.

**Rate limiting:** `@rate_limit(min, max)` decorator in `utils.py` adds randomized `time.sleep` after each call. Applied to scraping and email sending methods.

**Job board scrapers** (`monitor.py`): Greenhouse (JSON API), Lever (HTML), Ashby (JSON API), Workday (stub — not implemented), Generic HTML fallback. Board type auto-detected from URL or read from Companies sheet.

**Email composition** (`outreach.py`): Uses Jinja2 templates from `templates/`. For role-specific emails, tries LLM generation first (`llm.py` via Anthropic API), falls back to template. Subject lines are embedded in template files (first line).

**Email draft queue:** LLM-generated emails go to an "Email Drafts" sheet for review before sending. Template emails still send immediately. Drafts flow: compose → save_draft → review → approve → send_approved.

**Adzuna aggregator** (`aggregator.py`): Searches Adzuna job API across all config keywords, auto-adds unknown companies. Runs as part of `monitor` unless `--no-aggregators`.

**Systemd timers** (`systemd/`): 4 user-level timers for monitor (6h), contacts (daily 7AM), outreach (weekdays 9AM, sends approved drafts), status (daily 6PM). Setup via `scripts/setup-timers.sh`.

**Incomplete/stub areas:** Workday scraper, Apollo.io integration, follow-up sending, `get_pending_outreach()`, `get_due_followups()`, Dashboard "this week" formula, `--daemon` mode for monitor.

---

# Job Outreach Automation System — Project Specification

## Who is this for

Mihir Kulkarni — MS CS student at Rutgers (graduating May 2026). Targeting systems engineering / quantitative developer roles at HFT firms (Jane Street, Citadel Securities, Two Sigma, Hudson River Trading, Tower Research, etc.) and systems-focused tech companies. International student requiring H-1B sponsorship.

## Project Overview

An automated pipeline that:
1. **Monitors** job boards for new relevant postings
2. **Tracks** everything in a central Excel workbook
3. **Finds** hiring manager and recruiter contact info automatically
4. **Sends** cold outreach emails, including LLM-personalized emails for specific roles

The system should be runnable from cron or as a daemon on a Linux machine. All state lives in a single Excel tracker file and a JSON state file. No database required.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CRON / DAEMON                            │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────┐  │
│  │  Job Monitor  │───▶│Contact Finder│───▶│  Email Outreach   │  │
│  │  (scraper)    │    │  (enricher)  │    │  (sender)         │  │
│  └──────┬───────┘    └──────┬───────┘    └───────┬───────────┘  │
│         │                   │                    │              │
│         ▼                   ▼                    ▼              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              Excel Tracker (single source of truth)      │    │
│  │                                                         │    │
│  │  Sheet: "New Roles"       — scraped jobs, to-do queue   │    │
│  │  Sheet: "Global Tracker"  — master list, all statuses   │    │
│  │  Sheet: "Contacts"        — HMs, recruiters, emails     │    │
│  │  Sheet: "Outreach Log"    — every email sent + status   │    │
│  │  Sheet: "Companies"       — target company config       │    │
│  │  Sheet: "Email Templates" — base templates              │    │
│  │  Sheet: "Dashboard"       — auto-calculated metrics     │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌──────────────┐    ┌──────────────────────────────────────┐   │
│  │  seen_jobs.   │    │  config.yaml                         │   │
│  │  json         │    │  (API keys, SMTP, preferences)       │   │
│  └──────────────┘    └──────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
job_search/
├── CLAUDE.md                  # This file
├── config.yaml                # All configuration (API keys, SMTP, preferences)
├── config.example.yaml        # Template config (committed to git, no secrets)
├── requirements.txt           # Python dependencies
├── seen_jobs.json             # State: previously seen job postings (auto-generated)
├── outreach_tracker.xlsx      # THE tracker — single source of truth
│
├── src/
│   ├── __init__.py
│   ├── main.py                # CLI entrypoint — orchestrates everything
│   ├── config.py              # Load and validate config.yaml
│   ├── tracker.py             # All Excel read/write operations (centralized)
│   ├── monitor.py             # Job board scraping
│   ├── contacts.py            # Contact/email finding + enrichment
│   ├── outreach.py            # Email composition + sending
│   ├── llm.py                 # LLM integration for email personalization
│   ├── notify.py              # Notification emails (alerts to Mihir)
│   └── utils.py               # Shared helpers (logging, rate limiting, etc.)
│
├── templates/
│   ├── cold_hm.txt            # Cold email to hiring manager
│   ├── cold_recruiter.txt     # Cold email to recruiter
│   ├── role_specific.txt      # Template for role-matched outreach (LLM fills in)
│   ├── followup.txt           # Follow-up template
│   └── notification.html      # HTML template for alert emails to Mihir
│
└── tests/
    ├── test_monitor.py
    ├── test_contacts.py
    ├── test_outreach.py
    └── test_tracker.py
```

---

## config.yaml Structure

```yaml
# ── Mihir's Profile (used in email templates and LLM prompts) ──
profile:
  name: "Mihir Kulkarni"
  email: "mihir.atul.kulkarni@gmail.com"
  phone: "(510) 909-6142"
  github: "https://github.com/mihir965"
  linkedin: "https://www.linkedin.com/in/mihiratulkulkarni/"
  graduation: "May 2026"
  university: "Rutgers University New Brunswick"
  degree: "MS Computer Science"
  # Key talking points for emails — the LLM and templates pull from these
  highlights:
    - "Concurrent TCP server in C with sub-3ms p95 latency (epoll, non-blocking I/O)"
    - "Preemptive threading library with MLFQ and CFS schedulers (C, POSIX)"
    - "FPGA research with Prof. Richard Martin — hardware-software interface"
    - "Isometric game engine in C++/OpenGL — 120 FPS, 10K+ tiles"
    - "Production experience: serverless ETL pipelines at Syngenta (Python, AWS Glue, Redshift)"
    - "Full-stack SaaS development at UniteGPS (MERN, React Native)"
  target_roles:
    - "Systems Engineer"
    - "Software Engineer (C/C++)"
    - "Quantitative Developer"
    - "Infrastructure Engineer"
    - "Platform Engineer"
    - "Low Latency Developer"
    - "Software Development Engineer"
    - "Full-stack Engineer"
    - "Backend Engineer"

# ── SMTP ──
smtp:
  server: "smtp.gmail.com"
  port: 587
  user: "${SMTP_USER}"           # Resolve from env var
  password: "${SMTP_PASSWORD}"   # Gmail App Password
  from_name: "Mihir Kulkarni"

# ── API Keys (all optional — system degrades gracefully) ──
apis:
  hunter_key: "${HUNTER_API_KEY}"      # https://hunter.io — 25 free/month
  apollo_key: "${APOLLO_API_KEY}"      # https://apollo.io — 50 free/month
  anthropic_key: "${ANTHROPIC_API_KEY}" # For LLM email personalization

# ── Job Monitoring ──
monitor:
  check_interval_hours: 6
  search_keywords:
    - "systems engineer"
    - "software engineer"
    - "c++"
    - "infrastructure engineer"
    - "low latency"
    - "platform engineer"
    - "quantitative developer"
    - "trading systems"
    - "backend engineer"
    - "distributed systems"
    - "linux engineer"
    - "fpga"
    - "embedded"
  exclude_keywords:
    - "staff"
    - "principal"
    - "director"
    - "vp "
    - "vice president"
    - "10+ years"
    - "8+ years"
    - "manager"             # Exclude "engineering manager" as a ROLE to apply for
    - "senior staff"
  # Filter by location if desired (empty = all locations)
  preferred_locations:
    - "New York"
    - "New Jersey"
    - "Chicago"
    - "Remote"
    - "San Francisco"
    - "Boston"

# ── Outreach ──
outreach:
  daily_email_limit: 12          # Stay well under spam thresholds
  followup_after_days: 5         # Business days
  max_followups: 2               # Don't be annoying
  send_window_start: "08:00"     # Only send during business hours EST
  send_window_end: "17:00"
  timezone: "America/New_York"

# ── LLM Personalization ──
llm:
  model: "claude-sonnet-4-20250514"
  # If false, only sends templated emails (no API calls)
  enabled: true
  # Max tokens for email generation
  max_tokens: 500
  # System prompt is defined in src/llm.py — don't put it here
```

---

## Module Specifications

### `src/config.py`
- Load `config.yaml`, resolve `${ENV_VAR}` references from environment
- Validate required fields, provide sensible defaults
- Expose a singleton `Config` object importable everywhere
- If a key is missing but has a default, log a warning — don't crash

### `src/tracker.py` — THE critical module
This is the ONLY module that reads/writes the Excel file. Every other module calls functions here.

**Why centralized:** Prevents concurrent write corruption, keeps Excel logic in one place, makes testing easier.

Key functions:
```python
# ── Reading ──
get_companies() -> list[dict]                    # All companies from Companies sheet
get_new_roles() -> list[dict]                    # Unprocessed roles from New Roles sheet
get_contacts_needing_enrichment() -> list[dict]  # Companies without HM email
get_pending_outreach() -> list[dict]             # Contacts who haven't been emailed
get_due_followups() -> list[dict]                # Outreach past followup_after_days with no reply

# ── Writing ──
add_new_roles(roles: list[dict])                 # Append to New Roles sheet
add_to_global_tracker(role: dict)                # Append to Global Tracker
update_contact(company: str, contact: dict)      # Write HM/recruiter info to Companies sheet
log_outreach(entry: dict)                        # Append to Outreach Log
update_outreach_status(row: int, status: str)    # Update status of sent email
```

**Important rules for this module:**
- Always use `openpyxl`, never pandas for writes (preserves formatting/formulas)
- Use file locking (`fcntl.flock` or `filelock` library) to prevent corruption if two processes touch the file
- Never delete rows — only append or update in place
- If the Excel file doesn't exist, create it with all sheets and headers

### `src/monitor.py` — Job Board Scraper

Scrapes career pages and identifies new relevant postings.

**Supported job board types:**
- **Greenhouse** — Use their public JSON API: `https://boards-api.greenhouse.io/v1/boards/{token}/jobs`. Extract board token from URL. This is the most reliable method.
- **Lever** — Scrape HTML. Postings are in `.posting` divs with `.posting-title h5` for title.
- **Ashby** — API endpoint: `https://api.ashbyhq.com/posting-api/job-board/{token}`. Returns JSON.
- **Workday** — These are hard to scrape. Use the search API pattern: `https://{company}.wd5.myworkdayjobs.com/wday/cxs/{company}/External/jobs`. POST with `{"limit":20,"offset":0,"searchText":""}`.
- **Generic HTML** — Fallback: request the page, look for `<a>` tags with href containing "job", "career", "position", "apply". Filter by keyword match.

**Flow:**
1. Load companies from tracker (via `tracker.get_companies()`)
2. For each company with a careers URL:
   a. Detect board type (from config or URL pattern)
   b. Scrape all listings
   c. Filter by `search_keywords` match on title (case-insensitive, any keyword matches)
   d. Exclude by `exclude_keywords`
   e. Optionally filter by `preferred_locations`
   f. Check against `seen_jobs.json` — skip already-seen
   g. New matches → add to `seen_jobs.json`, call `tracker.add_new_roles()` and `tracker.add_to_global_tracker()`
3. If new roles found, call `notify.send_new_roles_alert()` with the list. I would prefer if not sending all the time, send in batches, I will sit down to apply once per day
4. Rate limit: 2-second delay between companies, 5-second delay if a request fails

**Job data schema:**
```python
{
    "company": str,
    "title": str,
    "url": str,                  # Direct link to the posting
    "location": str,
    "department": str,
    "date_found": str,           # ISO format
    "source": str,               # "Greenhouse API", "Lever HTML", etc.
    "status": "New",             # New | Applied | Emailed HM | Interviewing | Rejected | Offer
    "notes": ""
}
```

### `src/contacts.py` — Contact Finder & Email Enrichment

Finds hiring manager and recruiter emails. Uses multiple methods chained together.

**Method priority (try in order, stop when you have high-confidence results):**

1. **Hunter.io domain search** (`/v2/domain-search`) — Returns people at a domain with titles and emails. Filter by title matching `HM_TITLES` or `RECRUITER_TITLES`. If API key not set, skip.

2. **Apollo.io people search** (`/v1/mixed_people/search`) — Search by company name + title. If API key not set, skip.

3. **Google scraping** — Search `site:linkedin.com/in "{company}" "{title}"`. Parse name from LinkedIn result title (pattern: `"FirstName LastName - Title - Company | LinkedIn"`). Also search `"@{domain}" "engineering" OR "recruiter"` for exposed emails.

4. **Email pattern guessing + SMTP verification** — For contacts found via LinkedIn without emails:
   a. Generate candidates using common patterns: `first.last@`, `firstlast@`, `flast@`, `first_last@`, `first@`
   b. Look up MX record via `dns.resolver`
   c. Try SMTP `RCPT TO` verification (returns 250 if mailbox exists)
   d. If SMTP is inconclusive (catch-all server), default to `first.last@domain.com`

**Known company domains** — Hardcode these because they're not always guessable:
```python
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
    "optiver": "optiver.com",
    "wolverine trading": "wolve.com",
    "akuna capital": "akunacapital.com",
    "five rings": "fiverings.com",
    "cloudflare": "cloudflare.com",
    "databricks": "databricks.com",
}
```

**Target titles for hiring managers:**
```python
HM_TITLES = [
    "engineering manager", "head of engineering", "director of engineering",
    "vp engineering", "tech lead", "team lead", "head of infrastructure",
    "head of systems", "head of platform",
]
```

**Target titles for recruiters:**
```python
RECRUITER_TITLES = [
    "technical recruiter", "talent acquisition", "university recruiter",
    "campus recruiter", "recruiter",
]
```

**Flow:**
1. `tracker.get_contacts_needing_enrichment()` → list of companies without HM emails
2. For each company, run the methods above
3. Write best HM and best recruiter to tracker via `tracker.update_contact()`
4. Also populate the Contacts sheet with ALL found contacts (not just the best one)
5. Rate limit: 3-5 seconds between Google searches, 5 seconds between companies

**Contact data schema:**
```python
{
    "name": str,
    "title": str,
    "email": str,
    "linkedin": str,
    "company": str,
    "source": str,           # "Hunter.io", "Apollo.io", "Google/LinkedIn", "Email pattern guess"
    "confidence": str,       # "high", "medium", "low"
    "email_verified": bool,
    "date_found": str
}
```

### `src/outreach.py` — Email Composition & Sending

Handles all outbound email logic.

**Email types:**
1. **Cold generic** — Uses templates from `templates/cold_hm.txt` or `templates/cold_recruiter.txt`. Simple Jinja2 variable substitution (`{{ company }}`, `{{ first_name }}`, `{{ role }}`).
2. **Role-specific** — When a new role is found AND we have the HM email, use the LLM to personalize the email. Falls back to template if LLM is disabled or fails.
3. **Follow-up** — Sent `followup_after_days` business days after initial email if no reply. Uses `templates/followup.txt`.

**Critical safety rules:**
- ALWAYS preview before first send (require `--send` flag + "yes" confirmation)
- Enforce `daily_email_limit` from config (default 12)
- Only send during `send_window_start` to `send_window_end` (business hours EST)
- Never email the same person twice about the same role
- Never email someone who has status "Replied" or "Meeting Scheduled"
- Log EVERY email to the Outreach Log sheet via `tracker.log_outreach()`
- If SMTP fails, log the error and continue — don't crash the whole batch

**Sending flow:**
1. Get pending outreach from tracker
2. For each contact:
   a. Check if within daily limit
   b. Check if within send window
   c. Compose email (template or LLM-personalized)
   d. Send via SMTP
   e. Log to tracker
3. Report summary: sent / failed / skipped

### `src/llm.py` — LLM Email Personalization

Uses the Anthropic API to generate personalized outreach emails when a specific role is being referenced.

**When to use LLM:**
- A new role was found via the monitor
- We have the HM's email
- The email is about a SPECIFIC role (not just a generic intro)
- `llm.enabled` is true in config

**System prompt for the LLM:**
```
You are helping Mihir Kulkarni write a brief, professional cold email to a hiring manager about a specific job opening.

About Mihir:
- MS CS student at Rutgers, graduating May 2026
- Focused on systems programming in C/C++
- Key projects: concurrent TCP server (sub-3ms p95 latency, epoll), preemptive threading library (MLFQ, CFS schedulers), FPGA research, C++/OpenGL game engine
- Production experience: data pipelines at Syngenta (Python, AWS), full-stack SaaS at UniteGPS (MERN)
- Targeting systems/infrastructure/quant developer roles
- Requires H-1B sponsorship (do NOT mention this in the email)
- Refer to the base resume that I have in the project directory if needed

Rules:
- Keep the email under 150 words
- Be genuine and specific — mention 1-2 things about the role that connect to Mihir's experience
- Do NOT be overly formal or use corporate buzzwords
- Do NOT mention visa/sponsorship
- Do NOT use phrases like "I am writing to express my interest" or "I believe I would be a great fit"
- End with a soft ask: "Would you have 15 minutes to chat this week?"
- Include github.com/mihir965 at the bottom
- The tone should sound like a confident peer reaching out, not a desperate applicant
- Match the most relevant 1-2 highlights from Mihir's experience to the specific role requirements
```

**User prompt template:**
```
Write a cold email from Mihir to {hm_name} ({hm_title}) at {company} about this role:

Role: {role_title}
Role URL: {role_url}
Role Description (if available): {role_description_snippet}

Mihir's relevant highlights:
{relevant_highlights}

Output ONLY the email body — no subject line, no "Subject:", no commentary.
```

**Important:**
- If the API call fails, fall back to the `role_specific.txt` template
- Cache the generated email text so we can log it and review later
- Add a `[LLM-generated]` tag in the outreach log notes column so Mihir knows which emails were auto-written
- Truncate role description to ~300 words if it's very long

### `src/notify.py` — Notifications to Mihir

Sends HTML email alerts to Mihir when things happen.

**Notification types:**
1. **New roles found** — List of new matching jobs with company, title, location, link
2. **Outreach summary** — Daily digest: emails sent today, follow-ups due, response rate
3. **Errors** — If scraping fails for a company, if SMTP is down, etc.

Keep notifications concise. Mihir gets enough email already.

### `src/main.py` — CLI Entrypoint

```bash
# ── Job Monitoring ──
python -m src.main monitor              # One-time scrape of all career pages
python -m src.main monitor --daemon     # Run continuously (check_interval_hours)

# ── Contact Finding ──
python -m src.main contacts --all       # Find contacts for all companies missing them
python -m src.main contacts --company "Citadel Securities"  # Single company

# ── Outreach ──
python -m src.main outreach --preview   # Preview all pending emails
python -m src.main outreach --send      # Send (requires confirmation)
python -m src.main outreach --followup  # Send due follow-ups

# ── Full Pipeline ──
python -m src.main pipeline             # monitor → contacts → outreach --preview
python -m src.main pipeline --send      # monitor → contacts → outreach --send

# ── Utilities ──
python -m src.main init                 # Create tracker Excel + config.example.yaml
python -m src.main test-email           # Verify SMTP works
python -m src.main status               # Print dashboard stats from tracker
```

Use `argparse` with subcommands. Every command should support `--config path/to/config.yaml` (default: `./config.yaml`).

---

## Excel Tracker Sheet Specifications

### Sheet: "Companies"
The configuration sheet. Mihir populates this manually or via the `contacts` command.

| Column | Header | Notes |
|--------|--------|-------|
| A | Company | Company name |
| B | Tier | Dropdown: "Tier 1 - Dream", "Tier 2 - Strong", "Tier 3 - Backup" |
| C | Sector | Dropdown: "Quant/HFT", "Systems/Infra", "Fintech", "FAANG", "Startup", "Other" |
| D | Careers URL | Full URL to careers/jobs page |
| E | Board Type | Dropdown: "Greenhouse", "Lever", "Ashby", "Workday", "Custom" |
| F | Sponsors H-1B | Dropdown: "Yes", "No", "Unknown" |
| G | Domain | Email domain (auto-filled by contacts module) |
| H | Notes | Free text |

### Sheet: "New Roles" (the to-do queue)
Auto-populated by the monitor. Mihir reviews this when sitting down to apply.

| Column | Header |
|--------|--------|
| A | Date Found |
| B | Company |
| C | Role Title |
| D | Location |
| E | URL |
| F | Department |
| G | Board Type |
| H | Status — Dropdown: "New", "Reviewing", "Applied", "Skipped" |
| I | HM Name (auto-filled by contacts) |
| J | HM Email (auto-filled by contacts) |
| K | Outreach Sent? — "Yes" / "No" |
| L | Notes |

### Sheet: "Global Tracker"
Master list — every role ever found. Superset of New Roles with more status granularity.

| Column | Header |
|--------|--------|
| A | Date Found |
| B | Company |
| C | Role Title |
| D | Location |
| E | URL |
| F | Status — "New", "Applied", "Emailed HM", "Phone Screen", "Interview", "Rejected", "Offer", "Skipped" |
| G | Applied Date |
| H | HM Name |
| I | HM Email |
| J | Outreach Status — "Not Sent", "Sent", "Replied", "Meeting Scheduled" |
| K | Follow-up Due |
| L | Notes |

### Sheet: "Contacts"
All discovered contacts, not just the best one per company.

| Column | Header |
|--------|--------|
| A | Company |
| B | Name |
| C | Title |
| D | Email |
| E | LinkedIn |
| F | Type — "Hiring Manager", "Recruiter", "Engineer", "Other" |
| G | Source — "Hunter.io", "Apollo.io", "Google/LinkedIn", "Manual" |
| H | Confidence — "High", "Medium", "Low" |
| I | Email Verified — "Yes", "No" |
| J | Date Found |

### Sheet: "Outreach Log"
Every email ever sent.

| Column | Header |
|--------|--------|
| A | Date Sent |
| B | Company |
| C | Contact Name |
| D | Contact Email |
| E | Email Type — "Cold HM", "Cold Recruiter", "Role-Specific", "Follow-up" |
| F | Subject Line |
| G | Role Referenced |
| H | Status — "Sent", "Opened", "Replied", "Meeting Scheduled", "No Response", "Bounced" |
| I | Follow-up Due |
| J | LLM Generated? — "Yes", "No" |
| K | Notes |

### Sheet: "Email Templates"
Reference sheet. Templates are also stored as .txt files in `/templates/` for easier editing.

### Sheet: "Dashboard"
Auto-calculated metrics using Excel formulas. Formulas reference other sheets.

Metrics to include:
- Total companies tracked
- Total roles found (this week / all time)
- Roles by status (New / Applied / Interviewing)
- Outreach stats (sent / replied / response rate)
- Follow-ups due today
- Companies still needing contact enrichment

---

## Email Template Files

### `templates/cold_hm.txt`
```
Subject: Rutgers MS CS – Systems Engineer Interested in {{ company }}

Hi {{ first_name }},

I'm Mihir Kulkarni, an MS CS student at Rutgers graduating May 2026, focused on low-latency systems programming in C/C++.

I've built a concurrent TCP server with sub-3ms p95 latency using epoll, a preemptive threading library with multiple schedulers, and I'm currently doing FPGA research and building a matching engine in C++.

{% if role %}I saw {{ company }} posted the {{ role }} position — I'd love to chat about the team and what you look for in candidates.{% else %}I'm interested in systems roles at {{ company }} and would love to learn more about the team.{% endif %} Would you have 15 minutes this week or next?

Best,
Mihir Kulkarni
github.com/mihir965
```

### `templates/cold_recruiter.txt`
```
Subject: MS CS @ Rutgers – Systems/C++ Roles at {{ company }}

Hi {{ first_name }},

I'm Mihir Kulkarni, MS CS at Rutgers (May 2026), specializing in systems programming — C/C++, Linux, concurrency.

I have production experience (data pipelines at Syngenta, full-stack SaaS at UniteGPS) and deep systems projects: an epoll-based TCP server, user-level threading library, and FPGA research.

I'm targeting infrastructure and systems roles — happy to send my resume or chat briefly about relevant openings at {{ company }}.

Best,
Mihir Kulkarni
github.com/mihir965
```

### `templates/role_specific.txt` (fallback if LLM is unavailable)
```
Subject: {{ role }} at {{ company }} – Rutgers MS CS Candidate

Hi {{ first_name }},

I saw {{ company }} posted the {{ role }} role — it aligns well with my background in systems programming and low-latency C++.

Key projects: concurrent TCP server (sub-3ms p95, epoll), preemptive threading library (MLFQ/CFS), FPGA research, and production ETL pipelines at Syngenta.

I applied through your careers page and wanted to reach out directly. Would you have 15 minutes to chat?

Best,
Mihir Kulkarni
github.com/mihir965
```

### `templates/followup.txt`
```
Subject: Re: {{ original_subject }}

Hi {{ first_name }},

Just following up on my note from last week. I know you're busy — happy to reconnect whenever works.

{% if update %}Since my last email, {{ update }}{% endif %}

Would a quick 15-minute chat work sometime this week?

Best,
Mihir
```

---

## Implementation Rules

### Code Style
- Python 3.11+. Type hints everywhere.
- Use `dataclasses` or `pydantic` for data models (Contact, Job, OutreachEntry).
- Logging via `logging` module — INFO level by default, DEBUG with `--verbose` flag.
- No print statements for anything except `--preview` output.
- f-strings for formatting. No `.format()` or `%`.

### Error Handling
- Never crash the whole pipeline because one company's scrape failed.
- Wrap each company's scrape/enrich/outreach in try/except, log the error, continue.
- If the Excel file is corrupted or missing, `tracker.py` should be able to recreate it from scratch.
- If SMTP fails mid-batch, log it and report at the end — don't retry immediately.

### Rate Limiting
- Google searches: 3-5 second delay between requests (randomized).
- Career page scraping: 2 second delay between companies.
- SMTP sending: 3-5 second delay between emails.
- API calls (Hunter, Apollo): respect their rate limits (Hunter: 10/sec, Apollo: 5/sec).
- Use `time.sleep()` with slight randomization (`random.uniform(2, 5)`) to look less bot-like.

### Testing
- Use `pytest`. Mock external API calls and SMTP.
- Test `tracker.py` with a temporary Excel file.
- Test email template rendering with known inputs.
- Test keyword matching edge cases.

### Security
- Never commit `config.yaml` (it has secrets). Commit `config.example.yaml`.
- Add `config.yaml`, `seen_jobs.json`, `outreach_tracker.xlsx` to `.gitignore`.
- API keys and SMTP password should be loadable from env vars OR the config file.
- Never log email passwords or API keys.

---

## Deployment / Cron Setup

Intended to run on Mihir's EndevourOS PC. Crontab example:

```cron
# Check for new job postings every 6 hours
0 */6 * * * cd /path/to/job_search && python -m src.main monitor >> logs/monitor.log 2>&1

# Enrich contacts for companies missing HM info — daily at 7am
0 7 * * * cd /path/to/job_search && python -m src.main contacts --all >> logs/contacts.log 2>&1

# Send follow-ups every weekday at 9am
0 9 * * 1-5 cd /path/to/job_search && python -m src.main outreach --followup >> logs/followup.log 2>&1

# Daily status digest at 6pm
0 18 * * * cd /path/to/job_search && python -m src.main status --notify >> logs/status.log 2>&1
```

---

## Dependencies (requirements.txt)

```
requests>=2.31
beautifulsoup4>=4.12
openpyxl>=3.1
pyyaml>=6.0
jinja2>=3.1
dnspython>=2.4
filelock>=3.13
schedule>=1.2
anthropic>=0.40
```

---

## Pre-loaded Company List

Start the Companies sheet with these (Mihir's targets):

| Company | Tier | Sector | Board Type | Sponsors H-1B |
|---------|------|--------|------------|----------------|
| Jane Street | Tier 1 | Quant/HFT | Custom | Yes |
| Citadel Securities | Tier 1 | Quant/HFT | Greenhouse | Yes |
| Hudson River Trading | Tier 1 | Quant/HFT | Custom | Yes |
| Two Sigma | Tier 1 | Quant/HFT | Greenhouse | Yes |
| Tower Research Capital | Tier 1 | Quant/HFT | Custom | Yes |
| Jump Trading | Tier 1 | Quant/HFT | Custom | Yes |
| D.E. Shaw | Tier 1 | Quant/HFT | Custom | Yes |
| Five Rings | Tier 1 | Quant/HFT | Custom | Yes |
| Virtu Financial | Tier 2 | Quant/HFT | Greenhouse | Yes |
| IMC Trading | Tier 2 | Quant/HFT | Greenhouse | Yes |
| DRW | Tier 2 | Quant/HFT | Custom | Yes |
| Optiver | Tier 2 | Quant/HFT | Greenhouse | Yes |
| Wolverine Trading | Tier 2 | Quant/HFT | Custom | Unknown |
| Akuna Capital | Tier 2 | Quant/HFT | Greenhouse | Yes |
| Susquehanna (SIG) | Tier 2 | Quant/HFT | Custom | Yes |
| Cloudflare | Tier 2 | Systems/Infra | Greenhouse | Yes |
| Databricks | Tier 2 | Systems/Infra | Greenhouse | Yes |

---

## What NOT To Build

- No web UI. This is a CLI tool + Excel tracker.
- No database. Excel + JSON is the entire persistence layer.
- No job application bot (auto-applying). This only monitors, contacts, and emails.
- No LinkedIn automation (violates ToS and gets accounts banned).
- No resume tailoring automation — that's a separate workflow Mihir does manually in Claude.
