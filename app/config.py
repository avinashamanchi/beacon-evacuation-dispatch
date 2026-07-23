"""Environment loading and mode resolution for BEACON.

Missing Zendesk or OpenAI creds automatically force the corresponding
mock/fallback even when DEMO_MODE=false, each with a one-line startup warning.
"""
import json
import os

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


DEMO_MODE = _get_bool("DEMO_MODE", True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN", "").strip()
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL", "").strip()
ZENDESK_API_TOKEN = os.getenv("ZENDESK_API_TOKEN", "").strip()
ZENDESK_DISPATCH_FIELD_ID = os.getenv("ZENDESK_DISPATCH_FIELD_ID", "").strip()

try:
    FIRE_ETA_MINUTES = int(os.getenv("FIRE_ETA_MINUTES", "18"))
except ValueError:
    FIRE_ETA_MINUTES = 18

try:
    CREW_COUNTS = json.loads(
        os.getenv(
            "CREW_COUNTS",
            '{"fire_rescue": 2, "transport_assist": 3, "accessible_shelter": 99}',
        )
    )
except (ValueError, TypeError):
    CREW_COUNTS = {"fire_rescue": 2, "transport_assist": 3, "accessible_shelter": 99}

# Effective modes -------------------------------------------------------------
ZENDESK_CONFIGURED = all([ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN])
OPENAI_CONFIGURED = bool(OPENAI_API_KEY)

USE_MOCK_ZENDESK = DEMO_MODE or not ZENDESK_CONFIGURED
USE_FALLBACK_EXTRACTION = DEMO_MODE or not OPENAI_CONFIGURED

# Bulk seeding fans out to 30 costly OpenAI+Zendesk calls from a single request.
# Allowed freely in DEMO_MODE (zero cost); in live mode it must be opted in so a
# stray request to /api/seed can't rack up real charges.
ALLOW_BULK_SEED = DEMO_MODE or _get_bool("BEACON_ALLOW_BULK_SEED", False)


def startup_warnings() -> list[str]:
    warnings: list[str] = []
    if DEMO_MODE:
        warnings.append(
            "[BEACON] DEMO_MODE=true — mock Zendesk + canned extraction, zero network required."
        )
    else:
        if not ZENDESK_CONFIGURED:
            warnings.append(
                "[BEACON] Zendesk creds missing — falling back to MockZendeskClient."
            )
        if not OPENAI_CONFIGURED:
            warnings.append(
                "[BEACON] OpenAI key missing — falling back to keyword extraction."
            )
    return warnings
