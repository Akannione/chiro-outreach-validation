import json
import os
from pathlib import Path
from typing import Any

from .paths import CONFIG_EXAMPLE, CONFIG_LOCAL, PROJECT_DIR


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_config() -> dict[str, Any]:
    config = load_json(CONFIG_EXAMPLE)
    if CONFIG_LOCAL.exists():
        config.update(load_json(CONFIG_LOCAL))

    env_map = {
        "survey_url": "SURVEY_URL",
        "response_spreadsheet_id": "RESPONSE_SPREADSHEET_ID",
        "form_responses_range": "FORM_RESPONSES_RANGE",
        "outreach_spreadsheet_id": "OUTREACH_SPREADSHEET_ID",
        "sender_name": "GMAIL_SENDER_NAME",
        "sender_email": "GMAIL_SENDER_EMAIL",
        "sender_phone": "OUTREACH_SENDER_PHONE",
        "company_name": "OUTREACH_COMPANY_NAME",
        "postal_address": "OUTREACH_POSTAL_ADDRESS",
        "google_oauth_client_secret": "GOOGLE_OAUTH_CLIENT_SECRET",
        "google_oauth_token": "GOOGLE_OAUTH_TOKEN",
    }
    for key, env_name in env_map.items():
        if os.getenv(env_name):
            config[key] = os.environ[env_name]

    for key in ["daily_send_cap", "batch_send_cap", "min_delay_seconds", "max_delay_seconds"]:
        env_name = key.upper()
        if os.getenv(env_name):
            config[key] = int(os.environ[env_name])

    for key in ["google_oauth_client_secret", "google_oauth_token"]:
        value = Path(str(config[key]))
        if not value.is_absolute():
            config[key] = str(PROJECT_DIR / value)

    return config
