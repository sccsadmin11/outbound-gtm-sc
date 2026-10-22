"""Minimal PlusVibe API client shared by skills 01, 09, 10 and 11.

Docs: https://developer.plusvibe.ai/
Auth: header `x-api-key`. Every call needs `workspace_id`.
Env:  PLUSVIBE_API_KEY, PLUSVIBE_WORKSPACE_ID
Rate limit: 5 requests per second.
"""
from __future__ import annotations

from typing import Any

from gtm_common import RateLimiter, http, require_env

BASE = "https://api.plusvibe.ai/api/v1"
_limiter = RateLimiter(4)


class PlusVibe:
    def __init__(self, api_key: str | None = None, workspace_id: str | None = None):
        if api_key is None or workspace_id is None:
            env = require_env("PLUSVIBE_API_KEY", "PLUSVIBE_WORKSPACE_ID")
            api_key = api_key or env["PLUSVIBE_API_KEY"]
            workspace_id = workspace_id or env["PLUSVIBE_WORKSPACE_ID"]
        self.key = api_key
        self.ws = workspace_id

    def _call(self, method: str, path: str, params: dict | None = None, body: Any = None) -> Any:
        _limiter.wait()
        params = dict(params or {})
        if method == "GET" or path.startswith("/unibox/"):
            params.setdefault("workspace_id", self.ws)
        if body is not None and isinstance(body, dict):
            body = {"workspace_id": self.ws, **body}
        return http(method, BASE + path, headers={"x-api-key": self.key},
                    params=params or None, json_body=body)

    # accounts -----------------------------------------------------------
    def list_accounts(self) -> list[dict]:
        out, skip = [], 0
        while True:
            data = self._call("GET", "/account/list", {"skip": skip, "limit": 100})
            batch = (data or {}).get("accounts") or []
            out += batch
            if len(batch) < 100:
                return out
            skip += 100

    # campaigns ----------------------------------------------------------
    def create_campaign(self, name: str) -> dict:
        return self._call("POST", "/campaign/add/campaign", body={"camp_name": name})

    def update_campaign(self, campaign_id: str, fields: dict) -> dict:
        return self._call("PATCH", "/campaign/update/campaign", body={"campaign_id": campaign_id, **fields})

    def get_campaign(self, campaign_id: str) -> dict:
        data = self._call("GET", "/campaign/list-all", {"campaign_id": campaign_id})
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    def add_leads(self, campaign_id: str, leads: list[dict]) -> dict:
        return self._call("POST", "/lead/add", body={
            "campaign_id": campaign_id,
            "skip_if_in_workspace": False,
            "skip_lead_in_active_pause_camp": True,
            "is_overwrite": False,
            "leads": leads,
        })

    def launch_campaign(self, campaign_id: str) -> dict:
        """POST /campaign/launch. This STARTS SENDING. Only skill 11 calls it, after QA passes."""
        return self._call("POST", "/campaign/launch", body={"campaign_id": campaign_id})

    # webhooks + unibox -------------------------------------------------
    def add_webhook(self, name: str, url: str, secret: str, camp_ids: list[str] | None = None) -> dict:
        return self._call("POST", "/hook/add", body={
            "name": name, "url": url, "secret": secret,
            "camp_ids": camp_ids or ["ALL"],
            "event_types": ["ALL_EMAIL_REPLIES"],
            "ignore_ooo": False, "ignore_automatic": True,
        })

    def list_webhooks(self) -> Any:
        return self._call("GET", "/hook/list")

    def save_draft(self, parent_message_id: str, from_email: str, to: list[str], subject: str, body_html: str) -> dict:
        """Save a reply as a DRAFT. This never sends.

        We deliberately do not wrap /unibox/emails/reply because it sends.
        """
        return self._call("POST", "/unibox/emails/save-as-draft", body={
            "parent_message_id": parent_message_id,
            "from": from_email, "to": to, "subject": subject, "body": body_html,
        })

    def campaign_accounts(self, campaign_id: str) -> list:
        """Email addresses connected to a campaign (GET /campaign/get/accounts)."""
        data = self._call("GET", "/campaign/get/accounts", {"campaign_id": campaign_id})
        return data if isinstance(data, list) else (data or {}).get("accounts", []) or []


GOOGLE_PROVIDERS = {"GOOGLE_WORKSPACE", "GOOGLE", "GMAIL"}


def is_active_google(acc: dict) -> bool:
    return (str(acc.get("provider", "")).upper() in GOOGLE_PROVIDERS
            and str(acc.get("status", "")).upper() == "ACTIVE")
