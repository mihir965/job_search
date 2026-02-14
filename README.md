# Job Outreach Automation

Automated pipeline for finding jobs and reaching out to hiring managers at HFT/quant firms and tech companies.

## Quick Start

1. **Install dependencies:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Initialize the system:**
   ```bash
   python -m src.main init
   ```

3. **Configure:**
   - Edit `config.yaml` (copy from `config.example.yaml`)
   - Add your SMTP credentials (Gmail App Password)
   - Optionally add API keys (Hunter.io, Apollo.io, Anthropic)

4. **Add careers URLs:**
   - Open `outreach_tracker.xlsx`
   - Go to "Companies" sheet
   - Fill in the "Careers URL" column for each company

5. **Start monitoring:**
   ```bash
   python -m src.main monitor
   ```

## Usage

### Monitor job boards
```bash
python -m src.main monitor              # One-time scrape
python -m src.main monitor --daemon     # Continuous (every 6 hours)
```

### Find contacts
```bash
python -m src.main contacts --all                      # All companies
python -m src.main contacts --company "Jane Street"    # Single company
```

### Send outreach emails
```bash
python -m src.main outreach --preview   # Preview pending emails
python -m src.main outreach --send      # Send (with confirmation)
python -m src.main outreach --followup  # Send follow-ups
```

### Run full pipeline
```bash
python -m src.main pipeline             # monitor → contacts → preview
python -m src.main pipeline --send      # monitor → contacts → send
```

### Test SMTP
```bash
python -m src.main test-email
```

### Check status
```bash
python -m src.main status
```

## How It Works

1. **Monitoring**: Scrapes job boards (Greenhouse, Lever, Ashby, Workday) for matching roles
2. **Contact Finding**: Uses Hunter.io, Apollo.io, and Google to find hiring manager emails
3. **Outreach**: Sends personalized emails (optionally using Claude LLM for customization)
4. **Tracking**: Everything stored in `outreach_tracker.xlsx` with multiple sheets

## Configuration

### Environment Variables
Set these in your shell or `.env` file:
- `SMTP_USER` - Your Gmail address
- `SMTP_PASSWORD` - Gmail App Password ([create one here](https://myaccount.google.com/apppasswords))
- `HUNTER_API_KEY` - Hunter.io API key (optional, 25 free/month)
- `APOLLO_API_KEY` - Apollo.io API key (optional, 50 free/month)
- `ANTHROPIC_API_KEY` - Claude API key (optional, for LLM email personalization)

### config.yaml
Edit the config to customize:
- Search keywords (roles you're interested in)
- Exclude keywords (senior, staff, etc.)
- Daily email limit (default: 12)
- Send window (business hours)
- LLM settings

## Excel Tracker Sheets

- **Dashboard**: Overview metrics
- **Companies**: Target companies (add careers URLs here!)
- **New Roles**: Recently found jobs (to-do queue)
- **Global Tracker**: All roles ever found
- **Contacts**: All discovered hiring managers and recruiters
- **Outreach Log**: Every email sent

## Cron Setup

Add to crontab for automation:
```cron
# Monitor every 6 hours
0 */6 * * * cd /path/to/job_search && ./venv/bin/python -m src.main monitor

# Enrich contacts daily at 7am
0 7 * * * cd /path/to/job_search && ./venv/bin/python -m src.main contacts --all

# Send follow-ups weekdays at 9am
0 9 * * 1-5 cd /path/to/job_search && ./venv/bin/python -m src.main outreach --followup
```

## Notes

- **Rate limiting**: Built-in delays to avoid getting banned
- **Safety**: Email sending requires confirmation unless you use `--yes`
- **Privacy**: Never commit `config.yaml` or `outreach_tracker.xlsx` (they contain secrets/personal data)
- **API keys**: All APIs are optional - system degrades gracefully without them

## Troubleshooting

**SMTP fails:**
- Make sure you're using a Gmail App Password, not your regular password
- Enable "Less secure app access" if needed (not recommended, use App Password instead)

**No jobs found:**
- Check that careers URLs are filled in the Companies sheet
- Verify search keywords in config.yaml match the roles you want

**Contact enrichment limited:**
- Add Hunter.io and Apollo.io API keys for better results
- Without API keys, only basic methods are used

For more details, see `CLAUDE.md`.
