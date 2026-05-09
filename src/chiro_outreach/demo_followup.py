import csv
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .csv_store import append_log, load_contacts, load_suppression, read_rows, save_contacts
from .gmail_client import gmail_send_message, sent_in_last_24_hours, validate_send_config
from .normalization import clean_cell, email_domain, normalize_email, stable_id
from .paths import FORM_RESPONSES_CSV, OUTREACH_LOG_CSV, REPORTS_DIR
from .time_utils import utc_now_iso


FOLLOWUP_SENT_EVENT = "demo_followup_sent"
FOLLOWUP_DRY_RUN_EVENT = "demo_followup_dry_run"
DEFAULT_DEMO_URL = "https://akannione.github.io/aligndeskapp-demo/"


@dataclass
class DemoFollowup:
    recipient_type: str
    contact_id: str
    clinic_name: str
    email: str
    subject: str
    body: str
    source_summary: str


def run_demo_followups(
    config: dict[str, str],
    limit: int,
    min_delay_seconds: int,
    max_delay_seconds: int,
    actually_send: bool,
    include_contacts: bool = True,
    include_respondents: bool = True,
) -> tuple[int, str]:
    if max_delay_seconds < min_delay_seconds:
        raise RuntimeError("max_delay_seconds must be greater than or equal to min_delay_seconds.")
    validate_send_config(config, actually_send)

    suppressed_emails, suppressed_domains = suppression_sets()
    already_sent = already_demo_followed_up()
    drafts = build_demo_followups(config, include_contacts, include_respondents)
    eligible = [
        draft
        for draft in drafts
        if draft.email
        and draft.email not in already_sent
        and draft.email not in suppressed_emails
        and email_domain(draft.email) not in suppressed_domains
    ]

    daily_remaining = int(config.get("daily_send_cap", 20)) - sent_in_last_24_hours()
    if actually_send and daily_remaining <= 0:
        raise RuntimeError("Daily send cap reached for the last rolling 24 hours.")
    if actually_send:
        limit = min(limit, daily_remaining)

    selected = eligible[:limit]
    report_path = write_followup_report(selected)
    sent = 0
    contacts = load_contacts()
    contacts_by_id = {contact.get("contact_id", ""): contact for contact in contacts}

    for draft in selected:
        now = utc_now_iso()
        gmail_message_id = ""
        gmail_thread_id = ""
        details = "dry_run"

        if actually_send:
            result = gmail_send_message(
                to_email=draft.email,
                subject=draft.subject,
                body=draft.body,
                sender_name=config.get("sender_name", ""),
                sender_email=config.get("sender_email", ""),
                reply_to=config.get("sender_email", ""),
            )
            gmail_message_id = result.get("id", "")
            gmail_thread_id = result.get("threadId", "")
            details = "sent"

            contact = contacts_by_id.get(draft.contact_id)
            if contact:
                contact["last_contacted_at"] = now
                contact["sent_count"] = str(int(contact.get("sent_count") or "0") + 1)
                contact["notes"] = append_note(contact.get("notes", ""), "Demo follow-up sent.")
                contact["updated_at"] = now

        append_log(
            {
                "log_id": stable_id(draft.contact_id, FOLLOWUP_SENT_EVENT if actually_send else FOLLOWUP_DRY_RUN_EVENT, now),
                "contact_id": draft.contact_id,
                "clinic_name": draft.clinic_name,
                "email": draft.email,
                "event_type": FOLLOWUP_SENT_EVENT if actually_send else FOLLOWUP_DRY_RUN_EVENT,
                "gmail_message_id": gmail_message_id,
                "gmail_thread_id": gmail_thread_id,
                "subject": draft.subject,
                "timestamp": now,
                "details": details,
            }
        )
        sent += 1

        if actually_send and sent < len(selected):
            time.sleep(random.randint(min_delay_seconds, max_delay_seconds))

    if actually_send:
        save_contacts(contacts)

    return sent, str(report_path)


def build_demo_followups(
    config: dict[str, str],
    include_contacts: bool,
    include_respondents: bool,
) -> list[DemoFollowup]:
    drafts: list[DemoFollowup] = []
    if include_contacts:
        drafts.extend(contact_followups(config))
    if include_respondents:
        drafts.extend(response_followups(config, {draft.email for draft in drafts}))
    return drafts


def contact_followups(config: dict[str, str]) -> list[DemoFollowup]:
    drafts: list[DemoFollowup] = []
    demo_url = clean_cell(config.get("demo_url", "")) or DEFAULT_DEMO_URL
    signature = build_signature(config)

    for contact in load_contacts():
        email = normalize_email(contact.get("public_email", ""))
        if not email:
            continue
        if contact.get("outreach_status") not in {"sent", "responded", "completed_form"}:
            continue
        clinic_name = clean_cell(contact.get("clinic_name", ""))
        city = clean_cell(contact.get("city", ""))
        state = clean_cell(contact.get("state", ""))
        location = f"{city}, {state}".strip(", ")
        greeting = f"Hi {clinic_name} team," if clinic_name else "Hi,"
        subject = "Quick follow-up: AlignDeskApp documentation demo"
        body = f"""{greeting}

I am following up on my earlier chiropractic workflow research note. I put together a small 48-hour demo around the problem that keeps showing up: faster chiropractic documentation and easier EHR-ready notes.

Demo link:
{demo_url}

If the doctor or office manager has 3 minutes, could they open it with fake/de-identified info and reply with:
1. Would this save documentation time?
2. What is missing before this would be useful?
3. Is copy/paste into your EHR enough for v1, or would integration be required?

No patient information should be entered. This is only a validation demo, not a finished product.

Thanks,
{signature}

If you would rather I not contact your clinic again, reply "opt out" and I will remove you."""
        drafts.append(
            DemoFollowup(
                recipient_type="contacted_clinic",
                contact_id=contact.get("contact_id", ""),
                clinic_name=clinic_name,
                email=email,
                subject=subject,
                body=body,
                source_summary=f"Sent clinic contact from {location or 'unknown location'}",
            )
        )
    return drafts


def response_followups(config: dict[str, str], excluded_emails: set[str]) -> list[DemoFollowup]:
    drafts: list[DemoFollowup] = []
    demo_url = clean_cell(config.get("demo_url", "")) or DEFAULT_DEMO_URL
    signature = build_signature(config)

    for row in read_rows(FORM_RESPONSES_CSV):
        email = normalize_email(find_value(row, "email"))
        if not email or email in excluded_emails:
            continue
        role = clean_cell(find_value(row, "role"))
        org_type = clean_cell(find_value(row, "organization"))
        pain_text = clean_cell(find_value(row, "frustrating technical or workflow problems"))
        main_problem = clean_cell(find_value(row, "SECTION 3"))
        current_tools = clean_cell(find_value(row, "specific software"))
        price = clean_cell(find_value(row, "pay monthly"))
        testing = clean_cell(find_value(row, "open to testing"))
        source_summary = " | ".join(
            part
            for part in [
                f"role={role}" if role else "",
                f"org={org_type}" if org_type else "",
                f"problem={shorten(main_problem or pain_text, 110)}" if (main_problem or pain_text) else "",
                f"pay={price}" if price else "",
                f"testing={testing}" if testing else "",
            ]
            if part
        )
        pain_reference = tailored_pain_reference(main_problem, pain_text)
        subject = "I made a demo from your chiropractic workflow feedback"
        body = f"""Hi,

Thank you for leaving your email on the chiropractic workflow survey. You mentioned {pain_reference}, so I built a small 48-hour AlignDeskApp demo focused on faster chiropractic documentation and cleaner EHR-ready notes.

Demo link:
{demo_url}

Please use fake/de-identified information only. Could you try it for 3 minutes and reply with:
1. Would this save time in your current workflow?
2. What is missing before you would use or pay for it?
3. Is copy/paste into your current EHR enough, or would integration be required?

Your current tool context: {current_tools or "not specified"}
Your survey price reaction: {price or "not specified"}

Thanks,
{signature}

If you would rather not receive updates, reply "opt out" and I will remove you."""
        drafts.append(
            DemoFollowup(
                recipient_type="survey_respondent",
                contact_id=stable_id(email, "survey_respondent"),
                clinic_name=role or "Survey respondent",
                email=email,
                subject=subject,
                body=body,
                source_summary=source_summary,
            )
        )
    return drafts


def find_value(row: dict[str, str], needle: str) -> str:
    needle = needle.lower()
    for key, value in row.items():
        if needle in key.lower() and value:
            return value
    return ""


def tailored_pain_reference(main_problem: str, pain_text: str) -> str:
    text = clean_cell(main_problem or pain_text)
    lower = text.lower()
    if not text:
        return "that EHR and clinic workflow efficiency matters"
    if "child" in lower or "pediatric" in lower:
        return "that current EHRs are not chiropractic-specific enough, especially for pediatric notes"
    if "integrat" in lower or "reupload" in lower or "downloading" in lower:
        return "that disconnected software and re-uploading data waste time"
    if "slow" in lower or "efficien" in lower or "navigate" in lower:
        return "that slow or hard-to-navigate EHR workflows create friction"
    if "medical" in lower and "chiropractic" in lower:
        return "that many EHR workflows feel too medical-driven and not chiropractic-specific"
    return f'this pain point: "{shorten(text, 140)}"'


def build_signature(config: dict[str, str]) -> str:
    lines = [
        clean_cell(config.get("sender_name", "")),
        clean_cell(config.get("company_name", "")),
        clean_cell(config.get("postal_address", "")),
    ]
    return "\n".join(line for line in lines if line)


def suppression_sets() -> tuple[set[str], set[str]]:
    suppressed_emails: set[str] = set()
    suppressed_domains: set[str] = set()
    for row in load_suppression():
        email = normalize_email(row.get("email", ""))
        domain = clean_cell(row.get("domain", "")).lower()
        if email:
            suppressed_emails.add(email)
        if domain:
            suppressed_domains.add(domain)
    return suppressed_emails, suppressed_domains


def already_demo_followed_up() -> set[str]:
    emails: set[str] = set()
    for row in read_rows(OUTREACH_LOG_CSV):
        if row.get("event_type") == FOLLOWUP_SENT_EVENT and row.get("email"):
            emails.add(normalize_email(row["email"]))
    return emails


def append_note(existing: str, note: str) -> str:
    existing = clean_cell(existing)
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing} | {note}"


def write_followup_report(drafts: list[DemoFollowup]):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"demo_followup_drafts_{stamp}.csv"
    fields = ["recipient_type", "contact_id", "clinic_name", "email", "subject", "body", "source_summary"]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for draft in drafts:
            writer.writerow({field: getattr(draft, field) for field in fields})
    return path


def shorten(value: str, limit: int) -> str:
    value = " ".join(clean_cell(value).split())
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."
