import html
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from .normalization import EMAIL_RE, email_domain, normalize_email, normalize_url, url_domain


USER_AGENT = "ChiroOutreachResearchBot/0.2 (+market-research; respectful low-rate crawler)"
PAGE_TIMEOUT_SECONDS = 8
ROBOTS_TIMEOUT_SECONDS = 3
CONTACT_PATHS = [
    "",
    "/contact",
    "/contact-us",
    "/contacts",
    "/about",
    "/about-us",
    "/our-team",
    "/team",
    "/staff",
    "/meet-the-team",
    "/meet-the-doctor",
    "/doctors",
    "/providers",
    "/locations",
    "/location",
    "/new-patients",
    "/appointment",
    "/appointments",
    "/schedule",
    "/book-online",
]
CONTACT_LINK_KEYWORDS = {
    "about",
    "appointment",
    "book",
    "contact",
    "doctor",
    "dr",
    "location",
    "meet",
    "office",
    "provider",
    "schedule",
    "staff",
    "team",
}
PREFERRED_EMAIL_PREFIXES = {
    "admin",
    "appointments",
    "billing",
    "care",
    "contact",
    "frontdesk",
    "front.desk",
    "front-desk",
    "hello",
    "info",
    "office",
    "patientcare",
    "patients",
    "reception",
    "receptionist",
    "schedule",
    "scheduling",
}
OWNER_EMAIL_HINTS = ("dr", "doctor", "doc")
BLOCKED_EMAIL_PREFIXES = {
    "abuse",
    "dns",
    "example",
    "hostmaster",
    "mailer-daemon",
    "no-reply",
    "noreply",
    "postmaster",
    "privacy",
    "security",
    "webmaster",
}
BLOCKED_EMAIL_DOMAINS = {
    "domain.com",
    "email.com",
    "example.com",
    "example.org",
    "sentry.io",
}
BLOCKED_EMAIL_DOMAIN_SUFFIXES = {
    "sentry-next.wixpress.com",
    "sentry.wixpress.com",
    "wixpress.com",
}
FORM_NEGATIVE_TERMS = {
    "comment",
    "login",
    "newsletter",
    "password",
    "review",
    "search",
    "subscribe",
    "wp-login",
}
FORM_POSITIVE_TERMS = {
    "appointment",
    "contact",
    "email",
    "inquiry",
    "message",
    "name",
    "phone",
    "question",
    "request",
    "schedule",
}
FORM_IFRAME_HINTS = ("form", "jotform", "contact", "appointment", "schedule", "book", "intake", "patient")


@dataclass
class EmailMatch:
    email: str
    source_url: str
    score: int
    confidence: str
    kind: str = "public_email"
    context: str = ""


@dataclass
class FormField:
    name: str
    field_type: str
    label: str = ""
    required: bool = False
    placeholder: str = ""


@dataclass
class ContactFormInfo:
    page_url: str
    action: str
    method: str
    fields: list[FormField] = field(default_factory=list)
    submit_text: str = ""
    requires_captcha: bool = False
    score: int = 0
    form_kind: str = "html_form"


@dataclass
class PageFetch:
    url: str
    final_url: str
    html_text: str
    visible_text: str
    soup: object | None


@dataclass
class EnrichmentResult:
    website: str
    best_email: EmailMatch | None
    email_matches: list[EmailMatch]
    best_form: ContactFormInfo | None
    contact_forms: list[ContactFormInfo]
    pages_scanned: list[str]
    notes: list[str]


def find_public_email(website: str, delay_seconds: float = 1.5, respect_robots: bool = True) -> EmailMatch | None:
    return enrich_website(website, delay_seconds=delay_seconds, respect_robots=respect_robots).best_email


def enrich_website(
    website: str,
    delay_seconds: float = 1.5,
    respect_robots: bool = True,
    max_pages: int = 12,
) -> EnrichmentResult:
    base_url = normalize_url(website)
    if not base_url:
        return EnrichmentResult("", None, [], None, [], [], ["missing_website"])

    robot = build_robot_parser(base_url) if respect_robots else None
    candidates = candidate_urls(base_url)
    seen_urls: set[str] = set()
    pages_scanned: list[str] = []
    email_matches: list[EmailMatch] = []
    contact_forms: list[ContactFormInfo] = []
    notes: list[str] = []

    while candidates and len(pages_scanned) < max_pages:
        url = candidates.pop(0)
        normalized = normalize_url(url)
        if not normalized or normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        if not same_site(base_url, normalized):
            continue
        if robot and not robot.can_fetch(USER_AGENT, normalized):
            notes.append(f"robots_blocked:{normalized}")
            continue

        page = fetch_page(normalized)
        if not page:
            notes.append(f"fetch_failed:{normalized}")
            continue

        pages_scanned.append(page.final_url)
        emails = extract_emails_from_page(page)
        email_matches.extend(score_emails(emails, page.final_url, base_url, page.visible_text))
        forms = detect_contact_forms(page)
        contact_forms.extend(forms)

        if page.soup:
            for link in discover_contact_links(page.soup, page.final_url, base_url):
                if link not in seen_urls and link not in candidates:
                    candidates.append(link)

        if candidates and len(pages_scanned) < max_pages:
            time.sleep(delay_seconds)

    email_matches = dedupe_email_matches(email_matches)
    contact_forms = dedupe_contact_forms(contact_forms)
    best_email = email_matches[0] if email_matches else None
    best_form = contact_forms[0] if contact_forms else None

    return EnrichmentResult(
        website=base_url,
        best_email=best_email,
        email_matches=email_matches,
        best_form=best_form,
        contact_forms=contact_forms,
        pages_scanned=pages_scanned,
        notes=notes,
    )


def candidate_urls(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    urls = [urljoin(root, path) for path in CONTACT_PATHS]
    if parsed.path and parsed.path != "/":
        urls.insert(0, base_url)
    return list(dict.fromkeys(normalize_url(url) for url in urls))


def same_site(base_url: str, candidate_url: str) -> bool:
    base_domain = url_domain(base_url)
    candidate_domain = url_domain(candidate_url)
    return candidate_domain == base_domain or candidate_domain.endswith("." + base_domain)


def build_robot_parser(base_url: str) -> RobotFileParser | None:
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    robot = RobotFileParser()
    robot.set_url(robots_url)
    try:
        response = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=ROBOTS_TIMEOUT_SECONDS)
    except requests.RequestException:
        return None
    if response.status_code in {401, 403}:
        robot.disallow_all = True
        robot.modified()
        return robot
    if response.status_code >= 400:
        return None
    robot.parse(response.text.splitlines())
    robot.modified()
    return robot


def fetch_page(url: str) -> PageFetch | None:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=PAGE_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400 or "text/html" not in content_type:
            return None
    except requests.RequestException:
        return None

    html_text = html.unescape(response.text)
    soup = build_soup(html_text)
    visible_text = visible_page_text(soup, html_text)
    return PageFetch(url=url, final_url=normalize_url(response.url), html_text=html_text, visible_text=visible_text, soup=soup)


def build_soup(html_text: str):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    return BeautifulSoup(html_text, "html.parser")


def visible_page_text(soup, html_text: str) -> str:
    if not soup:
        text = re.sub(r"<(script|style).*?</\1>", " ", html_text, flags=re.IGNORECASE | re.DOTALL)
        return re.sub(r"<[^>]+>", " ", text)

    soup_copy = soup.__copy__()
    for tag in soup_copy(["script", "style", "noscript"]):
        tag.decompose()
    return soup_copy.get_text(" ", strip=True)


def discover_contact_links(soup, page_url: str, base_url: str) -> list[str]:
    scored_links: list[tuple[int, str]] = []
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if href.startswith(("mailto:", "tel:", "sms:", "javascript:")):
            continue
        absolute = normalize_url(urljoin(page_url, href.split("#", 1)[0]))
        if not absolute or not same_site(base_url, absolute):
            continue
        text = " ".join([link.get_text(" ", strip=True), href]).lower()
        score = sum(1 for keyword in CONTACT_LINK_KEYWORDS if keyword in text)
        if score:
            scored_links.append((score, absolute))

    scored_links.sort(key=lambda item: item[0], reverse=True)
    return list(dict.fromkeys(link for _score, link in scored_links))


def extract_emails_from_page(page: PageFetch) -> set[str]:
    values: set[str] = set()
    if page.soup:
        for link in page.soup.find_all("a", href=True):
            href = html.unescape(link.get("href", ""))
            if href.lower().startswith("mailto:"):
                values.update(extract_emails(unquote(href.split(":", 1)[1].split("?", 1)[0])))
        for element in page.soup.select("[data-cfemail]"):
            decoded = decode_cloudflare_email(element.get("data-cfemail", ""))
            if decoded:
                values.add(normalize_email(decoded))

    values.update(extract_emails(page.visible_text))
    values.update(extract_emails(page.html_text))
    return values


def extract_emails(text: str) -> set[str]:
    cleaned = deobfuscate_email_text(html.unescape(text or ""))
    return {normalize_email(email).strip(".,;:)([]{}<>") for email in EMAIL_RE.findall(cleaned)}


def deobfuscate_email_text(text: str) -> str:
    cleaned = text.replace("\u00a0", " ")
    cleaned = re.sub(r"\s*(?:\[|\()\s*at\s*(?:\]|\))\s*", "@", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(?:at|AT)\s+", "@", cleaned)
    cleaned = re.sub(r"\s*(?:\[|\()\s*dot\s*(?:\]|\))\s*", ".", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(?:dot|DOT)\s+", ".", cleaned)
    cleaned = cleaned.replace("&#64;", "@").replace("&commat;", "@")
    return cleaned


def decode_cloudflare_email(value: str) -> str:
    try:
        key = int(value[:2], 16)
        return "".join(chr(int(value[i : i + 2], 16) ^ key) for i in range(2, len(value), 2))
    except Exception:
        return ""


def score_emails(emails: Iterable[str], source_url: str, base_url: str, page_text: str) -> list[EmailMatch]:
    website_domain = url_domain(base_url)
    scored: list[EmailMatch] = []
    for email in emails:
        prefix = email.split("@", 1)[0].lower()
        domain = email_domain(email)
        if not usable_email(email, prefix, domain):
            continue

        score = 20
        if domain == website_domain or domain.endswith("." + website_domain):
            score += 35
        elif domain in {"gmail.com", "outlook.com", "yahoo.com", "icloud.com"}:
            score += 5
        else:
            score -= 10

        if prefix in PREFERRED_EMAIL_PREFIXES:
            score += 20
        if any(prefix.startswith(hint) for hint in OWNER_EMAIL_HINTS):
            score += 10
        if prefix in BLOCKED_EMAIL_PREFIXES:
            score -= 25
        if re.search(r"\d{3,}", prefix):
            score -= 5
        if any(keyword in source_url.lower() for keyword in ("contact", "about", "team", "staff", "doctor")):
            score += 8

        scored.append(
            EmailMatch(
                email=email,
                source_url=source_url,
                score=score,
                confidence=email_confidence(score),
                context=email_context(page_text, email),
            )
        )
    return scored


def usable_email(email: str, prefix: str, domain: str) -> bool:
    if not domain or domain in BLOCKED_EMAIL_DOMAINS:
        return False
    if any(domain == suffix or domain.endswith("." + suffix) for suffix in BLOCKED_EMAIL_DOMAIN_SUFFIXES):
        return False
    if domain.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")):
        return False
    if prefix in BLOCKED_EMAIL_PREFIXES:
        return False
    if re.fullmatch(r"[a-f0-9]{24,}", prefix):
        return False
    if ".." in email or email.count("@") != 1:
        return False
    return True


def is_public_contact_email(email: str) -> bool:
    email = normalize_email(email)
    if "@" not in email:
        return False
    prefix = email.split("@", 1)[0].lower()
    return usable_email(email, prefix, email_domain(email))


def email_confidence(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def email_context(page_text: str, email: str, window: int = 90) -> str:
    lower = page_text.lower()
    index = lower.find(email.lower())
    if index < 0:
        return ""
    start = max(0, index - window)
    end = min(len(page_text), index + len(email) + window)
    return " ".join(page_text[start:end].split())


def dedupe_email_matches(matches: list[EmailMatch]) -> list[EmailMatch]:
    by_email: dict[str, EmailMatch] = {}
    for match in matches:
        existing = by_email.get(match.email)
        if not existing or match.score > existing.score:
            by_email[match.email] = match
    return sorted(by_email.values(), key=lambda match: match.score, reverse=True)


def detect_contact_forms(page: PageFetch) -> list[ContactFormInfo]:
    if not page.soup:
        return []

    forms: list[ContactFormInfo] = []
    for form in page.soup.find_all("form"):
        info = parse_form(form, page.final_url)
        if info and info.score >= 12:
            forms.append(info)

    forms.extend(detect_embedded_form_frames(page))
    return sorted(forms, key=lambda form: form.score, reverse=True)


def parse_form(form, page_url: str) -> ContactFormInfo | None:
    action = normalize_url(urljoin(page_url, form.get("action", "") or page_url))
    method = (form.get("method", "get") or "get").upper()
    fields = parse_form_fields(form)
    submit_text = submit_button_text(form)
    form_text = " ".join([form.get_text(" ", strip=True), action, " ".join(asdict(field)["name"] for field in fields)]).lower()

    if any(term in form_text for term in FORM_NEGATIVE_TERMS) and not any(term in form_text for term in FORM_POSITIVE_TERMS):
        return None

    requires_captcha = "captcha" in str(form).lower()
    field_names = " ".join(f"{field.name} {field.label} {field.placeholder} {field.field_type}" for field in fields).lower()
    score = 0
    score += 12 if "textarea" in field_names or "message" in field_names else 0
    score += 8 if "email" in field_names else 0
    score += 6 if "name" in field_names else 0
    score += 5 if "phone" in field_names or "tel" in field_names else 0
    score += 6 if any(term in form_text for term in ("contact", "request", "appointment", "schedule")) else 0
    score -= 10 if requires_captcha else 0
    score -= 12 if any(term in form_text for term in FORM_NEGATIVE_TERMS) else 0

    if not fields:
        return None

    return ContactFormInfo(
        page_url=page_url,
        action=action,
        method=method,
        fields=fields,
        submit_text=submit_text,
        requires_captcha=requires_captcha,
        score=score,
    )


def parse_form_fields(form) -> list[FormField]:
    fields: list[FormField] = []
    for element in form.find_all(["input", "textarea", "select"]):
        tag_name = element.name.lower()
        field_type = tag_name
        if tag_name == "input":
            field_type = (element.get("type", "text") or "text").lower()
        if field_type in {"hidden", "submit", "button", "reset", "image"}:
            continue

        name = element.get("name") or element.get("id") or ""
        label = field_label(form, element)
        placeholder = element.get("placeholder", "") or element.get("aria-label", "")
        fields.append(
            FormField(
                name=name,
                field_type=field_type,
                label=" ".join(label.split()),
                required=bool(element.get("required")),
                placeholder=" ".join(placeholder.split()),
            )
        )
    return fields


def field_label(form, element) -> str:
    element_id = element.get("id", "")
    if element_id:
        label = form.find("label", attrs={"for": element_id})
        if label:
            return label.get_text(" ", strip=True)
    parent_label = element.find_parent("label")
    if parent_label:
        return parent_label.get_text(" ", strip=True)
    return element.get("aria-label", "") or element.get("placeholder", "")


def submit_button_text(form) -> str:
    values: list[str] = []
    for button in form.find_all(["button", "input"]):
        tag_name = button.name.lower()
        input_type = (button.get("type", "") or "").lower()
        if tag_name == "button" and input_type in {"", "submit"}:
            values.append(button.get_text(" ", strip=True))
        if tag_name == "input" and input_type == "submit":
            values.append(button.get("value", ""))
    return " | ".join(value for value in values if value)


def detect_embedded_form_frames(page: PageFetch) -> list[ContactFormInfo]:
    forms: list[ContactFormInfo] = []
    for iframe in page.soup.find_all("iframe", src=True):
        src = normalize_url(urljoin(page.final_url, iframe.get("src", "")))
        text = " ".join([src, iframe.get("title", ""), iframe.get("name", "")]).lower()
        if any(hint in text for hint in FORM_IFRAME_HINTS):
            forms.append(
                ContactFormInfo(
                    page_url=page.final_url,
                    action=src,
                    method="IFRAME",
                    fields=[],
                    submit_text="",
                    requires_captcha="captcha" in text,
                    score=18,
                    form_kind="embedded_iframe",
                )
            )
    return forms


def dedupe_contact_forms(forms: list[ContactFormInfo]) -> list[ContactFormInfo]:
    by_key: dict[tuple[str, str], ContactFormInfo] = {}
    for form in forms:
        key = (form.page_url, form.action)
        existing = by_key.get(key)
        if not existing or form.score > existing.score:
            by_key[key] = form
    return sorted(by_key.values(), key=lambda form: form.score, reverse=True)


def email_matches_to_json(matches: list[EmailMatch]) -> str:
    return compact_json([asdict(match) for match in matches[:8]])


def form_fields_to_json(form: ContactFormInfo | None) -> str:
    if not form:
        return ""
    return compact_json([asdict(field) for field in form.fields])


def compact_json(value) -> str:
    try:
        import json

        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except Exception:
        return ""
