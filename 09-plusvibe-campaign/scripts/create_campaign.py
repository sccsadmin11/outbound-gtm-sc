#!/usr/bin/env python3
"""Create the PlusVibe campaign, load the sequence, connect inboxes, upload leads.

Settings applied:
  daily_limit           = connected ACTIVE Google inboxes x 15 (--per-inbox)
  daily_limit_new_lead  = daily_limit / 2, send_priority = 0.5  (50/50 new vs follow-up)
  send_as_txt = yes, open tracking = no, unsubscribe link = no (opt-out line is in the copy)
  stop_on_lead_replied = yes
  sequence: step 1 = Email 1 A/B/C, step 2 = Email 2 A/B
  email_accounts = every connected ACTIVE Google inbox
  leads: every CSV column is sent as a custom variable

This script never sets the campaign status to ACTIVE, so nothing sends.
Skill 11 runs QA and is the only step that can launch it.

Input : sequence.json (07), verified_leads.csv (06), spam_report.json (08),
        optional inboxes_connected.csv (01) to limit which inboxes are used
Output: campaign_state.json
Env   : PLUSVIBE_API_KEY, PLUSVIBE_WORKSPACE_ID
ALWAYS run with --dry-run first. Without it this writes to PlusVibe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from copy_utils import STANDARD_FIELDS  # noqa: E402
from gtm_common import dry_run_print, log, optional_env, read_csv, read_json, write_json  # noqa: E402
from plusvibe import PlusVibe, is_active_google  # noqa: E402

LEAD_BATCH = 100  # TODO: PlusVibe does not document a max leads per /lead/add call; 100 is a safe guess.


def pick_accounts(accounts: list[dict], only_emails: set[str] | None) -> list[dict]:
    out = [a for a in accounts if is_active_google(a)]
    if only_emails:
        out = [a for a in out if str(a.get("email", "")).lower() in only_emails]
    return out


def daily_limits(n_inboxes: int, per_inbox: int = 15) -> tuple[int, int]:
    total = n_inboxes * per_inbox
    return total, total // 2


def build_settings(account_ids: list[str], daily_limit: int, new_lead_limit: int, args) -> dict:
    schedule = {
        "daily_limit": daily_limit,
        "daily_limit_new_lead": new_lead_limit,
        "start_date": args.start_date,
        "end_date": "",
        "days": {str(d): d <= 5 for d in range(1, 8)},
        "timezone": args.timezone,
        "timing": {"from": args.send_from, "to": args.send_to},
    }
    return {
        # TODO: the schema says `schedules` is an object, the official example sends a list. We follow the example.
        "schedules": [schedule] if args.schedule_format == "list" else schedule,
        "email_accounts": account_ids,
        "send_priority": 0.5,
        "send_as_txt": "yes",
        "is_emailopened_tracking": "no",
        "is_unsubscribed_link": "no",
        "stop_on_lead_replied": "yes",
        "exclude_ooo": "yes",
        "var_sel_type": "R_ROBIN",
    }


def build_sequences(seq: dict) -> list[dict]:
    out = []
    for st in seq["steps"]:
        out.append({
            "step": st["step"],
            "wait_time": int(seq["steps"][st["step"]]["wait_time"]) if st["step"] < len(seq["steps"]) else 0,
            "variations": [{"variation": v["variation"], "subject": v.get("subject", ""), "name": "",
                            "body": v["body_html"]} for v in st["variations"]],
        })
    return out


def to_plusvibe_lead(row: dict) -> dict:
    lead = {}
    for col, field in STANDARD_FIELDS.items():
        if row.get(col):
            lead[field] = row[col]
    lead["custom_variables"] = {k: ("" if v is None else str(v)) for k, v in row.items() if k}
    return lead


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="campaign name")
    p.add_argument("--sequence", default="sequence.json")
    p.add_argument("--leads", default="verified_leads.csv")
    p.add_argument("--spam-report", default="spam_report.json")
    p.add_argument("--inboxes", help="inboxes_connected.csv from skill 01 (only these inboxes are connected)")
    p.add_argument("--per-inbox", type=int, default=15)
    p.add_argument("--timezone", default="America/New_York")
    p.add_argument("--send-from", default="09:00")
    p.add_argument("--send-to", default="17:00")
    p.add_argument("--start-date", default=dt.date.today().isoformat())
    p.add_argument("--schedule-format", choices=["list", "object"], default="list")
    p.add_argument("--campaign-id", help="update this existing campaign instead of creating one")
    p.add_argument("--dry-run", action="store_true", help="print every payload, write nothing to PlusVibe")
    p.add_argument("--out", default="campaign_state.json")
    a = p.parse_args(argv)

    spam = read_json(a.spam_report) if Path(a.spam_report).exists() else None
    if not spam or not spam.get("passed"):
        print(f"ERROR: {a.spam_report} missing or not passed. Run skill 08 first.", file=sys.stderr)
        return 2
    seq = read_json(a.sequence)
    if [len(s["variations"]) for s in seq["steps"]] != [3, 2]:
        print("ERROR: sequence must be Email 1 A/B/C + Email 2 A/B (run skill 07)", file=sys.stderr)
        return 2
    leads = read_csv(a.leads)
    only = None
    inbox_rows = []
    if a.inboxes:
        inbox_rows = read_csv(a.inboxes)
        only = {r["email"].lower() for r in inbox_rows}

    have_env = optional_env("PLUSVIBE_API_KEY") and optional_env("PLUSVIBE_WORKSPACE_ID")
    pv = PlusVibe() if (have_env or not a.dry_run) else None
    if pv:
        accounts = pv.list_accounts()  # read-only
    else:
        log("dry-run without PlusVibe keys: using the inboxes CSV as the account list")
        accounts = [{"id": r.get("plusvibe_account_id", ""), "email": r["email"], "status": r.get("status", ""),
                     "provider": r.get("provider", "")} for r in inbox_rows]
    chosen = pick_accounts(accounts, only)
    if not chosen:
        print("ERROR: no ACTIVE Google inboxes found in PlusVibe. Finish skill 01 first.", file=sys.stderr)
        return 2
    if only and len(chosen) < len(only):
        missing = sorted(only - {c["email"].lower() for c in chosen})
        log(f"WARNING: {len(missing)} inbox(es) not ACTIVE in PlusVibe and left out: {', '.join(missing)}")
    ids = [c["id"] for c in chosen]
    limit, new_limit = daily_limits(len(chosen), a.per_inbox)
    settings = build_settings(ids, limit, new_limit, a)
    settings["sequences"] = build_sequences(seq)
    pv_leads = [to_plusvibe_lead(r) for r in leads]
    batches = [pv_leads[i:i + LEAD_BATCH] for i in range(0, len(pv_leads), LEAD_BATCH)]

    state = {"name": a.name, "campaign_id": a.campaign_id, "inbox_count": len(chosen),
             "inbox_emails": [c["email"] for c in chosen], "account_ids": ids,
             "per_inbox": a.per_inbox, "daily_limit": limit, "daily_limit_new_lead": new_limit,
             "send_priority": 0.5, "send_as_txt": "yes", "is_emailopened_tracking": "no",
             "lead_count": len(pv_leads), "launched": False}
    if a.dry_run:
        dry_run_print("create campaign", {"camp_name": a.name} if not a.campaign_id else {"existing": a.campaign_id})
        dry_run_print("update campaign settings", settings)
        dry_run_print(f"upload leads ({len(batches)} batch(es))", {"first_lead": pv_leads[0] if pv_leads else None})
        write_json(a.out, {**state, "dry_run": True})
        print(f"dry run ok: {len(chosen)} inboxes -> daily limit {limit} ({new_limit} new), {len(pv_leads)} leads")
        return 0

    cid = a.campaign_id or pv.create_campaign(a.name)["id"]
    state["campaign_id"] = cid
    write_json(a.out, state)
    pv.update_campaign(cid, settings)
    log(f"campaign {cid}: settings, sequence and {len(ids)} inboxes saved")
    uploaded = 0
    for b in batches:
        res = pv.add_leads(cid, b) or {}
        uploaded += int(res.get("leads_uploaded", 0) or 0)
        log(f"leads batch: {res.get('leads_uploaded')} uploaded, {res.get('duplicate_email_count')} dupes, "
            f"{res.get('invalid_email_count')} invalid")
    state["leads_uploaded"] = uploaded
    write_json(a.out, state)
    print(f"campaign {cid} ready (not launched): {len(ids)} inboxes, daily limit {limit}, {uploaded} leads. Run skill 11.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
