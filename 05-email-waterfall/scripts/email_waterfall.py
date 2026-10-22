#!/usr/bin/env python3
"""Find a work email for every person with a provider waterfall.

Order (default): QuickEnrich -> BlitzAPI -> GetLeads -> Prospeo.
Providers run in order and STOP at the first email found. Rows that
already have an email from skill 04 are kept as-is (unless
--ignore-existing).

Input : people.csv (skill 04)
Output: leads_with_email.csv (adds email, email_source, email_status)
        emails_not_found.csv

Env: QUICKENRICH_API_KEY, BLITZ_API_KEY, GETLEADS_API_KEY, PROSPEO_API_KEY
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from gtm_common import ApiError, dry_run_print, log, normalize_domain, read_csv, write_csv  # noqa: E402
import providers  # noqa: E402

DEFAULT_ORDER = ["quickenrich", "blitz", "getleads", "prospeo"]


def find_email(row: dict, order: list[str], fns: dict | None = None) -> tuple[dict | None, list[str]]:
    fns = fns or providers.EMAIL_PROVIDERS
    domain = normalize_domain(row.get("domain", ""))
    tried = []
    for name in order:
        try:
            if name == "prospeo":
                hit = fns[name](row, domain, row.get("company_name", ""))
            else:
                hit = fns[name](row, domain)
        except (ApiError, RuntimeError, ValueError, KeyError) as e:
            tried.append(f"{name}: error {str(e)[:120]}")
            continue
        except SystemExit as e:
            tried.append(f"{name}: skipped ({str(e).splitlines()[0]})")
            continue
        if hit and "@" in hit.get("email", ""):
            tried.append(f"{name}: found")
            return hit, tried
        tried.append(f"{name}: none")
    return None, tried


def run(rows: list[dict], order: list[str], ignore_existing: bool, fns: dict | None = None):
    found, missing = [], []
    for r in rows:
        r = dict(r)
        if r.get("email") and not ignore_existing:
            r["email_source"] = r.get("people_source", "") + " (from people step)"
            found.append(r)
            continue
        hit, tried = find_email(r, order, fns)
        log(f"{r.get('full_name')} @ {r.get('domain')}: " + " -> ".join(tried))
        if hit:
            r.update(email=hit["email"], email_status=hit.get("email_status", ""), email_source=hit["source"])
            found.append(r)
        else:
            missing.append({**r, "tried": " | ".join(tried)})
    # one row per email address
    seen, unique = set(), []
    for r in found:
        if r["email"].lower() not in seen:
            seen.add(r["email"].lower())
            unique.append(r)
    return unique, missing


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--people", default="people.csv")
    p.add_argument("--order", nargs="*", default=DEFAULT_ORDER, choices=DEFAULT_ORDER)
    p.add_argument("--ignore-existing", action="store_true", help="re-look up rows that already have an email")
    p.add_argument("--dry-run", action="store_true", help="print the plan, call no provider")
    p.add_argument("--out", default="leads_with_email.csv")
    p.add_argument("--not-found", default="emails_not_found.csv")
    a = p.parse_args(argv)
    rows = read_csv(a.people)
    if a.dry_run:
        need = [r for r in rows if a.ignore_existing or not r.get("email")]
        dry_run_print("email waterfall plan", {"order": a.order, "people": len(rows), "need_lookup": len(need)})
        return 0
    found, missing = run(rows, a.order, a.ignore_existing)
    cols = list(rows[0].keys()) if rows else []
    for c in ("email", "email_status", "email_source"):
        if c not in cols:
            cols.append(c)
    write_csv(a.out, found, cols)
    write_csv(a.not_found, missing, cols + ["tried"])
    print(f"{len(found)} emails found, {len(missing)} not found -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
