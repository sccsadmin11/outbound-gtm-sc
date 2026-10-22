#!/usr/bin/env python3
"""Zapmail step: connect domains, create Google Workspace inboxes, export.

Subcommands
  plan              Build inbox_plan.csv from domains + sender names (local only).
  connect-domains   Connect domains to Zapmail and poll until done (writes).
  create-mailboxes  Create the planned Google Workspace mailboxes (writes,
                    uses mailbox slots on your Zapmail plan).
  list              Export mailboxes to inboxes.csv (passwords are NEVER written).
  export-plusvibe   Ask Zapmail to push the mailboxes into PlusVibe (writes).

Every writing subcommand supports --dry-run. Run it first.

Docs: https://docs.zapmail.ai/llms.txt
Env:  ZAPMAIL_API_KEY (Zapmail app -> Settings -> API), optional ZAPMAIL_WORKSPACE_KEY

DNS: once your registrar points the domain at Zapmail's nameservers
(see porkbun_domains.py set-ns), Zapmail creates the MX, SPF, DKIM and
DMARC records itself as part of connect-domain.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from gtm_common import (  # noqa: E402
    RateLimiter, dry_run_print, http, log, normalize_domain, optional_env,
    read_csv, require_env, write_csv,
)

BASE = "https://api.zapmail.ai/api"
MAX_PER_DOMAIN = 5        # Zapmail allows at most 5 mailboxes per domain
CONNECT_BATCH = 50
TERMINAL_OK = {"SUCCESS", "DOMAIN_ALREADY_CONNECTED"}
TERMINAL_FAIL = {
    "DOMAIN_NOT_REGISTERED", "WORKSPACE_ALREADY_EXISTS", "BLACKLISTED_DOMAIN", "BANNED_DOMAIN",
}
limiter = RateLimiter(4)  # documented limit is 5 rps


def headers() -> dict:
    env = require_env("ZAPMAIL_API_KEY")
    h = {"x-auth-zapmail": env["ZAPMAIL_API_KEY"], "x-service-provider": "GOOGLE"}
    ws = optional_env("ZAPMAIL_WORKSPACE_KEY")
    if ws:
        h["x-workspace-key"] = ws
    return h


def zm(method: str, path: str, **kw):
    limiter.wait()
    return http(method, BASE + path, headers=headers(), **kw)


# ---------------------------------------------------------------- plan
def username_for(first: str, last: str, style: str) -> str:
    f = re.sub(r"[^a-z]", "", first.lower())
    l = re.sub(r"[^a-z]", "", last.lower())
    return {
        "first": f,
        "first.last": f"{f}.{l}",
        "firstlast": f"{f}{l}",
        "f.last": f"{f[:1]}.{l}",
        "firstl": f"{f}{l[:1]}",
    }[style]


def build_plan(domains: list[str], senders: list[dict], per_domain: int, styles: list[str]) -> list[dict]:
    """Spread inboxes over domains. Each domain gets `per_domain` inboxes,
    cycling through senders and username styles so no address repeats."""
    if not 1 <= per_domain <= MAX_PER_DOMAIN:
        raise ValueError(f"--per-domain must be 1..{MAX_PER_DOMAIN}")
    rows = []
    for d in domains:
        used = set()
        i = 0
        while len([r for r in rows if r["domain"] == d]) < per_domain:
            if i > per_domain * len(styles) * max(1, len(senders)):
                raise ValueError(f"Not enough unique sender/style combos for {d}")
            s = senders[i % len(senders)]
            style = styles[(i // len(senders)) % len(styles)]
            u = username_for(s["first_name"], s["last_name"], style)
            i += 1
            if u in used:
                continue
            used.add(u)
            rows.append({
                "domain": d, "first_name": s["first_name"], "last_name": s["last_name"],
                "username": u, "email": f"{u}@{d}",
            })
    return rows


# ---------------------------------------------------------------- connect
def connect_domains(domains: list[str], dry_run: bool, poll_seconds: int, timeout: int) -> list[dict]:
    results = {}
    for i in range(0, len(domains), CONNECT_BATCH):
        batch = domains[i:i + CONNECT_BATCH]
        body = {"domainNames": batch}
        if dry_run:
            dry_run_print(f"POST {BASE}/v2/domains/connect-domain", body)
            results.update({d: "dry-run" for d in batch})
            continue
        deadline = time.time() + timeout
        while True:
            data = zm("POST", "/v2/domains/connect-domain", json_body=body)
            states = {normalize_domain(k): (v or {}).get("status", "")
                      for k, v in ((data.get("data") or {}).get("domains") or {}).items()}
            results.update(states)
            open_ = [d for d in batch if results.get(d) not in TERMINAL_OK | TERMINAL_FAIL]
            if not open_ or time.time() > deadline:
                break
            log(f"waiting on {len(open_)} domains ({', '.join(sorted(set(results[d] for d in open_)))})")
            time.sleep(poll_seconds)
    return [{"domain": d, "status": results.get(d, "unknown")} for d in domains]


# ---------------------------------------------------------------- create
def assignable_domain_ids() -> dict[str, str]:
    ids, page = {}, 1
    while True:
        data = zm("GET", "/v2/domains/assignable", params={"page": page, "limit": 100})
        block = data.get("data") or {}
        for d in block.get("domains") or []:
            ids[normalize_domain(d.get("domain", ""))] = d.get("id")
        if not block.get("nextPage") or page >= int(block.get("totalPages") or page):
            return ids
        page += 1


def create_mailboxes(plan: list[dict], dry_run: bool, domain_ids: dict[str, str] | None = None) -> dict:
    if domain_ids is None:
        domain_ids = {} if dry_run else assignable_domain_ids()
    body: dict[str, list] = {}
    missing = []
    for r in plan:
        did = domain_ids.get(r["domain"]) or (f"<domainId of {r['domain']}>" if dry_run else None)
        if not did:
            missing.append(r["domain"])
            continue
        body.setdefault(did, []).append({
            "firstName": r["first_name"], "lastName": r["last_name"],
            "mailboxUsername": r["username"], "domainName": r["domain"],
        })
    for did, boxes in body.items():
        if len(boxes) > MAX_PER_DOMAIN:
            raise ValueError(f"{boxes[0]['domainName']} has {len(boxes)} mailboxes, max is {MAX_PER_DOMAIN}")
    if missing:
        log("Not assignable yet (connect them first): " + ", ".join(sorted(set(missing))))
    if dry_run:
        dry_run_print(f"POST {BASE}/v2/mailboxes?serviceProvider=GOOGLE", body)
        return {"dry_run": True, "domains": len(body)}
    if not body:
        return {"created": 0}
    return zm("POST", "/v2/mailboxes", params={"serviceProvider": "GOOGLE"}, json_body=body)


# ---------------------------------------------------------------- list
SAFE_FIELDS = ["email", "first_name", "last_name", "domain", "status", "zapmail_mailbox_id"]


def list_mailboxes(contains: str = "") -> list[dict]:
    rows, page = [], 1
    while True:
        params = {"page": page, "limit": 100}
        if contains:
            params["contains"] = contains
        data = zm("GET", "/v2/mailboxes/list", params=params)
        block = data.get("data") or {}
        for dom in block.get("domains") or []:
            for m in dom.get("mailboxes") or []:
                # Only copy non-secret fields. The API also returns passwords,
                # app passwords and 2FA secrets: we never store those.
                rows.append({
                    "email": m.get("email", ""), "first_name": m.get("firstName", ""),
                    "last_name": m.get("lastName", ""), "domain": m.get("domain") or dom.get("domain", ""),
                    "status": m.get("status", ""), "zapmail_mailbox_id": m.get("id", ""),
                })
        if not block.get("nextPage") or page >= int(block.get("totalPages") or page):
            return rows
        page += 1


# ---------------------------------------------------------------- export
def export(ids: list[str], app: str, dry_run: bool, third_party_account_id: str = "") -> dict:
    body = {
        "apps": [app], "ids": ids, "excludeIds": [], "tagIds": [],
        "status": "ACTIVE", "contains": "",
    }
    if third_party_account_id:
        body["thirdPartyAccountId"] = third_party_account_id
    if dry_run:
        dry_run_print(f"POST {BASE}/v2/exports/mailboxes", body)
        return {"dry_run": True}
    return zm("POST", "/v2/exports/mailboxes", json_body=body)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("plan", help="build inbox_plan.csv (local)")
    s.add_argument("--domains-csv", help="domain_check.csv (rows with available=yes or a domain column)")
    s.add_argument("--domains", nargs="*")
    s.add_argument("--senders", required=True, help="CSV with first_name,last_name")
    s.add_argument("--per-domain", type=int, default=3, help="inboxes per domain (1-5, default 3)")
    s.add_argument("--styles", nargs="*", default=["first", "first.last", "firstl"],
                   help="username styles: first first.last firstlast f.last firstl")
    s.add_argument("--out", default="inbox_plan.csv")

    s = sub.add_parser("connect-domains")
    s.add_argument("--domains", nargs="*")
    s.add_argument("--plan", help="inbox_plan.csv (uses its domain column)")
    s.add_argument("--poll-seconds", type=int, default=30)
    s.add_argument("--timeout", type=int, default=1800)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--out", default="domain_connect.csv")

    s = sub.add_parser("create-mailboxes")
    s.add_argument("--plan", required=True)
    s.add_argument("--dry-run", action="store_true")

    s = sub.add_parser("list")
    s.add_argument("--contains", default="")
    s.add_argument("--out", default="inboxes.csv")

    s = sub.add_parser("export-plusvibe")
    s.add_argument("--inboxes", required=True, help="inboxes.csv from `list`")
    s.add_argument("--app", default="PLUSVIBE",
                   help="Zapmail export app. TODO: PLUSVIBE is not in the documented enum; "
                        "use MANUAL for a CSV export if Zapmail rejects it")
    s.add_argument("--third-party-account-id", default="")
    s.add_argument("--dry-run", action="store_true")

    a = p.parse_args(argv)

    if a.cmd == "plan":
        domains = [normalize_domain(d) for d in (a.domains or [])]
        if a.domains_csv:
            for r in read_csv(a.domains_csv):
                if r.get("available", "yes") in ("yes", "owned", ""):
                    domains.append(normalize_domain(r["domain"]))
        domains = list(dict.fromkeys(d for d in domains if d))
        if not domains:
            sys.exit("No domains. Use --domains or --domains-csv")
        plan = build_plan(domains, read_csv(a.senders), a.per_domain, a.styles)
        write_csv(a.out, plan)
        print(f"{len(plan)} inboxes over {len(domains)} domains -> {a.out}")
    elif a.cmd == "connect-domains":
        domains = [normalize_domain(d) for d in (a.domains or [])]
        if a.plan:
            domains += [r["domain"] for r in read_csv(a.plan)]
        domains = list(dict.fromkeys(domains))
        rows = connect_domains(domains, a.dry_run, a.poll_seconds, a.timeout)
        write_csv(a.out, rows)
        print(f"{sum(r['status'] in TERMINAL_OK for r in rows)}/{len(rows)} connected -> {a.out}")
    elif a.cmd == "create-mailboxes":
        res = create_mailboxes(read_csv(a.plan), a.dry_run)
        print(res if a.dry_run else res.get("message", res))
    elif a.cmd == "list":
        rows = list_mailboxes(a.contains)
        write_csv(a.out, rows, SAFE_FIELDS)
        print(f"{len(rows)} mailboxes -> {a.out}")
    elif a.cmd == "export-plusvibe":
        ids = [r["zapmail_mailbox_id"] for r in read_csv(a.inboxes) if r.get("zapmail_mailbox_id")]
        res = export(ids, a.app, a.dry_run, a.third_party_account_id)
        print(res if a.dry_run else res.get("message", res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
