import hashlib
import re
from urllib.parse import urlparse, urlunparse


EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")


def stable_id(*parts: str) -> str:
    raw = "|".join(part.strip().lower() for part in parts if part)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def normalize_email(value: str) -> str:
    return value.strip().lower()


def email_domain(email: str) -> str:
    email = normalize_email(email)
    return email.split("@", 1)[1] if "@" in email else ""


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme, netloc, path, "", "", ""))


def url_domain(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    return parsed.netloc.lower()


def clean_phone(value: str) -> str:
    return " ".join((value or "").split())


def clean_cell(value: str) -> str:
    return " ".join((value or "").split())

