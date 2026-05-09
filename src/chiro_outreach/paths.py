from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parents[1]
CONFIG_DIR = PROJECT_DIR / "config"
DATA_DIR = PROJECT_DIR / "data"
REPORTS_DIR = PROJECT_DIR / "reports"
SECRETS_DIR = PROJECT_DIR / ".secrets"

CONTACTS_CSV = DATA_DIR / "contacts.csv"
OUTREACH_LOG_CSV = DATA_DIR / "outreach_log.csv"
SUPPRESSION_CSV = DATA_DIR / "suppression_list.csv"
MANUAL_RESPONSES_CSV = DATA_DIR / "manual_responses.csv"
FORM_RESPONSES_CSV = DATA_DIR / "form_responses.csv"
CONFIG_EXAMPLE = CONFIG_DIR / "outreach_config.example.json"
CONFIG_LOCAL = CONFIG_DIR / "outreach_config.local.json"
TARGET_MARKETS = CONFIG_DIR / "target_markets.json"
