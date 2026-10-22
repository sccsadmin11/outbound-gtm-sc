#!/usr/bin/env python3
"""Confirm the Zapmail inboxes landed in PlusVibe (read only).

Pulls every email account from PlusVibe, matches it against inboxes.csv
from zapmail_inboxes.py and writes inboxes_connected.csv. Exits 1 if any
planned inbox is missing or not active, so you can re-run the export.

Env: PLUSVIBE_API_KEY, PLUSVIBE_WORKSPACE_ID
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from gtm_common import read_csv, write_csv  # noqa: E402
from plusvibe import PlusVibe  # noqa: E402

FIELDS = ["email", "in_plusvibe", "plusvibe_account_id", "status", "warmup_status", "provider"]


def is_active(acc: dict) -> bool:
    # Documented example values: status "ACTIVE", provider "GOOGLE_WORKSPACE".
    return str(acc.get("status", "")).upper() == "ACTIVE"


def match(planned: list[dict], accounts: list[dict]) -> list[dict]:
    by_email = {str(a.get("email", "")).lower(): a for a in accounts}
    rows = []
    for p in planned:
        e = p["email"].lower()
        a = by_email.get(e)
        rows.append({
            "email": e,
            "in_plusvibe": "yes" if a else "no",
            "plusvibe_account_id": (a or {}).get("id", ""),
            "status": (a or {}).get("status", ""),
            "warmup_status": (a or {}).get("warmup_status", ""),
            "provider": (a or {}).get("provider", ""),
        })
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--inboxes", required=True, help="inboxes.csv from zapmail_inboxes.py list")
    p.add_argument("--out", default="inboxes_connected.csv")
    a = p.parse_args(argv)
    planned = read_csv(a.inboxes)
    rows = match(planned, PlusVibe().list_accounts())
    write_csv(a.out, rows, FIELDS)
    missing = [r for r in rows if r["in_plusvibe"] != "yes" or not is_active({"status": r["status"]})]
    print(f"{len(rows) - len(missing)}/{len(rows)} inboxes connected and active -> {a.out}")
    if missing:
        print("Not connected yet: " + ", ".join(r["email"] for r in missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
