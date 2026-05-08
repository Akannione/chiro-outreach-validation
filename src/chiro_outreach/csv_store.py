import csv
from pathlib import Path
from typing import Iterable

from .paths import CONTACTS_CSV, MANUAL_RESPONSES_CSV, OUTREACH_LOG_CSV, SUPPRESSION_CSV


CONTACT_FIELDS = [
    "contact_id",
    "clinic_name",
    "website",
    "public_email",
    "email_source_url",
    "email_confidence",
    "email_candidates_json",
    "address",
    "city",
    "state",
    "phone",
    "best_contact_channel",
    "contact_form_found",
    "contact_form_url",
    "contact_form_action",
    "contact_form_method",
    "contact_form_status",
    "form_fields_json",
    "form_submit_text",
    "form_requires_captcha",
    "google_place_id",
    "google_maps_url",
    "source",
    "source_query",
    "discovery_status",
    "enrichment_status",
    "pages_scanned",
    "lead_quality_score",
    "outreach_status",
    "outreach_variant",
    "last_outreach_channel",
    "personalized_subject",
    "personalized_body",
    "last_contacted_at",
    "sent_count",
    "opened_at",
    "responded_at",
    "response_status",
    "completed_form_at",
    "survey_completed",
    "pain_point_summary",
    "enrichment_notes",
    "notes",
    "created_at",
    "updated_at",
]

OUTREACH_LOG_FIELDS = [
    "log_id",
    "contact_id",
    "clinic_name",
    "email",
    "event_type",
    "gmail_message_id",
    "gmail_thread_id",
    "subject",
    "timestamp",
    "details",
]

SUPPRESSION_FIELDS = ["email", "domain", "reason", "created_at"]
MANUAL_RESPONSE_FIELDS = [
    "response_id",
    "received_at",
    "contact_id",
    "clinic_name",
    "responder_email",
    "summary",
    "pain_points",
    "willingness_to_pay",
    "raw_notes",
]


def ensure_file(path: Path, fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        migrate_file(path, fields)
        return
    write_rows(path, [], fields)


def migrate_file(path: Path, fields: list[str]) -> None:
    rows = read_rows(path)
    if not rows:
        return
    existing_fields = list(rows[0].keys())
    if existing_fields == fields:
        return
    write_rows(path, rows, fields)


def ensure_data_files() -> None:
    ensure_file(CONTACTS_CSV, CONTACT_FIELDS)
    ensure_file(OUTREACH_LOG_CSV, OUTREACH_LOG_FIELDS)
    ensure_file(SUPPRESSION_CSV, SUPPRESSION_FIELDS)
    ensure_file(MANUAL_RESPONSES_CSV, MANUAL_RESPONSE_FIELDS)


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def write_rows(path: Path, rows: Iterable[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def append_row(path: Path, row: dict[str, str], fields: list[str]) -> None:
    ensure_file(path, fields)
    with path.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writerow({field: row.get(field, "") for field in fields})


def load_contacts() -> list[dict[str, str]]:
    ensure_file(CONTACTS_CSV, CONTACT_FIELDS)
    return read_rows(CONTACTS_CSV)


def save_contacts(rows: list[dict[str, str]]) -> None:
    write_rows(CONTACTS_CSV, rows, CONTACT_FIELDS)


def append_log(row: dict[str, str]) -> None:
    append_row(OUTREACH_LOG_CSV, row, OUTREACH_LOG_FIELDS)


def load_suppression() -> list[dict[str, str]]:
    ensure_file(SUPPRESSION_CSV, SUPPRESSION_FIELDS)
    return read_rows(SUPPRESSION_CSV)
