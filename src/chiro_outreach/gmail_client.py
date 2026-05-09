import base64
import random
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from .csv_store import append_log, load_contacts, load_suppression, read_rows, save_contacts
from .google_auth import OUTREACH_GOOGLE_SCOPES, google_service
from .normalization import email_domain, normalize_email, stable_id
from .paths import OUTREACH_LOG_CSV
from .time_utils import utc_now_iso


GMAIL_SCOPES = OUTREACH_GOOGLE_SCOPES
DEMO_FOLLOWUP_SENT_EVENT = "demo_followup_sent"
DEMO_FOLLOWUP_RESPONDED_EVENT = "demo_followup_responded"


def gmail_send_message(
    to_email: str,
    subject: str,
    body: str,
    sender_name: str,
    sender_email: str,
    reply_to: str | None = None,
) -> dict[str, str]:
    service = google_service("gmail", "v1", GMAIL_SCOPES)
    message = EmailMessage()
    message.set_content(body)
    message["To"] = to_email
    message["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to

    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return service.users().messages().send(userId="me", body={"raw": encoded}).execute()


def check_replies(config: dict[str, str], limit: int = 100) -> int:
    service = google_service("gmail", "v1", GMAIL_SCOPES)
    sender_email = normalize_email(config.get("sender_email", ""))
    contacts = load_contacts()
    sent_contacts = [row for row in contacts if row.get("outreach_status") == "sent" and row.get("public_email")]
    updated = 0

    for contact in sent_contacts[:limit]:
        after = gmail_after_date(contact.get("last_contacted_at", ""))
        query = f'from:{contact["public_email"]} {after}'.strip()
        response = service.users().messages().list(userId="me", q=query, maxResults=10).execute()
        messages = response.get("messages", [])
        if not messages:
            continue
        now = utc_now_iso()
        contact["outreach_status"] = "responded"
        contact["responded_at"] = contact.get("responded_at") or now
        contact["updated_at"] = now
        append_log(
            {
                "log_id": stable_id(contact["contact_id"], "responded", now),
                "contact_id": contact["contact_id"],
                "clinic_name": contact.get("clinic_name", ""),
                "email": contact.get("public_email", ""),
                "event_type": "responded",
                "timestamp": now,
                "details": f"Reply detected with Gmail query. Sender account: {sender_email}",
            }
        )
        updated += 1

    updated += check_demo_followup_replies(service, sender_email, max(0, limit - updated))

    if updated:
        save_contacts(contacts)
    return updated


def check_demo_followup_replies(service, sender_email: str, limit: int) -> int:
    if limit <= 0:
        return 0
    sent_events = demo_followup_sent_events()
    responded_emails = {
        normalize_email(row.get("email", ""))
        for row in read_rows(OUTREACH_LOG_CSV)
        if row.get("event_type") == DEMO_FOLLOWUP_RESPONDED_EVENT and row.get("email")
    }
    updated = 0

    for event in sent_events:
        if updated >= limit:
            break
        email = normalize_email(event.get("email", ""))
        if not email or email in responded_emails:
            continue

        response = service.users().messages().list(
            userId="me",
            q=f"from:{email} {gmail_after_date(event.get('timestamp', ''))}".strip(),
            maxResults=10,
        ).execute()
        messages = response.get("messages", [])
        if not messages:
            continue

        now = utc_now_iso()
        append_log(
            {
                "log_id": stable_id(event.get("contact_id", email), DEMO_FOLLOWUP_RESPONDED_EVENT, now),
                "contact_id": event.get("contact_id", ""),
                "clinic_name": event.get("clinic_name", ""),
                "email": email,
                "event_type": DEMO_FOLLOWUP_RESPONDED_EVENT,
                "timestamp": now,
                "details": f"Demo follow-up reply detected with Gmail query. Sender account: {sender_email}",
            }
        )
        updated += 1

    return updated


def demo_followup_sent_events() -> list[dict[str, str]]:
    by_email: dict[str, dict[str, str]] = {}
    for row in read_rows(OUTREACH_LOG_CSV):
        if row.get("event_type") != DEMO_FOLLOWUP_SENT_EVENT:
            continue
        email = normalize_email(row.get("email", ""))
        if not email:
            continue
        existing = by_email.get(email)
        if not existing or row.get("timestamp", "") > existing.get("timestamp", ""):
            by_email[email] = row
    return sorted(by_email.values(), key=lambda row: row.get("timestamp", ""), reverse=True)


def send_batch(
    config: dict[str, str],
    limit: int,
    min_delay_seconds: int,
    max_delay_seconds: int,
    actually_send: bool,
) -> int:
    if max_delay_seconds < min_delay_seconds:
        raise RuntimeError("max_delay_seconds must be greater than or equal to min_delay_seconds.")
    validate_send_config(config, actually_send)
    contacts = load_contacts()
    suppressed_emails, suppressed_domains = suppression_sets()
    daily_remaining = int(config.get("daily_send_cap", 20)) - sent_in_last_24_hours()
    if actually_send and daily_remaining <= 0:
        raise RuntimeError("Daily send cap reached for the last rolling 24 hours.")
    if actually_send:
        limit = min(limit, daily_remaining)
    sent = 0

    for contact in contacts:
        if sent >= limit:
            break
        email = normalize_email(contact.get("public_email", ""))
        if not email:
            continue
        if contact.get("outreach_status") not in {"draft_ready", "ready"}:
            continue
        if email in suppressed_emails or email_domain(email) in suppressed_domains:
            contact["outreach_status"] = "suppressed"
            continue

        subject = contact.get("personalized_subject", "").strip()
        body = contact.get("personalized_body", "").strip()
        if not subject or not body:
            contact["outreach_status"] = "not_ready"
            continue

        now = utc_now_iso()
        gmail_message_id = ""
        gmail_thread_id = ""
        details = "dry_run"

        if actually_send:
            try:
                result = gmail_send_message(
                    to_email=email,
                    subject=subject,
                    body=body,
                    sender_name=config.get("sender_name", ""),
                    sender_email=config.get("sender_email", ""),
                    reply_to=config.get("sender_email", ""),
                )
                gmail_message_id = result.get("id", "")
                gmail_thread_id = result.get("threadId", "")
                details = "sent"
            except Exception as error:
                append_log(
                    {
                        "log_id": stable_id(contact["contact_id"], "send_error", now),
                        "contact_id": contact["contact_id"],
                        "clinic_name": contact.get("clinic_name", ""),
                        "email": email,
                        "event_type": "error",
                        "subject": subject,
                        "timestamp": now,
                        "details": str(error),
                    }
                )
                continue

        contact["outreach_status"] = "sent" if actually_send else "draft_ready"
        contact["last_contacted_at"] = now if actually_send else contact.get("last_contacted_at", "")
        contact["sent_count"] = str(int(contact.get("sent_count") or "0") + (1 if actually_send else 0))
        contact["updated_at"] = now
        append_log(
            {
                "log_id": stable_id(contact["contact_id"], "sent" if actually_send else "dry_run", now),
                "contact_id": contact["contact_id"],
                "clinic_name": contact.get("clinic_name", ""),
                "email": email,
                "event_type": "sent" if actually_send else "dry_run",
                "gmail_message_id": gmail_message_id,
                "gmail_thread_id": gmail_thread_id,
                "subject": subject,
                "timestamp": now,
                "details": details,
            }
        )
        sent += 1

        if actually_send and sent < limit:
            time.sleep(random.randint(min_delay_seconds, max_delay_seconds))

    save_contacts(contacts)
    return sent


def validate_send_config(config: dict[str, str], actually_send: bool) -> None:
    if not actually_send:
        return
    required = ["sender_email", "postal_address", "survey_url"]
    missing = [
        key
        for key in required
        if not config.get(key)
        or "YOUR VALID POSTAL ADDRESS" in str(config.get(key))
        or str(config.get(key)).strip() == "you@example.com"
    ]
    if missing:
        raise RuntimeError(f"Cannot send until these config values are set: {', '.join(missing)}")
    if int(config.get("max_delay_seconds", 0) or 0) < int(config.get("min_delay_seconds", 0) or 0):
        raise RuntimeError("max_delay_seconds must be greater than or equal to min_delay_seconds.")


def suppression_sets() -> tuple[set[str], set[str]]:
    suppressed_emails: set[str] = set()
    suppressed_domains: set[str] = set()
    for row in load_suppression():
        if row.get("email"):
            suppressed_emails.add(normalize_email(row["email"]))
        if row.get("domain"):
            suppressed_domains.add(row["domain"].strip().lower())
    return suppressed_emails, suppressed_domains


def sent_in_last_24_hours() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    count = 0
    for row in read_rows(OUTREACH_LOG_CSV):
        if row.get("event_type") not in {"sent", "demo_followup_sent"}:
            continue
        timestamp = parse_iso_datetime(row.get("timestamp", ""))
        if timestamp and timestamp >= cutoff:
            count += 1
    return count


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def gmail_after_date(value: str) -> str:
    parsed = parse_iso_datetime(value)
    if not parsed:
        return "newer_than:180d"
    return f"after:{parsed.strftime('%Y/%m/%d')}"
