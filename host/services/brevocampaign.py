"""
email_campaigns/brevo.py

Low-level wrapper around the Brevo (ex-Sendinblue) REST API.
All HTTP calls are isolated here so nothing else in the codebase
knows about Brevo's API shape.
"""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BREVO_API_BASE = "https://api.brevo.com/v3"


def _headers():
    return {
        "accept":       "application/json",
        "content-type": "application/json",
        "api-key": settings.ANYMAIL["BREVO_API_KEY"],
    }


# ── Contact / List management ──────────────────────────────────────────────────

def create_contact_list(name: str) -> int:
    """
    Create a new Brevo contact list and return its list_id.
    Folder 1 is Brevo's default root folder.
    """
    response = requests.post(
        f"{BREVO_API_BASE}/contacts/lists",
        headers=_headers(),
        json={"name": name, "folderId": 1},
    )
    response.raise_for_status()
    return response.json()["id"]


def sync_contacts_to_list(list_id: int, contacts: list[dict]):
    """
    Upsert a batch of contacts into a Brevo list.
    contacts = [{"email": "...", "attributes": {"FIRSTNAME": "...", ...}}, ...]

    Brevo's import endpoint handles up to 150 contacts per call;
    we chunk automatically.
    """
    CHUNK_SIZE = 150
    for i in range(0, len(contacts), CHUNK_SIZE):
        chunk = contacts[i: i + CHUNK_SIZE]
        response = requests.post(
            f"{BREVO_API_BASE}/contacts/import",
            headers=_headers(),
            json={
                "listIds":         [list_id],
                "updateEnabled":   True,
                "jsonBody":        chunk,
            },
        )
        response.raise_for_status()


# ── Campaign management ────────────────────────────────────────────────────────

def create_email_campaign(
    name:         str,
    subject:      str,
    html_content: str,
    sender_name:  str,
    sender_email: str,
    list_id:      int,
) -> int:
    """
    Create a campaign in Brevo (status=draft) and return its campaign_id.
    """
    response = requests.post(
        f"{BREVO_API_BASE}/emailCampaigns",
        headers=_headers(),
        json={
            "name":        name,
            "subject":     subject,
            "htmlContent": html_content,
            "sender":      {"name": sender_name, "email": sender_email},
            "recipients":  {"listIds": [list_id]},
        },
    )
    response.raise_for_status()
    return response.json()["id"]


def send_email_campaign(campaign_id: int):
    """
    Trigger an immediate send for an existing Brevo campaign.
    """
    response = requests.post(
        f"{BREVO_API_BASE}/emailCampaigns/{campaign_id}/sendNow",
        headers=_headers(),
    )
    response.raise_for_status()


def get_campaign_stats(campaign_id: int) -> dict:
    """
    Fetch live stats for a single campaign from Brevo.
    Returns a dict with open_rate and click_rate (as percentages, 0–100).
    Returns zeros gracefully if the campaign hasn't been sent yet.
    """
    try:
        response = requests.get(
            f"{BREVO_API_BASE}/emailCampaigns/{campaign_id}",
            headers=_headers(),
        )
        response.raise_for_status()
        data       = response.json()
        statistics = data.get("statistics", {}).get("globalStats", {})

        sent     = statistics.get("sent", 0)
        opened   = statistics.get("uniqueOpens", 0)
        clicked  = statistics.get("uniqueClicks", 0)

        open_rate  = round((opened  / sent) * 100, 2) if sent else 0.0
        click_rate = round((clicked / sent) * 100, 2) if sent else 0.0

        return {"open_rate": open_rate, "click_rate": click_rate}

    except Exception as exc:
        logger.warning("Failed to fetch Brevo stats for campaign %s: %s", campaign_id, exc)
        return {"open_rate": 0.0, "click_rate": 0.0}


def get_bulk_campaign_stats(campaign_ids: list[int]) -> dict[int, dict]:
    """
    Fetch stats for multiple campaigns in one pass.
    Returns {campaign_id: {open_rate, click_rate}}.
    """
    return {cid: get_campaign_stats(cid) for cid in campaign_ids}


def send_transactional_email(
    to_email:     str,
    sender_name:  str,
    sender_email: str,
    subject:      str,
    html_content: str,
):
    """
    Sends a one-off transactional email to a single recipient via Brevo.
    Uses /smtp/email endpoint — not campaign-based, instant delivery.
    """
    response = requests.post(
        f"{BREVO_API_BASE}/smtp/email",
        headers=_headers(),
        json={
            "sender":      {"name": sender_name, "email": sender_email},
            "to":          [{"email": to_email}],
            "subject":     subject,
            "htmlContent": html_content,
        },
    )
    response.raise_for_status()