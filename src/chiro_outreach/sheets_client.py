import csv
from pathlib import Path
from typing import Iterable

from .config import load_config
from .csv_store import (
    CONTACT_FIELDS,
    OUTREACH_LOG_FIELDS,
    SUPPRESSION_FIELDS,
    load_contacts,
    read_rows,
    save_contacts,
)
from .google_auth import google_service
from .google_auth import OUTREACH_GOOGLE_SCOPES
from .normalization import normalize_email, stable_id
from .paths import CONTACTS_CSV, FORM_RESPONSES_CSV, OUTREACH_LOG_CSV, SUPPRESSION_CSV
from .time_utils import utc_now_iso


SHEETS_SCOPES = OUTREACH_GOOGLE_SCOPES


def sheets_service():
    return google_service("sheets", "v4", SHEETS_SCOPES)


def sync_csvs_to_google_sheet(spreadsheet_id: str | None = None) -> None:
    config = load_config()
    spreadsheet_id = spreadsheet_id or config.get("outreach_spreadsheet_id") or config.get("response_spreadsheet_id")
    if not spreadsheet_id:
        raise RuntimeError("Set outreach_spreadsheet_id or pass --spreadsheet-id.")

    service = sheets_service()
    ensure_sheets(service, spreadsheet_id, ["Outreach Contacts", "Outreach Log", "Suppression List"])
    update_tab(service, spreadsheet_id, "Outreach Contacts", CONTACT_FIELDS, read_rows(CONTACTS_CSV))
    update_tab(service, spreadsheet_id, "Outreach Log", OUTREACH_LOG_FIELDS, read_rows(OUTREACH_LOG_CSV))
    update_tab(service, spreadsheet_id, "Suppression List", SUPPRESSION_FIELDS, read_rows(SUPPRESSION_CSV))


def ensure_sheets(service, spreadsheet_id: str, titles: Iterable[str]) -> None:
    spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = {sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])}
    requests = [{"addSheet": {"properties": {"title": title}}} for title in titles if title not in existing]
    if requests:
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()


def update_tab(service, spreadsheet_id: str, tab_name: str, fields: list[str], rows: list[dict[str, str]]) -> None:
    values = [fields] + [[row.get(field, "") for field in fields] for row in rows]
    service.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range=f"'{tab_name}'!A:AZ").execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def pull_form_responses(spreadsheet_id: str | None = None, response_range: str | None = None) -> int:
    config = load_config()
    spreadsheet_id = spreadsheet_id or config.get("response_spreadsheet_id")
    response_range = response_range or config.get("form_responses_range", "Form Responses 1!A:Z")
    if not spreadsheet_id:
        raise RuntimeError("Set response_spreadsheet_id or pass --spreadsheet-id.")

    response = sheets_service().spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=response_range).execute()
    values = response.get("values", [])
    if not values:
        return 0

    write_matrix_csv(FORM_RESPONSES_CSV, values)
    return max(0, len(values) - 1)


def write_matrix_csv(path: Path, values: list[list[str]]) -> None:
    max_width = max(len(row) for row in values)
    normalized = [row + [""] * (max_width - len(row)) for row in values]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerows(normalized)


def mark_completed_from_form_responses() -> int:
    if not FORM_RESPONSES_CSV.exists():
        return 0

    with FORM_RESPONSES_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))
    if len(rows) < 2:
        return 0

    header = [cell.lower() for cell in rows[0]]
    timestamp_idx = 0
    email_indices = [i for i, col in enumerate(header) if "email" in col]
    clinic_indices = [i for i, col in enumerate(header) if "clinic" in col or "practice" in col or "company" in col]
    response_texts = []
    for row in rows[1:]:
        text = " ".join(row).lower()
        emails = {normalize_email(row[i]) for i in email_indices if i < len(row) and row[i]}
        clinics = {row[i].strip().lower() for i in clinic_indices if i < len(row) and row[i]}
        timestamp = row[timestamp_idx] if timestamp_idx < len(row) else ""
        response_texts.append((text, emails, clinics, timestamp))

    contacts = load_contacts()
    updated = 0
    for contact in contacts:
        email = normalize_email(contact.get("public_email", ""))
        clinic = contact.get("clinic_name", "").strip().lower()
        if contact.get("completed_form_at"):
            continue
        for text, emails, clinics, timestamp in response_texts:
            matched_email = email and (email in emails or email in text)
            matched_clinic = clinic and (clinic in clinics or clinic in text)
            if matched_email or matched_clinic:
                contact["outreach_status"] = "completed_form"
                contact["completed_form_at"] = timestamp or utc_now_iso()
                contact["updated_at"] = utc_now_iso()
                updated += 1
                break

    if updated:
        save_contacts(contacts)
    return updated
