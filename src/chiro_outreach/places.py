import os
import time
from typing import Any, Iterable

import requests

from .normalization import clean_cell, clean_phone, normalize_url, stable_id
from .time_utils import utc_now_iso


PLACES_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.addressComponents",
        "places.nationalPhoneNumber",
        "places.websiteUri",
        "places.googleMapsUri",
        "places.businessStatus",
        "nextPageToken",
    ]
)


def google_maps_api_key() -> str:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set GOOGLE_MAPS_API_KEY before running clinic discovery.")
    return api_key


def search_places(
    query: str,
    api_key: str,
    max_results: int = 40,
    page_size: int = 20,
    states: set[str] | None = None,
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    page_token = ""

    while len(results) < max_results:
        body: dict[str, Any] = {"textQuery": query, "pageSize": min(page_size, max_results - len(results))}
        if page_token:
            body["pageToken"] = page_token

        response = requests.post(
            PLACES_ENDPOINT,
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": PLACES_FIELD_MASK,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()

        for place in payload.get("places", []):
            contact = place_to_contact(place, query)
            if not contact:
                continue
            if states and contact.get("state") not in states:
                continue
            results.append(contact)
            if len(results) >= max_results:
                break

        page_token = payload.get("nextPageToken", "")
        if not page_token:
            break
        time.sleep(2)

    return results


def place_to_contact(place: dict[str, Any], query: str) -> dict[str, str] | None:
    if place.get("businessStatus") and place["businessStatus"] != "OPERATIONAL":
        return None

    place_id = clean_cell(place.get("id", ""))
    display_name = place.get("displayName", {}) or {}
    clinic_name = clean_cell(display_name.get("text", ""))
    address = clean_cell(place.get("formattedAddress", ""))
    if not clinic_name:
        return None

    city, state = city_state_from_components(place.get("addressComponents", []))
    website = normalize_url(place.get("websiteUri", ""))
    phone = clean_phone(place.get("nationalPhoneNumber", ""))
    now = utc_now_iso()

    return {
        "contact_id": stable_id(place_id, clinic_name, address),
        "clinic_name": clinic_name,
        "website": website,
        "public_email": "",
        "email_source_url": "",
        "address": address,
        "city": city,
        "state": state,
        "phone": phone,
        "google_place_id": place_id,
        "google_maps_url": clean_cell(place.get("googleMapsUri", "")),
        "source": "google_places_text_search",
        "source_query": query,
        "discovery_status": "website_found" if website else "no_website",
        "outreach_status": "not_ready",
        "sent_count": "0",
        "created_at": now,
        "updated_at": now,
    }


def city_state_from_components(components: Iterable[dict[str, Any]]) -> tuple[str, str]:
    city = ""
    state = ""
    for component in components:
        types = set(component.get("types", []))
        long_text = clean_cell(component.get("longText", ""))
        short_text = clean_cell(component.get("shortText", ""))
        if not city and types.intersection({"locality", "postal_town", "administrative_area_level_3"}):
            city = long_text or short_text
        if not state and "administrative_area_level_1" in types:
            state = short_text or long_text
    return city, state

