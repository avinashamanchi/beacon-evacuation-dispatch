"""Zendesk clients: one interface, two implementations chosen by config.

Every real network call is wrapped so a failure returns a graceful result and
never blanks the dashboard. The MockZendeskClient mirrors every signature.
"""
import httpx

from app import config
from app.security import valid_subdomain

PRIORITY_BY_PATH = {
    "fire_rescue": "urgent",
    "transport_assist": "urgent",
    "needs_human_review": "urgent",
    "accessible_shelter": "high",
    "auto_answered": "normal",
    "standard": "normal",
}

CANNED_GUIDE = [
    {
        "title": "Wildfire evacuation FAQ",
        "snippet": "Deductibles are waived for claims filed under an active evacuation order.",
        "url": "https://help.example.com/hc/en-us/articles/evac-faq",
    },
    {
        "title": "Filing a claim during an evacuation",
        "snippet": "You can file online with photos; receipts help but are not required for emergency supplies.",
        "url": "https://help.example.com/hc/en-us/articles/filing-a-claim",
    },
]


class ZendeskClient:
    """Real Zendesk Support + Guide + Side Conversations client (httpx)."""

    def __init__(self):
        # Reject a poisoned subdomain so the base URL can't be pointed at an
        # attacker-controlled host (SSRF / credential exfiltration guard).
        if not valid_subdomain(config.ZENDESK_SUBDOMAIN):
            raise ValueError("invalid ZENDESK_SUBDOMAIN — expected a bare subdomain label")
        self.base = f"https://{config.ZENDESK_SUBDOMAIN}.zendesk.com/api/v2"
        self.auth = (f"{config.ZENDESK_EMAIL}/token", config.ZENDESK_API_TOKEN)
        self.field_id = config.ZENDESK_DISPATCH_FIELD_ID
        self._client = httpx.Client(auth=self.auth, timeout=10.0)

    def create_ticket(self, name, email, subject, body):
        # Prefer the end-user request endpoint; fall back to /tickets on 403.
        try:
            r = self._client.post(
                f"{self.base}/requests.json",
                json={"request": {"subject": subject, "comment": {"body": body},
                                  "requester": {"name": name, "email": email}}},
            )
            if r.status_code == 403:
                raise httpx.HTTPStatusError("403", request=r.request, response=r)
            r.raise_for_status()
            return r.json()["request"]["id"]
        except httpx.HTTPStatusError:
            r = self._client.post(
                f"{self.base}/tickets.json",
                json={"ticket": {"subject": subject, "comment": {"body": body},
                                 "requester": {"name": name, "email": email}}},
            )
            r.raise_for_status()
            return r.json()["ticket"]["id"]

    def update_ticket(self, ticket_id, dispatch_path, tags, internal_note):
        ticket = {
            "priority": PRIORITY_BY_PATH.get(dispatch_path, "normal"),
            "tags": tags,
            "comment": {"body": internal_note, "public": False},
        }
        if self.field_id:
            ticket["custom_fields"] = [{"id": int(self.field_id), "value": dispatch_path}]
        r = self._client.put(f"{self.base}/tickets/{ticket_id}.json", json={"ticket": ticket})
        r.raise_for_status()
        return True

    def public_reply(self, ticket_id, body):
        r = self._client.put(
            f"{self.base}/tickets/{ticket_id}.json",
            json={"ticket": {"comment": {"body": body, "public": True}}},
        )
        r.raise_for_status()
        return True

    def search_guide(self, query):
        r = self._client.get(
            f"{self.base}/help_center/articles/search.json", params={"query": query}
        )
        r.raise_for_status()
        results = r.json().get("results", [])[:3]
        return [{"title": a.get("title", ""),
                 "snippet": (a.get("body", "") or "")[:160],
                 "url": a.get("html_url", "")} for a in results] or CANNED_GUIDE[:1]

    def open_side_conversation(self, ticket_id, team, summary):
        try:
            r = self._client.post(
                f"{self.base}/tickets/{ticket_id}/side_conversations.json",
                json={"message": {"subject": f"[BEACON DISPATCH] {team}",
                                  "body": summary}},
            )
            if r.status_code >= 400:
                raise httpx.HTTPStatusError("side-conv", request=r.request, response=r)
            return {"channel": "side_conversation", "status": "sent"}
        except Exception:  # noqa: BLE001 — add-on may be missing; fall back to a note.
            try:
                self._client.put(
                    f"{self.base}/tickets/{ticket_id}.json",
                    json={"ticket": {"comment": {"body": f"📟 PAGED {team}: {summary}",
                                                 "public": False}}},
                )
            except Exception:  # noqa: BLE001
                pass
            return {"channel": "internal_note", "status": "internal_note_fallback"}

    def poll_new_tickets(self, since_iso):
        try:
            r = self._client.get(
                f"{self.base}/search.json",
                params={"query": f"type:ticket created>{since_iso}"},
            )
            r.raise_for_status()
            return r.json().get("results", [])
        except Exception:  # noqa: BLE001
            return []


class MockZendeskClient:
    """In-memory stand-in with identical signatures. Fake IDs from 4200."""

    def __init__(self):
        self._next_id = 4200
        self.tickets: list[dict] = []

    def create_ticket(self, name, email, subject, body):
        tid = self._next_id
        self._next_id += 1
        self.tickets.append(
            {"id": tid, "requester": name, "subject": subject, "body": body,
             "tags": [], "priority": "normal", "custom_field": None, "comments": []}
        )
        return tid

    def _find(self, ticket_id):
        return next((t for t in self.tickets if t["id"] == ticket_id), None)

    def update_ticket(self, ticket_id, dispatch_path, tags, internal_note):
        t = self._find(ticket_id)
        if t:
            t["priority"] = PRIORITY_BY_PATH.get(dispatch_path, "normal")
            t["tags"] = tags
            t["custom_field"] = dispatch_path
            t["comments"].append({"public": False, "body": internal_note})
        return True

    def public_reply(self, ticket_id, body):
        t = self._find(ticket_id)
        if t:
            t["comments"].append({"public": True, "body": body})
        return True

    def search_guide(self, query):
        return CANNED_GUIDE

    def open_side_conversation(self, ticket_id, team, summary):
        t = self._find(ticket_id)
        if t:
            t["comments"].append({"public": False, "body": f"[BEACON DISPATCH] {team}: {summary}"})
        return {"channel": "side_conversation", "status": "sent"}

    def poll_new_tickets(self, since_iso):
        return []


def get_client():
    if config.USE_MOCK_ZENDESK:
        return MockZendeskClient()
    try:
        return ZendeskClient()
    except Exception as exc:  # noqa: BLE001
        print(f"[BEACON] Zendesk client init failed ({exc!r}); using mock.")
        return MockZendeskClient()
