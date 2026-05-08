from .normalization import clean_cell


def clinic_greeting(contact: dict[str, str]) -> str:
    name = clean_cell(contact.get("clinic_name", ""))
    if name:
        return f"Hi {name} team,"
    return "Hi,"


OUTREACH_VARIANTS = ("research_short", "ops_pain", "owner_operator", "front_desk")


def build_outreach_email(contact: dict[str, str], config: dict[str, str], variant: str = "research_short") -> tuple[str, str]:
    city = clean_cell(contact.get("city", "your area"))
    state = clean_cell(contact.get("state", ""))
    location = f"{city}, {state}".strip(", ")
    sender_name = clean_cell(config.get("sender_name", ""))
    company_name = clean_cell(config.get("company_name", ""))
    postal_address = clean_cell(config.get("postal_address", ""))
    survey_url = clean_cell(config.get("survey_url", "https://forms.gle/HjWbEG3Z7hzNY9L1A"))
    signature_lines = [line for line in [sender_name, company_name, postal_address] if line]
    signature = "\n".join(signature_lines)

    if variant == "ops_pain":
        subject = f"Clinic ops bottleneck question in {location}" if location else "Clinic ops bottleneck question"
        body = f"""{clinic_greeting(contact)}

I am researching which admin or operational bottlenecks cost chiropractic clinics the most staff time each week.

If someone at your clinic has 3 minutes, could they share what is most painful right now?
{survey_url}

No sales call required. I am looking for one repeated problem that might be worth solving with simple software.

Thanks,
{signature}

If you would rather I not contact your clinic again, reply "opt out" and I will remove you."""
        return subject, body

    if variant == "owner_operator":
        subject = "Question about chiropractic clinic admin time"
        body = f"""{clinic_greeting(contact)}

I am doing quick research with chiropractic clinic owners and operators about the workflows that quietly drain revenue or staff time.

Would you be open to answering this 3-minute survey?
{survey_url}

I am not trying to book a sales call. I am using the responses to decide whether there is one narrow software workflow clinics would actually value.

Thanks,
{signature}

If you would rather I not contact your clinic again, reply "opt out" and I will remove you."""
        return subject, body

    if variant == "front_desk":
        subject = "3-minute front desk workflow question"
        body = f"""{clinic_greeting(contact)}

I am researching which front desk or admin tasks waste the most time inside chiropractic clinics.

If the right person on your team has 3 minutes, this short survey would help:
{survey_url}

No sales call required. I am trying to identify one repeated workflow problem before building anything.

Thanks,
{signature}

If you would rather I not contact your clinic again, reply "opt out" and I will remove you."""
        return subject, body

    subject = f"Quick chiropractic ops question in {location}" if location else "Quick chiropractic ops question"
    body = f"""{clinic_greeting(contact)}

I am doing short market research with chiropractic clinics in {location or "the U.S."} to understand which admin or operations bottlenecks cost the most time each week.

If someone on your team has 3 minutes, would you mind answering this short survey?
{survey_url}

I am using the responses to decide whether there is one narrow software workflow worth building for clinics. No sales call required.

Disclosure: this is a one-time market research message for a potential software product.

Thanks,
{signature}

If you would rather I not contact your clinic again, reply "opt out" and I will remove you."""

    return subject, body
