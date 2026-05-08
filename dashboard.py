import re
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CONTACTS_CSV = DATA_DIR / "contacts.csv"
MANUAL_RESPONSES_CSV = DATA_DIR / "manual_responses.csv"
FORM_RESPONSES_CSV = DATA_DIR / "form_responses.csv"

PAIN_KEYWORDS = {
    "scheduling": ["schedule", "scheduling", "appointment", "reschedule", "calendar", "booking"],
    "insurance": ["insurance", "claim", "claims", "billing", "payer", "denial", "eligibility"],
    "documentation": ["documentation", "notes", "soap", "chart", "charting", "paperwork"],
    "no-shows": ["no-show", "no show", "missed appointment", "cancellation", "cancel"],
    "patient follow-up": ["follow up", "follow-up", "recall", "reactivation", "retention"],
    "front desk workload": ["front desk", "admin", "reception", "phone", "calls", "staff time"],
    "payments": ["payment", "collections", "copay", "invoice", "balance"],
    "marketing": ["marketing", "leads", "reviews", "referrals", "new patients"],
}


st.set_page_config(page_title="Chiro Outreach Dashboard", layout="wide")
st.title("Chiropractic Outreach Validation")


def rate(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round((numerator / denominator) * 100)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path).fillna("")


def chart_count(frame: pd.DataFrame, column: str) -> None:
    if column not in frame:
        st.info(f"No `{column}` column yet.")
        return
    counts = frame[column].replace("", "unknown").value_counts()
    st.bar_chart(counts)


def response_texts(manual: pd.DataFrame, forms: pd.DataFrame) -> list[str]:
    texts: list[str] = []
    if not manual.empty:
        for column in ["summary", "pain_points", "raw_notes"]:
            if column in manual:
                texts.extend(str(value) for value in manual[column].tolist() if str(value).strip())
    if not forms.empty:
        for _idx, row in forms.iterrows():
            texts.append(" ".join(str(value) for value in row.tolist() if str(value).strip()))
    return texts


def pain_keyword_counts(texts: list[str]) -> dict[str, int]:
    combined = "\n".join(texts).lower()
    counts: Counter[str] = Counter()
    for theme, keywords in PAIN_KEYWORDS.items():
        for keyword in keywords:
            counts[theme] += len(re.findall(rf"\b{re.escape(keyword)}\b", combined))
    return {theme: count for theme, count in counts.items() if count > 0}


contacts = read_csv(CONTACTS_CSV)
manual_responses = read_csv(MANUAL_RESPONSES_CSV)
form_responses = read_csv(FORM_RESPONSES_CSV)

if contacts.empty:
    st.warning("No contacts found yet. Run clinic discovery first.")
    st.stop()

total = len(contacts)
emails = int((contacts["public_email"] != "").sum()) if "public_email" in contacts else 0
forms = int((contacts["contact_form_found"] == "true").sum()) if "contact_form_found" in contacts else 0
sent = int(contacts.get("outreach_status", pd.Series(dtype=str)).isin(["sent", "responded", "completed_form"]).sum())
responded = int((contacts.get("responded_at", "") != "").sum()) if "responded_at" in contacts else 0
completed = int((contacts.get("completed_form_at", "") != "").sum()) if "completed_form_at" in contacts else 0

cols = st.columns(6)
cols[0].metric("Clinics", total)
cols[1].metric("Emails", emails, f"{rate(emails, total)}%")
cols[2].metric("Forms", forms, f"{rate(forms, total)}%")
cols[3].metric("Sent", sent)
cols[4].metric("Responses", responded, f"{rate(responded, sent)}%")
cols[5].metric("Surveys", completed, f"{rate(completed, sent)}%")

st.divider()

left, middle, right = st.columns(3)
with left:
    st.subheader("Best Contact Channel")
    chart_count(contacts, "best_contact_channel")
with middle:
    st.subheader("Outreach Status")
    chart_count(contacts, "outreach_status")
with right:
    st.subheader("Discovery Status")
    chart_count(contacts, "discovery_status")

left, right = st.columns(2)
with left:
    st.subheader("Contact Forms")
    chart_count(contacts, "contact_form_status")
with right:
    st.subheader("Lead Quality")
    quality = pd.to_numeric(contacts.get("lead_quality_score", pd.Series(dtype=str)), errors="coerce").fillna(0)
    st.bar_chart(quality.value_counts().sort_index())

st.divider()
st.subheader("Ready Leads")
ready_columns = [
    "clinic_name",
    "city",
    "state",
    "public_email",
    "email_confidence",
    "contact_form_status",
    "best_contact_channel",
    "lead_quality_score",
    "outreach_status",
]
existing_ready_columns = [column for column in ready_columns if column in contacts.columns]
ready = contacts[
    contacts.get("outreach_status", pd.Series(dtype=str)).isin(["ready", "draft_ready", "form_draft_ready", "form_needs_review"])
]
ready_table = ready[existing_ready_columns].copy()
if "lead_quality_score" in ready_table:
    ready_table["_quality_sort"] = pd.to_numeric(ready_table["lead_quality_score"], errors="coerce").fillna(0)
    ready_table = ready_table.sort_values(by="_quality_sort", ascending=False).drop(columns=["_quality_sort"])
st.dataframe(ready_table, use_container_width=True)

st.divider()
st.subheader("Pain Point Signals")
texts = response_texts(manual_responses, form_responses)
if texts:
    keyword_counts = pain_keyword_counts(texts)
    if keyword_counts:
        st.bar_chart(pd.Series(keyword_counts).sort_values(ascending=False))
    else:
        st.info("Responses exist, but no configured pain keywords were detected yet.")
else:
    st.info("No response text pulled yet. Run `pull-responses` after survey responses arrive.")
