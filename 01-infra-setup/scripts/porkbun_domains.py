#!/usr/bin/env python3
"""Porkbun domain step: check availability + price, set nameservers, and
(only with --confirm-purchase) register.

Subcommands
  check   Bulk availability + price check. Read only. Never buys.
  buy     Purchase. Without --confirm-purchase it only runs Porkbun's
          `dryRun: true` rehearsal (no order, no charge).
          WITH --confirm-purchase it SPENDS MONEY from your Porkbun credit.
  set-ns  Point domains at Zapmail's nameservers (writes, supports --dry-run).

Docs: https://porkbun.com/api/json/v3/documentation
Spec: https://porkbun.com/api/json/v3/spec

Env: PORKBUN_API_KEY, PORKBUN_SECRET_API_KEY (https://porkbun.com/account/api)
`check --mock` uses Porkbun's public mock server and needs no keys.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from gtm_common import (  # noqa: E402
    dry_run_print, http, log, normalize_domain, require_env, write_csv,
)

BASE = "https://api.porkbun.com/api/json/v3"
ZAPMAIL_NAMESERVERS = [
    "pns61.cloudns.net",
    "pns62.cloudns.com",
    "pns63.cloudns.net",
    "pns64.cloudns.uk",
]
BULK_MAX = 25  # documented max domains per bulk checkDomain call
CHECK_FIELDS = [
    "domain", "available", "price_usd", "regular_price_usd", "renewal_price_usd",
    "first_year_promo", "premium", "min_duration_years", "note",
]


def auth_body() -> dict:
    env = require_env("PORKBUN_API_KEY", "PORKBUN_SECRET_API_KEY")
    return {"apikey": env["PORKBUN_API_KEY"], "secretapikey": env["PORKBUN_SECRET_API_KEY"]}


def read_domains(args) -> list[str]:
    items: list[str] = list(args.domains or [])
    if args.file:
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                items.append(line)
    out, seen = [], set()
    for d in items:
        d = normalize_domain(d)
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    if not out:
        sys.exit("No domains given. Use --domains a.com b.com or --file domains.txt")
    return out


def parse_check(domain: str, r: dict) -> dict:
    """Map one checkDomain `response` object to a flat CSV row."""
    renewal = ((r.get("additional") or {}).get("renewal") or {}).get("price", "")
    return {
        "domain": domain,
        "available": "yes" if str(r.get("avail", "")).lower() == "yes" else "no",
        "price_usd": r.get("price", ""),
        "regular_price_usd": r.get("regularPrice", ""),
        "renewal_price_usd": renewal,
        "first_year_promo": r.get("firstYearPromo", ""),
        "premium": r.get("premium", ""),
        "min_duration_years": r.get("minDuration", ""),
        "note": "",
    }


def check(domains: list[str], mock: bool = False, pause: float = 1.0) -> list[dict]:
    """Bulk check. Unresolved names are retried once, invalid ones reported."""
    if mock:
        # The public mock server returns schema placeholders for the bulk call,
        # so mock mode uses the single-domain endpoint, which returns a sample.
        out = []
        for d in domains:
            data = http("POST", f"{BASE}/mock/domain/checkDomain/{d}")
            out.append(parse_check(d, data.get("response") or {}))
        return out
    url = f"{BASE}/domain/checkDomain"
    body_auth = auth_body()
    rows: dict[str, dict] = {}
    pending = list(domains)
    for attempt in range(2):
        retry: list[str] = []
        for i in range(0, len(pending), BULK_MAX):
            batch = pending[i:i + BULK_MAX]
            data = http("POST", url, json_body={**body_auth, "domains": batch})
            for name, resp in (data.get("domains") or {}).items():
                rows[normalize_domain(name)] = parse_check(normalize_domain(name), resp or {})
            for item in data.get("invalid") or []:
                # TODO: spec types `invalid` items loosely; accept a string or {"domain": ...}
                name = item.get("domain", "") if isinstance(item, dict) else str(item)
                if name:
                    rows[normalize_domain(name)] = {"domain": normalize_domain(name), "available": "no", "note": "invalid domain name"}
            retry += [normalize_domain(n) for n in data.get("unresolved") or [] if isinstance(n, str)]
            time.sleep(pause)
        if not retry:
            break
        pending = retry
        time.sleep(10)
    for d in domains:
        rows.setdefault(d, {"domain": d, "available": "unknown", "note": "unresolved, re-run later"})
    return [rows[d] for d in domains]


def cost_cents(row: dict) -> int:
    """Total cost in pennies for the minimum registration duration.

    TODO: the spec says `cost` must equal 'the total price at the minimum
    duration'. We assume `price` is per year and multiply by minDuration.
    The dryRun preview below reports Porkbun's own `cost`, and we refuse to
    buy if the two do not match, so a wrong assumption fails safe.
    """
    years = int(row.get("min_duration_years") or 1)
    return round(float(row["price_usd"]) * 100) * max(1, years)


def buy(domains: list[str], confirm: bool, max_cost_cents: int) -> list[dict]:
    auth = auth_body()
    results = []
    for row in check(domains):
        d = row["domain"]
        if row.get("available") != "yes":
            results.append({"domain": d, "result": "skipped: not available"})
            continue
        if str(row.get("premium")).lower() in ("yes", "true", "1"):
            results.append({"domain": d, "result": "skipped: premium (not allowed via API)"})
            continue
        cents = cost_cents(row)
        if cents > max_cost_cents:
            results.append({"domain": d, "result": f"skipped: cost {cents}c over --max-cost-cents {max_cost_cents}"})
            continue
        body = {**auth, "cost": cents, "agreeToTerms": "yes"}
        preview = http("POST", f"{BASE}/domain/create/{d}", json_body={**body, "dryRun": True})
        if not preview.get("dryRun") or not preview.get("wouldSucceed"):
            results.append({"domain": d, "result": f"dry-run says no: {preview.get('message', '')}"})
            continue
        if int(preview.get("cost", -1)) != cents:
            results.append({"domain": d, "result": f"refused: preview cost {preview.get('cost')} != computed {cents}"})
            continue
        if not confirm:
            results.append({"domain": d, "result": f"dry-run OK, would cost {preview.get('costDisplay', cents)}. Not purchased (no --confirm-purchase)."})
            continue
        log(f"PURCHASING {d} for {preview.get('costDisplay', cents)} (this spends money)")
        done = http("POST", f"{BASE}/domain/create/{d}", json_body=body)
        results.append({"domain": d, "result": f"purchased: {done.get('status')}", "order_id": done.get("orderId", "")})
        time.sleep(1)
    return results


def set_ns(domains: list[str], nameservers: list[str], dry_run: bool) -> list[dict]:
    out = []
    for d in domains:
        if dry_run:
            dry_run_print(f"POST {BASE}/domain/updateNs/{d}", {"ns": nameservers})
            out.append({"domain": d, "result": "dry-run"})
            continue
        res = http("POST", f"{BASE}/domain/updateNs/{d}", json_body={**auth_body(), "ns": nameservers})
        out.append({"domain": d, "result": res.get("status", "")})
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "buy", "set-ns"):
        s = sub.add_parser(name)
        s.add_argument("--domains", nargs="*", help="domain names")
        s.add_argument("--file", help="text file, one domain per line")
        s.add_argument("--out", default=f"{name.replace('-', '_')}_results.csv")
        if name == "check":
            s.add_argument("--mock", action="store_true", help="use Porkbun's public mock server (no keys, fake data)")
            s.set_defaults(out="domain_check.csv")
        if name == "buy":
            s.add_argument("--confirm-purchase", action="store_true",
                           help="ACTUALLY BUY. Costs real money from your Porkbun credit. Off by default.")
            s.add_argument("--max-cost-cents", type=int, default=1500, help="refuse any domain above this (default 1500 = $15)")
        if name == "set-ns":
            s.add_argument("--ns", nargs="*", default=ZAPMAIL_NAMESERVERS, help="nameservers (default: Zapmail)")
            s.add_argument("--dry-run", action="store_true", help="print the calls, change nothing")
    a = p.parse_args(argv)
    domains = read_domains(a)
    if a.cmd == "check":
        rows = check(domains, mock=a.mock)
        write_csv(a.out, rows, CHECK_FIELDS)
        avail = sum(1 for r in rows if r.get("available") == "yes")
        print(f"Checked {len(rows)} domains, {avail} available -> {a.out}")
    elif a.cmd == "buy":
        rows = buy(domains, a.confirm_purchase, a.max_cost_cents)
        write_csv(a.out, rows)
        for r in rows:
            print(f"{r['domain']}: {r['result']}")
    else:
        rows = set_ns(domains, a.ns, a.dry_run)
        write_csv(a.out, rows)
        print(f"Nameserver update: {len(rows)} domains -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
