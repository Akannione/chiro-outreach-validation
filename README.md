# Chiropractic Outreach Validation Pipeline

This is a lean market-research system for contacting chiropractic clinics in Ohio and Georgia, tracking survey outreach, and syncing structured data to Google Sheets.

The goal is validation speed, not scale. Start with 20 to 50 thoughtful, one-to-one emails, read the replies, then decide what to automate next.

## What It Stores

- `data/contacts.csv`: clinic contact database and outreach status
- `data/outreach_log.csv`: every dry run, send, reply detection, and error
- `data/suppression_list.csv`: emails/domains that should never be contacted again
- `data/manual_responses.csv`: notes from calls, replies, or manually captured interviews
- optional Google Sheets tabs: `Outreach Contacts`, `Outreach Log`, `Suppression List`

## Setup

```bash
cd "/Users/tobiloba202/Documents/New project/chiro_outreach"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m chiro_outreach.cli init
```

Edit:

```text
config/outreach_config.local.json
```

Before sending real emails, set:

- `sender_name`
- `sender_email`
- `company_name`
- `postal_address`
- `survey_url`

The default survey URL is already set to:

```text
https://forms.gle/HjWbEG3Z7hzNY9L1A
```

## Google API Credentials

For clinic discovery:

```bash
export GOOGLE_MAPS_API_KEY="your-google-maps-api-key"
```

For Gmail and Sheets:

1. Create a Google Cloud OAuth desktop client.
2. Enable Gmail API and Google Sheets API.
3. Save the downloaded OAuth JSON as:

```text
chiro_outreach/.secrets/client_secret.json
```

The first Gmail/Sheets command opens a browser OAuth flow and writes:

```text
chiro_outreach/.secrets/token.json
```

## Workflow

Discover a small initial sample:

```bash
PYTHONPATH=src python -m chiro_outreach.cli discover --states OH,GA --max-per-query 10 --limit-queries 6
```

Find public emails from clinic websites:

```bash
PYTHONPATH=src python -m chiro_outreach.cli enrich-emails --limit 50 --max-pages 5
```

Re-scan only weak leads without an email or contact form:

```bash
PYTHONPATH=src python -m chiro_outreach.cli enrich-emails --limit 25 --force --weak-only --max-pages 5
```

Clean vendor/debug email artifacts after enrichment:

```bash
PYTHONPATH=src python -m chiro_outreach.cli clean-emails
```

Generate personalized drafts:

```bash
PYTHONPATH=src python -m chiro_outreach.cli draft --limit 50
```

Rotate A/B outreach variants:

```bash
PYTHONPATH=src python -m chiro_outreach.cli draft --limit 50 --rotate-variants
```

Dry-run the next batch:

```bash
PYTHONPATH=src python -m chiro_outreach.cli send --limit 10
```

Send a real one-to-one batch:

```bash
PYTHONPATH=src python -m chiro_outreach.cli send --limit 10 --send
```

Check for replies:

```bash
PYTHONPATH=src python -m chiro_outreach.cli check-replies
```

Record an opt-out immediately:

```bash
PYTHONPATH=src python -m chiro_outreach.cli suppress --email info@exampleclinic.com --reason opt-out
```

Draft contact-form outreach for form-only leads:

```bash
PYTHONPATH=src python -m chiro_outreach.cli draft-forms --limit 10
```

Preview contact-form fill plans without submitting:

```bash
PYTHONPATH=src python -m chiro_outreach.cli preview-forms --limit 5
```

Dry-run reviewed contact-form submissions:

```bash
PYTHONPATH=src python -m chiro_outreach.cli submit-forms --limit 3
```

Submit reviewed contact forms only after manual review:

```bash
PYTHONPATH=src python -m chiro_outreach.cli submit-forms --limit 3 --send
```

Pull Google Form responses and mark completed contacts when a clinic/email match is detected:

```bash
PYTHONPATH=src python -m chiro_outreach.cli pull-responses
```

Sync outreach CSVs to Google Sheets:

```bash
PYTHONPATH=src python -m chiro_outreach.cli sync-sheets
```

Show funnel status:

```bash
PYTHONPATH=src python -m chiro_outreach.cli status
```

Run the dashboard:

```bash
streamlit run dashboard.py
```

## 48-Hour MVP Demo

The AlignDeskApp validation demo lives at:

```text
demo/aligndesk_mvp/index.html
```

Open it in a browser to show a chiropractic documentation workflow demo: visit template, exam findings, generated SOAP note, EHR-ready copy output, follow-up queue, and local reaction capture.

Use it to test whether clinics care about a narrow documentation/workflow assistant before building integrations, auth, patient storage, or a full SaaS app.

## Sending Rules

- Default is dry-run. Real sending requires `--send`.
- Send one recipient per email.
- Default batch cap is 10 and the recommended daily cap is 20.
- Default delay is 2 to 6 minutes between messages.
- Include a valid postal address before sending real email.
- Include opt-out language and immediately add opt-outs to `data/suppression_list.csv`.
- Do not use tracking pixels by default. `opened_at` exists as a manual/import field, but Gmail does not provide reliable open tracking through the API.
- Contact-form submission is dry-run by default. It skips CAPTCHA-marked forms and blocks unknown required fields for review.
- Keep form submission batches tiny at first. Recommended: 3 to 5 reviewed forms per day.

## Recommended First Batch

1. Discover 100 to 150 clinics across both states.
2. Enrich until you have 30 to 50 public emails.
3. Manually review `data/contacts.csv`.
4. Send 10 emails per day for the first 3 days.
5. Read replies and update `manual_responses.csv`.
6. Only scale after the response rate and survey completion quality are acceptable.
