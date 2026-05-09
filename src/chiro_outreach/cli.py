import argparse
import json
import sys
from collections import Counter

from .config import load_config
from .csv_store import CONTACT_FIELDS, SUPPRESSION_FIELDS, append_row, ensure_data_files, load_contacts, save_contacts
from .demo_followup import run_demo_followups
from .email_finder import email_matches_to_json, enrich_website, form_fields_to_json, is_public_contact_email
from .form_submitter import draft_contact_forms, preview_form_plans, submit_form_batch
from .gmail_client import check_replies, send_batch
from .normalization import email_domain, normalize_email, stable_id
from .paths import CONTACTS_CSV, CONFIG_LOCAL, SUPPRESSION_CSV, TARGET_MARKETS
from .places import google_maps_api_key, search_places
from .sheets_client import mark_completed_from_form_responses, pull_form_responses, sync_csvs_to_google_sheet
from .templates import OUTREACH_VARIANTS, build_outreach_email
from .time_utils import utc_now_iso


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ensure_data_files()
    return args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chiropractic clinic outreach validation pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create local config/data files.")
    init_parser.set_defaults(func=cmd_init)

    discover = subparsers.add_parser("discover", help="Find clinics via Google Places Text Search.")
    discover.add_argument("--states", default="OH,GA", help="Comma-separated state codes.")
    discover.add_argument("--max-per-query", type=int, default=20)
    discover.add_argument("--limit-queries", type=int, default=0, help="Debug limit for number of queries.")
    discover.set_defaults(func=cmd_discover)

    enrich = subparsers.add_parser("enrich-emails", help="Find public emails from clinic websites.")
    enrich.add_argument("--limit", type=int, default=50)
    enrich.add_argument("--delay-seconds", type=float, default=1.5)
    enrich.add_argument("--max-pages", type=int, default=5)
    enrich.add_argument("--force", action="store_true", help="Re-scan already enriched contacts.")
    enrich.add_argument("--weak-only", action="store_true", help="Only scan contacts without an email or contact form.")
    enrich.add_argument("--ignore-robots", action="store_true")
    enrich.set_defaults(func=cmd_enrich_emails)

    draft = subparsers.add_parser("draft", help="Generate personalized outreach drafts.")
    draft.add_argument("--limit", type=int, default=0)
    draft.add_argument("--variant", default="", choices=("", *OUTREACH_VARIANTS))
    draft.add_argument("--rotate-variants", action="store_true")
    draft.set_defaults(func=cmd_draft)

    send = subparsers.add_parser("send", help="Send or dry-run a controlled outreach batch.")
    send.add_argument("--limit", type=int, default=None)
    send.add_argument("--send", action="store_true", help="Actually send. Omit for dry run.")
    send.add_argument("--min-delay-seconds", type=int, default=None)
    send.add_argument("--max-delay-seconds", type=int, default=None)
    send.set_defaults(func=cmd_send)

    demo_followups = subparsers.add_parser("demo-followups", help="Draft or send demo follow-up emails.")
    demo_followups.add_argument("--limit", type=int, default=None)
    demo_followups.add_argument("--send", action="store_true", help="Actually send. Omit for dry run.")
    demo_followups.add_argument("--contacts-only", action="store_true", help="Only follow up with previously contacted clinics.")
    demo_followups.add_argument("--respondents-only", action="store_true", help="Only follow up with survey respondents who left email.")
    demo_followups.add_argument("--min-delay-seconds", type=int, default=None)
    demo_followups.add_argument("--max-delay-seconds", type=int, default=None)
    demo_followups.set_defaults(func=cmd_demo_followups)

    form_draft = subparsers.add_parser("draft-forms", help="Draft outreach messages for contact-form-only leads.")
    form_draft.add_argument("--limit", type=int, default=10)
    form_draft.add_argument("--variant", default="research_short", choices=OUTREACH_VARIANTS)
    form_draft.set_defaults(func=cmd_draft_forms)

    form_preview = subparsers.add_parser("preview-forms", help="Preview contact form fill plans without submitting.")
    form_preview.add_argument("--limit", type=int, default=10)
    form_preview.set_defaults(func=cmd_preview_forms)

    form_submit = subparsers.add_parser("submit-forms", help="Submit reviewed contact forms. Dry-run unless --send.")
    form_submit.add_argument("--limit", type=int, default=None)
    form_submit.add_argument("--send", action="store_true", help="Actually submit forms. Omit for dry run.")
    form_submit.add_argument("--min-delay-seconds", type=int, default=None)
    form_submit.add_argument("--max-delay-seconds", type=int, default=None)
    form_submit.set_defaults(func=cmd_submit_forms)

    replies = subparsers.add_parser("check-replies", help="Mark contacts as responded when Gmail replies are found.")
    replies.add_argument("--limit", type=int, default=100)
    replies.set_defaults(func=cmd_check_replies)

    suppress = subparsers.add_parser("suppress", help="Add an opt-out email or domain to the suppression list.")
    suppress.add_argument("--email", default="")
    suppress.add_argument("--domain", default="")
    suppress.add_argument("--reason", default="opt-out")
    suppress.set_defaults(func=cmd_suppress)

    clean = subparsers.add_parser("clean-emails", help="Remove vendor/debug emails from contacts and candidates.")
    clean.set_defaults(func=cmd_clean_emails)

    sheets = subparsers.add_parser("sync-sheets", help="Push local outreach CSVs to Google Sheets tabs.")
    sheets.add_argument("--spreadsheet-id", default="")
    sheets.set_defaults(func=cmd_sync_sheets)

    pull = subparsers.add_parser("pull-responses", help="Pull Google Form responses and mark completed contacts.")
    pull.add_argument("--spreadsheet-id", default="")
    pull.add_argument("--range", default="")
    pull.set_defaults(func=cmd_pull_responses)

    status = subparsers.add_parser("status", help="Show outreach funnel counts.")
    status.set_defaults(func=cmd_status)

    return parser


def cmd_init(_args: argparse.Namespace) -> int:
    ensure_data_files()
    if not CONFIG_LOCAL.exists():
        CONFIG_LOCAL.write_text(
            json.dumps(load_config(), indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"Initialized outreach workspace at {CONTACTS_CSV.parent.parent}")
    print(f"Edit local config: {CONFIG_LOCAL}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    api_key = google_maps_api_key()
    targets = json.loads(TARGET_MARKETS.read_text(encoding="utf-8"))
    selected_states = {state.strip().upper() for state in args.states.split(",") if state.strip()}
    queries = build_queries(targets, selected_states)
    if args.limit_queries:
        queries = queries[: args.limit_queries]

    existing = load_contacts()
    by_key = contact_index(existing)
    added = 0
    updated = 0

    for query in queries:
        print(f"Searching: {query}")
        for contact in search_places(query, api_key, max_results=args.max_per_query, states=selected_states):
            key = dedupe_key(contact)
            if key in by_key:
                existing_row = by_key[key]
                merge_contact(existing_row, contact)
                updated += 1
            else:
                existing.append({field: contact.get(field, "") for field in CONTACT_FIELDS})
                by_key[key] = existing[-1]
                added += 1

    save_contacts(existing)
    print(f"Discovery complete: {added} added, {updated} updated, {len(existing)} total contacts.")
    return 0


def build_queries(targets: dict, selected_states: set[str]) -> list[str]:
    queries: list[str] = []
    for state_code, state in targets["states"].items():
        if state_code not in selected_states:
            continue
        for city in state["cities"]:
            for term in targets["search_terms"]:
                queries.append(f"{term} in {city}, {state_code}")
    return queries


def contact_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {dedupe_key(row): row for row in rows if dedupe_key(row)}


def dedupe_key(row: dict[str, str]) -> str:
    return row.get("google_place_id") or row.get("website") or stable_id(
        row.get("clinic_name", ""), row.get("city", ""), row.get("state", "")
    )


def merge_contact(existing: dict[str, str], incoming: dict[str, str]) -> None:
    for field in ["website", "address", "city", "state", "phone", "google_maps_url", "source_query"]:
        if incoming.get(field) and not existing.get(field):
            existing[field] = incoming[field]
    existing["updated_at"] = utc_now_iso()


def cmd_enrich_emails(args: argparse.Namespace) -> int:
    contacts = load_contacts()
    processed = 0
    found = 0
    forms_found = 0
    for contact in contacts:
        if processed >= args.limit:
            break
        if not contact.get("website"):
            continue
        if args.weak_only and (contact.get("public_email") or contact.get("contact_form_found") == "true"):
            continue
        if not args.force and contact.get("enrichment_status") == "enriched":
            continue

        processed += 1
        print(
            f"[{processed}/{args.limit}] Enriching {contact.get('clinic_name', 'unknown clinic')} "
            f"({contact.get('website')})",
            flush=True,
        )
        result = enrich_website(
            contact["website"],
            delay_seconds=args.delay_seconds,
            respect_robots=not args.ignore_robots,
            max_pages=args.max_pages,
        )
        now = utc_now_iso()

        if result.best_email:
            contact["public_email"] = result.best_email.email
            contact["email_source_url"] = result.best_email.source_url
            contact["email_confidence"] = result.best_email.confidence
            found += 1
        contact["email_candidates_json"] = email_matches_to_json(result.email_matches)

        if result.best_form:
            contact["contact_form_found"] = "true"
            contact["contact_form_url"] = result.best_form.page_url
            contact["contact_form_action"] = result.best_form.action
            contact["contact_form_method"] = result.best_form.method
            contact["contact_form_status"] = "blocked_captcha" if result.best_form.requires_captcha else "needs_review"
            contact["form_fields_json"] = form_fields_to_json(result.best_form)
            contact["form_submit_text"] = result.best_form.submit_text
            contact["form_requires_captcha"] = "true" if result.best_form.requires_captcha else "false"
            forms_found += 1
        else:
            contact["contact_form_found"] = "false"
            contact["contact_form_status"] = "not_found"

        apply_enrichment_status(contact)
        contact["pages_scanned"] = " | ".join(result.pages_scanned)
        contact["enrichment_status"] = "enriched"
        contact["enrichment_notes"] = " | ".join(result.notes)
        contact["lead_quality_score"] = str(lead_quality_score(contact))
        contact["updated_at"] = now
        print(
            f"  -> email={contact.get('public_email') or '-'} "
            f"form={contact.get('contact_form_status') or '-'} "
            f"pages={len(result.pages_scanned)}",
            flush=True,
        )
    save_contacts(contacts)
    print(f"Enrichment complete: processed {processed}, emails found {found}, contact forms found {forms_found}.")
    return 0


def apply_enrichment_status(contact: dict[str, str]) -> None:
    if contact.get("public_email"):
        contact["best_contact_channel"] = "email"
        contact["discovery_status"] = "email_found"
        update_outreach_status_if_open(contact, "ready")
    elif contact.get("contact_form_found") == "true":
        contact["best_contact_channel"] = "contact_form"
        contact["discovery_status"] = "contact_form_found"
        update_outreach_status_if_open(contact, "form_needs_review")
    elif contact.get("phone"):
        contact["best_contact_channel"] = "phone_only"
        contact["discovery_status"] = "phone_only"
        update_outreach_status_if_open(contact, "not_ready")
    else:
        contact["best_contact_channel"] = "none"
        contact["discovery_status"] = "contact_missing"
        update_outreach_status_if_open(contact, "not_ready")


def update_outreach_status_if_open(contact: dict[str, str], status: str) -> None:
    protected = {"sent", "responded", "completed_form", "suppressed"}
    if contact.get("outreach_status") not in protected:
        contact["outreach_status"] = status


def lead_quality_score(contact: dict[str, str]) -> int:
    score = 0
    if contact.get("public_email"):
        confidence = contact.get("email_confidence", "")
        score += {"high": 80, "medium": 65, "low": 45}.get(confidence, 55)
    elif contact.get("contact_form_found") == "true":
        score += 45
    elif contact.get("phone"):
        score += 20
    if contact.get("website"):
        score += 10
    if contact.get("city") and contact.get("state"):
        score += 5
    if contact.get("form_requires_captcha") == "true":
        score -= 10
    return max(0, min(100, score))


def cmd_draft(args: argparse.Namespace) -> int:
    config = load_config()
    contacts = load_contacts()
    drafted = 0
    for contact in contacts:
        if args.limit and drafted >= args.limit:
            break
        if not contact.get("public_email"):
            continue
        if contact.get("outreach_status") not in {"ready", "draft_ready", "not_ready"}:
            continue
        if args.rotate_variants:
            variant = OUTREACH_VARIANTS[drafted % len(OUTREACH_VARIANTS)]
        else:
            variant = args.variant or contact.get("outreach_variant") or "research_short"
        subject, body = build_outreach_email(contact, config, variant=variant)
        contact["outreach_variant"] = variant
        contact["personalized_subject"] = subject
        contact["personalized_body"] = body
        contact["outreach_status"] = "draft_ready"
        contact["updated_at"] = utc_now_iso()
        drafted += 1
    save_contacts(contacts)
    print(f"Drafted {drafted} outreach emails.")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    config = load_config()
    limit = args.limit or int(config.get("batch_send_cap", 10))
    min_delay = args.min_delay_seconds or int(config.get("min_delay_seconds", 120))
    max_delay = args.max_delay_seconds or int(config.get("max_delay_seconds", 360))
    count = send_batch(config, limit, min_delay, max_delay, args.send)
    mode = "sent" if args.send else "dry-run checked"
    print(f"{mode}: {count} contacts.")
    return 0


def cmd_demo_followups(args: argparse.Namespace) -> int:
    config = load_config()
    limit = args.limit or int(config.get("batch_send_cap", 10))
    min_delay = args.min_delay_seconds or int(config.get("min_delay_seconds", 120))
    max_delay = args.max_delay_seconds or int(config.get("max_delay_seconds", 360))
    include_contacts = not args.respondents_only
    include_respondents = not args.contacts_only
    count, report_path = run_demo_followups(
        config,
        limit,
        min_delay,
        max_delay,
        args.send,
        include_contacts=include_contacts,
        include_respondents=include_respondents,
    )
    mode = "sent" if args.send else "dry-run drafted"
    print(f"{mode}: {count} demo follow-ups.")
    print(f"Draft CSV: {report_path}")
    return 0


def cmd_draft_forms(args: argparse.Namespace) -> int:
    count = draft_contact_forms(load_config(), limit=args.limit, variant=args.variant)
    print(f"Drafted {count} contact-form outreach messages.")
    return 0


def cmd_preview_forms(args: argparse.Namespace) -> int:
    plans = preview_form_plans(load_config(), limit=args.limit)
    for index, plan in enumerate(plans, start=1):
        print(f"[{index}] {plan.clinic_name}")
        print(f"  URL: {plan.form_url}")
        print(f"  Subject: {plan.subject}")
        print(f"  Blocked: {plan.blocked_reason or '-'}")
        print("  Fields:")
        for field in plan.fields:
            masked = field.value
            if field.reason == "sender_email" and "@" in masked:
                local, domain = masked.split("@", 1)
                masked = f"{local[:2]}***@{domain}"
            print(f"    - {field.name or field.selector}: {field.reason} required={field.required} value={masked[:80]}")
    print(f"Previewed {len(plans)} contact-form plans.")
    return 0


def cmd_submit_forms(args: argparse.Namespace) -> int:
    config = load_config()
    limit = args.limit or int(config.get("batch_send_cap", 10))
    min_delay = args.min_delay_seconds or int(config.get("min_delay_seconds", 120))
    max_delay = args.max_delay_seconds or int(config.get("max_delay_seconds", 360))
    count = submit_form_batch(config, limit, min_delay, max_delay, args.send)
    mode = "submitted" if args.send else "dry-run checked"
    print(f"{mode}: {count} contact forms.")
    return 0


def cmd_check_replies(args: argparse.Namespace) -> int:
    updated = check_replies(load_config(), limit=args.limit)
    print(f"Marked {updated} contacts as responded.")
    return 0


def cmd_suppress(args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    domain = args.domain.strip().lower() or email_domain(email)
    if not email and not domain:
        raise RuntimeError("Pass --email or --domain.")

    now = utc_now_iso()
    append_row(
        SUPPRESSION_CSV,
        {"email": email, "domain": domain, "reason": args.reason, "created_at": now},
        SUPPRESSION_FIELDS,
    )

    contacts = load_contacts()
    updated = 0
    for contact in contacts:
        contact_email = normalize_email(contact.get("public_email", ""))
        contact_domain = email_domain(contact_email)
        if (email and contact_email == email) or (domain and contact_domain == domain):
            contact["outreach_status"] = "suppressed"
            contact["updated_at"] = now
            updated += 1
    if updated:
        save_contacts(contacts)

    print(f"Suppressed {email or domain}. Updated {updated} matching contacts.")
    return 0


def cmd_clean_emails(_args: argparse.Namespace) -> int:
    contacts = load_contacts()
    cleaned_primary = 0
    cleaned_candidates = 0

    for contact in contacts:
        primary = normalize_email(contact.get("public_email", ""))
        if primary and not is_public_contact_email(primary):
            contact["public_email"] = ""
            contact["email_source_url"] = ""
            contact["email_confidence"] = ""
            cleaned_primary += 1

        candidates_raw = contact.get("email_candidates_json", "")
        if candidates_raw:
            try:
                candidates = json.loads(candidates_raw)
            except json.JSONDecodeError:
                candidates = []
            filtered = [candidate for candidate in candidates if is_public_contact_email(candidate.get("email", ""))]
            if len(filtered) != len(candidates):
                contact["email_candidates_json"] = json.dumps(filtered, ensure_ascii=True, separators=(",", ":"))
                cleaned_candidates += len(candidates) - len(filtered)

        apply_enrichment_status(contact)
        contact["lead_quality_score"] = str(lead_quality_score(contact))
        contact["updated_at"] = utc_now_iso()

    save_contacts(contacts)
    print(f"Cleaned {cleaned_primary} primary emails and {cleaned_candidates} candidate emails.")
    return 0


def cmd_sync_sheets(args: argparse.Namespace) -> int:
    sync_csvs_to_google_sheet(args.spreadsheet_id or None)
    print("Synced local outreach CSVs to Google Sheets.")
    return 0


def cmd_pull_responses(args: argparse.Namespace) -> int:
    pulled = pull_form_responses(args.spreadsheet_id or None, args.range or None)
    completed = mark_completed_from_form_responses()
    print(f"Pulled {pulled} form responses. Marked {completed} contacts as completed_form.")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    contacts = load_contacts()
    discovery = Counter(row.get("discovery_status") or "unknown" for row in contacts)
    outreach = Counter(row.get("outreach_status") or "unknown" for row in contacts)
    states = Counter(row.get("state") or "unknown" for row in contacts)
    channels = Counter(row.get("best_contact_channel") or "unknown" for row in contacts)
    forms = Counter(row.get("contact_form_status") or "unknown" for row in contacts)
    print(f"Contacts: {len(contacts)}")
    print("By state:", dict(states))
    print("Discovery:", dict(discovery))
    print("Best channel:", dict(channels))
    print("Contact forms:", dict(forms))
    print("Outreach:", dict(outreach))
    print(f"CSV: {CONTACTS_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
