import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .csv_store import append_log, load_contacts, read_rows, save_contacts
from .normalization import stable_id
from .paths import OUTREACH_LOG_CSV
from .templates import build_outreach_email
from .time_utils import parse_iso_datetime, utc_now_iso


FORM_OUTREACH_STATUSES = {"form_needs_review", "form_draft_ready"}


@dataclass
class FieldPlan:
    name: str
    value: str
    selector: str
    required: bool
    reason: str


@dataclass
class FormPlan:
    contact_id: str
    clinic_name: str
    form_url: str
    subject: str
    message: str
    fields: list[FieldPlan]
    blocked_reason: str = ""


def draft_contact_forms(config: dict[str, str], limit: int, variant: str) -> int:
    contacts = load_contacts()
    drafted = 0
    for contact in contacts:
        if drafted >= limit:
            break
        if contact.get("public_email"):
            continue
        if contact.get("contact_form_found") != "true":
            continue
        if contact.get("contact_form_status") != "needs_review":
            continue
        if contact.get("outreach_status") not in FORM_OUTREACH_STATUSES:
            continue

        subject, body = build_outreach_email(contact, config, variant=variant)
        contact["outreach_variant"] = variant
        contact["personalized_subject"] = subject
        contact["personalized_body"] = body
        contact["last_outreach_channel"] = "contact_form"
        contact["outreach_status"] = "form_draft_ready"
        contact["updated_at"] = utc_now_iso()
        drafted += 1
    save_contacts(contacts)
    return drafted


def build_form_plan(contact: dict[str, str], config: dict[str, str]) -> FormPlan:
    fields = parse_fields(contact.get("form_fields_json", ""))
    subject = contact.get("personalized_subject") or build_outreach_email(contact, config)[0]
    message = contact.get("personalized_body") or build_outreach_email(contact, config)[1]
    field_plans: list[FieldPlan] = []
    blocked_reasons: list[str] = []

    for field in fields:
        name = field.get("name", "")
        field_type = field.get("field_type", "")
        text = " ".join([name, field.get("label", ""), field.get("placeholder", ""), field_type]).lower()
        value, reason = value_for_field(text, field_type, subject, message, config)
        selector = selector_for_field(name, field_type)
        required = bool(field.get("required"))
        if required and not value:
            blocked_reasons.append(f"required_field_unmapped:{name or field_type}")
        if value and selector:
            field_plans.append(FieldPlan(name=name, value=value, selector=selector, required=required, reason=reason))

    if contact.get("form_requires_captcha") == "true":
        blocked_reasons.append("captcha_detected")

    if not field_plans:
        blocked_reasons.append("no_fillable_fields")

    return FormPlan(
        contact_id=contact.get("contact_id", ""),
        clinic_name=contact.get("clinic_name", ""),
        form_url=contact.get("contact_form_url", ""),
        subject=subject,
        message=message,
        fields=field_plans,
        blocked_reason=";".join(blocked_reasons),
    )


def parse_fields(raw_json: str) -> list[dict[str, str]]:
    if not raw_json:
        return []
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def value_for_field(text: str, field_type: str, subject: str, message: str, config: dict[str, str]) -> tuple[str, str]:
    if field_type in {"checkbox", "radio", "file"}:
        return "", "manual_review"
    if field_type == "email" or "email" in text:
        return config.get("sender_email", ""), "sender_email"
    if field_type in {"tel", "phone"} or "phone" in text or "mobile" in text:
        return config.get("sender_phone", ""), "sender_phone"
    if "subject" in text:
        return subject, "subject"
    if field_type == "textarea" or "message" in text or "comment" in text or "question" in text:
        return message, "message"
    if "first" in text and "name" in text:
        return first_name(config.get("sender_name", "")), "first_name"
    if "last" in text and "name" in text:
        return last_name(config.get("sender_name", "")), "last_name"
    if "name" in text:
        return config.get("sender_name", ""), "sender_name"
    if "company" in text or "business" in text:
        return config.get("company_name", ""), "company_name"
    return "", "unmapped"


def selector_for_field(name: str, field_type: str) -> str:
    if name:
        safe = css_escape(name)
        if field_type == "textarea":
            return f'textarea[name="{safe}"]'
        if field_type == "select":
            return f'select[name="{safe}"]'
        return f'input[name="{safe}"], textarea[name="{safe}"], select[name="{safe}"]'
    if field_type == "textarea":
        return "textarea"
    if field_type == "email":
        return 'input[type="email"]'
    if field_type in {"tel", "phone"}:
        return 'input[type="tel"]'
    return ""


def css_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def first_name(name: str) -> str:
    parts = name.strip().split()
    return parts[0] if parts else ""


def last_name(name: str) -> str:
    parts = name.strip().split()
    return parts[-1] if len(parts) > 1 else ""


def preview_form_plans(config: dict[str, str], limit: int) -> list[FormPlan]:
    plans: list[FormPlan] = []
    for contact in eligible_form_contacts(limit):
        plans.append(build_form_plan(contact, config))
    return plans


def submit_form_batch(
    config: dict[str, str],
    limit: int,
    min_delay_seconds: int,
    max_delay_seconds: int,
    actually_send: bool,
) -> int:
    if max_delay_seconds < min_delay_seconds:
        raise RuntimeError("max_delay_seconds must be greater than or equal to min_delay_seconds.")
    if actually_send:
        validate_submit_config(config)
        daily_remaining = int(config.get("daily_send_cap", 20)) - outreach_events_in_last_24_hours()
        if daily_remaining <= 0:
            raise RuntimeError("Daily outreach cap reached for the last rolling 24 hours.")
        limit = min(limit, daily_remaining)

    contacts = load_contacts()
    submitted = 0
    for contact in contacts:
        if submitted >= limit:
            break
        if not is_submit_candidate(contact):
            continue

        plan = build_form_plan(contact, config)
        if plan.blocked_reason:
            contact["contact_form_status"] = "blocked_review"
            contact["notes"] = append_note(contact.get("notes", ""), f"Form blocked: {plan.blocked_reason}")
            contact["updated_at"] = utc_now_iso()
            continue

        if actually_send:
            submit_one_form(plan, min_delay_seconds=min_delay_seconds, max_delay_seconds=max_delay_seconds)
            now = utc_now_iso()
            contact["contact_form_status"] = "submitted"
            contact["outreach_status"] = "sent"
            contact["last_outreach_channel"] = "contact_form"
            contact["last_contacted_at"] = now
            contact["sent_count"] = str(int(contact.get("sent_count") or "0") + 1)
            contact["updated_at"] = now
            append_log(
                {
                    "log_id": stable_id(contact.get("contact_id", ""), "form_submitted", now),
                    "contact_id": contact.get("contact_id", ""),
                    "clinic_name": contact.get("clinic_name", ""),
                    "email": "",
                    "event_type": "form_submitted",
                    "subject": plan.subject,
                    "timestamp": now,
                    "details": plan.form_url,
                }
            )
            submitted += 1
            if submitted < limit:
                time.sleep(random.randint(min_delay_seconds, max_delay_seconds))
        else:
            submitted += 1

    save_contacts(contacts)
    return submitted


def eligible_form_contacts(limit: int) -> list[dict[str, str]]:
    contacts = [contact for contact in load_contacts() if is_submit_candidate(contact)]
    return contacts[:limit]


def is_submit_candidate(contact: dict[str, str]) -> bool:
    if contact.get("public_email"):
        return False
    if contact.get("contact_form_found") != "true":
        return False
    if contact.get("contact_form_status") != "needs_review":
        return False
    return contact.get("outreach_status") in {"form_needs_review", "form_draft_ready"}


def validate_submit_config(config: dict[str, str]) -> None:
    missing = []
    for key in ["sender_name", "sender_email", "survey_url", "postal_address"]:
        value = str(config.get(key, "")).strip()
        if not value or value == "you@example.com" or "YOUR VALID POSTAL ADDRESS" in value:
            missing.append(key)
    if missing:
        raise RuntimeError(f"Cannot submit forms until these config values are set: {', '.join(missing)}")


def submit_one_form(plan: FormPlan, min_delay_seconds: int, max_delay_seconds: int) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is not installed. Run `pip install -r chiro_outreach/requirements.txt` "
            "and `python -m playwright install chromium` first."
        ) from error

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(plan.form_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(1.0, 2.5))
        for field in plan.fields:
            locator = page.locator(field.selector).first
            if locator.count() == 0:
                continue
            locator.fill(field.value, timeout=8000)
            time.sleep(random.uniform(0.4, 1.4))
        time.sleep(random.uniform(1.0, 2.5))
        page.locator('button[type="submit"], input[type="submit"], button').first.click(timeout=8000)
        time.sleep(random.randint(min_delay_seconds, max_delay_seconds))
        browser.close()


def outreach_events_in_last_24_hours() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    count = 0
    for row in read_rows(OUTREACH_LOG_CSV):
        if row.get("event_type") not in {"sent", "form_submitted"}:
            continue
        timestamp = parse_iso_datetime(row.get("timestamp", ""))
        if timestamp and timestamp >= cutoff:
            count += 1
    return count


def append_note(existing: str, note: str) -> str:
    if not existing:
        return note
    return f"{existing} | {note}"
