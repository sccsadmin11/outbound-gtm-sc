#!/usr/bin/env python3
"""Find the right people at each qualified account with a provider waterfall.

Order (default): Clay CLI -> QuickEnrich -> BlitzAPI -> GetLeads.
For every account x persona, providers are tried in order and the
waterfall STOPS at the first provider that returns a matching person.

Input : qualified_accounts.csv (skill 03) + strategy.json (personas)
Output: people.csv, one row per person found, with `people_source`.
        Rows where nobody was found go to people_not_found.csv.

Env: QUICKENRICH_API_KEY, BLITZ_API_KEY, GETLEADS_API_KEY
     Clay uses the `clay` CLI login (run `clay login` once).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from gtm_common import ApiError, dry_run_print, log, normalize_domain, read_csv, read_json, write_csv  # noqa: E402
import providers  # noqa: E402

DEFAULT_ORDER = ["clay", "quickenrich", "blitz", "getleads"]
FIELDS = ["domain", "company_name", "company_linkedin_url", "persona", "first_name", "last_name",
          "full_name", "title", "linkedin_url", "email", "email_status", "people_source", "account_score"]


def find_for(account: dict, persona: dict, order: list[str], per_persona: int,
             provider_fns: dict | None = None, clay_template: str | None = None) -> tuple[list[dict], list[str]]:
    """Run the waterfall for one account x persona. Returns (people, log of attempts)."""
    fns = provider_fns or providers.PEOPLE_PROVIDERS
    domain = normalize_domain(account["domain"])
    titles = persona["titles"]
    exclude = persona.get("exclude_titles") or []
    tried = []
    for name in order:
        fn = fns[name]
        kwargs = {}
        if name in ("blitz", "getleads") and account.get("linkedin_url"):
            kwargs["company_linkedin_url"] = account["linkedin_url"]
        if name == "clay" and clay_template:
            kwargs["template"] = clay_template
        try:
            found = fn(domain, titles, exclude, per_persona, **kwargs)
        except (ApiError, RuntimeError, ValueError, KeyError) as e:
            tried.append(f"{name}: error {str(e)[:120]}")
            continue
        except SystemExit as e:  # missing env var for this provider: skip it
            tried.append(f"{name}: skipped ({str(e).splitlines()[0]})")
            continue
        if found:
            tried.append(f"{name}: {len(found)} found")
            return found[:per_persona], tried
        tried.append(f"{name}: none")
    return [], tried


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--accounts", default="qualified_accounts.csv")
    p.add_argument("--strategy", default="strategy.json")
    p.add_argument("--order", nargs="*", default=DEFAULT_ORDER, choices=DEFAULT_ORDER)
    p.add_argument("--per-persona", type=int, default=1, help="people to keep per account x persona")
    p.add_argument("--limit-accounts", type=int, default=0, help="only the first N accounts (0 = all)")
    p.add_argument("--clay-query-template", default=None,
                   help="Clay query with {domain} and {titles} placeholders")
    p.add_argument("--dry-run", action="store_true", help="print the plan, call no provider")
    p.add_argument("--out", default="people.csv")
    p.add_argument("--not-found", default="people_not_found.csv")
    a = p.parse_args(argv)

    accounts = read_csv(a.accounts)
    if a.limit_accounts:
        accounts = accounts[:a.limit_accounts]
    personas = read_json(a.strategy)["personas"]

    if a.dry_run:
        dry_run_print("people waterfall plan", {
            "order": a.order, "accounts": len(accounts), "personas": [x["persona"] for x in personas],
            "max_lookups": len(accounts) * len(personas), "per_persona": a.per_persona,
            "first_account": accounts[0]["domain"] if accounts else None,
        })
        return 0

    rows, misses = [], []
    for acc in accounts:
        for per in personas:
            found, tried = find_for(acc, per, a.order, a.per_persona, clay_template=a.clay_query_template)
            log(f"{acc['domain']} / {per['persona']}: " + " -> ".join(tried))
            if not found:
                misses.append({"domain": acc["domain"], "persona": per["persona"], "tried": " | ".join(tried)})
            for f in found:
                rows.append({
                    "domain": normalize_domain(acc["domain"]), "company_name": acc.get("company_name", ""),
                    "company_linkedin_url": acc.get("linkedin_url", ""), "persona": per["persona"],
                    **{k: f[k] for k in ("first_name", "last_name", "full_name", "title", "linkedin_url",
                                          "email", "email_status")},
                    "people_source": f["source"], "account_score": acc.get("score", ""),
                })
    # de-dupe the same person found for two personas
    seen, unique = set(), []
    for r in rows:
        key = (r["linkedin_url"] or f"{r['full_name']}|{r['domain']}").lower()
        if key not in seen:
            seen.add(key)
            unique.append(r)
    write_csv(a.out, unique, FIELDS)
    write_csv(a.not_found, misses, ["domain", "persona", "tried"])
    print(f"{len(unique)} people found, {len(misses)} account/persona misses -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
