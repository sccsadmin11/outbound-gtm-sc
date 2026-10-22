#!/usr/bin/env python3
"""Point PlusVibe's reply webhook at the relay.

POST /hook/add with event ALL_EMAIL_REPLIES, your relay URL + /plusvibe,
and PLUSVIBE_WEBHOOK_SECRET so every delivery is HMAC signed.
--dry-run prints the payload (secret masked) and writes nothing.
--list only lists existing webhooks (read-only).

Env: PLUSVIBE_API_KEY, PLUSVIBE_WORKSPACE_ID, PLUSVIBE_WEBHOOK_SECRET, RELAY_PUBLIC_URL
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from gtm_common import dry_run_print, read_json, require_env  # noqa: E402
from plusvibe import PlusVibe  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default="speed-to-lead relay")
    p.add_argument("--campaign-state", help="campaign_state.json from skill 09 (limits the hook to that campaign)")
    p.add_argument("--list", action="store_true", help="list existing webhooks and exit")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    if a.list:
        print(PlusVibe().list_webhooks())
        return 0
    env = require_env("PLUSVIBE_WEBHOOK_SECRET", "RELAY_PUBLIC_URL")
    url = env["RELAY_PUBLIC_URL"].rstrip("/") + "/plusvibe"
    camp = ["ALL"]
    if a.campaign_state:
        cid = read_json(a.campaign_state).get("campaign_id")
        camp = [cid] if cid else camp
    if a.dry_run:
        dry_run_print("add webhook", {"name": a.name, "url": url, "camp_ids": camp, "event_types": ["ALL_EMAIL_REPLIES"],
                                      "secret": "***", "ignore_ooo": False, "ignore_automatic": True})
        return 0
    res = PlusVibe().add_webhook(a.name, url, env["PLUSVIBE_WEBHOOK_SECRET"], camp)
    print(f"webhook added -> {url}: {res if not isinstance(res, dict) else {k: v for k, v in res.items() if k != 'secret'}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
