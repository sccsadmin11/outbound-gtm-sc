#!/usr/bin/env python3
"""Verify every email and keep only the ones that are safe to send.

1. MillionVerifier single API for every email.
     ok                    -> safe
     catch_all / unknown   -> step 2
     invalid / disposable  -> rejected
2. BounceBan (waterfall endpoint) for catch-all and unknown emails.
     deliverable           -> safe
     risky / undeliverable / unknown -> rejected (use --allow-risky to keep risky)

Input : leads_with_email.csv (skill 05)
Output: verified_leads.csv  (safe to send only, adds verify_* columns)
        rejected_emails.csv (with the reason)

Env: MILLIONVERIFIER_API_KEY, BOUNCEBAN_API_KEY
Docs: https://developer.millionverifier.com/  https://bounceban.com/public/doc/api.html
Verification only reads, but it does use credits. --dry-run counts and stops.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from gtm_common import ApiError, RateLimiter, dry_run_print, http, log, read_csv, require_env, write_csv  # noqa: E402

MV_URL = "https://api.millionverifier.com/api/v3/"
BB_URL = "https://api-waterfall.bounceban.com/v1/verify/single"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
mv_limit = RateLimiter(5)
bb_limit = RateLimiter(2)


def millionverifier(email: str, key: str) -> dict:
    mv_limit.wait()
    data = http("GET", MV_URL, params={"api": key, "email": email, "timeout": 10}, timeout=30)
    if data.get("error"):
        raise RuntimeError(f"MillionVerifier error: {data['error']}")
    return data


def bounceban(email: str, key: str, mode: str = "regular", tries: int = 3) -> dict:
    for attempt in range(tries):
        bb_limit.wait()
        try:
            return http("GET", BB_URL, headers={"Authorization": key},
                        params={"email": email, "mode": mode, "timeout": 80}, timeout=100, retries=1)
        except ApiError as e:
            # 408 = still verifying. Re-sending the same request within 30 min is free.
            if e.status == 408 and attempt < tries - 1:
                time.sleep(5)
                continue
            if e.status == 403:
                raise RuntimeError("BounceBan: not enough credits (403)") from e
            raise
    return {"result": "unknown"}


def classify(email: str, mv: callable, bb: callable, allow_risky: bool) -> dict:
    """Return {'safe': bool, 'mv_result', 'bb_result', 'reason'} for one email."""
    if not EMAIL_RE.match(email or ""):
        return {"safe": False, "mv_result": "", "bb_result": "", "reason": "malformed email"}
    m = mv(email)
    mres = str(m.get("result", "")).lower()
    out = {"safe": False, "mv_result": mres, "bb_result": "", "reason": ""}
    if mres == "ok":
        out.update(safe=True, reason="MillionVerifier ok")
        return out
    if mres in ("catch_all", "unknown"):
        mode = "deepverify" if mres == "catch_all" else "regular"
        b = bb(email, mode)
        bres = str(b.get("result", "")).lower()
        out["bb_result"] = bres
        if bres == "deliverable" or (allow_risky and bres == "risky"):
            out.update(safe=True, reason=f"MillionVerifier {mres} -> BounceBan {bres}")
        else:
            out["reason"] = f"MillionVerifier {mres} -> BounceBan {bres or 'no result'}"
        return out
    out["reason"] = f"MillionVerifier {mres or 'no result'}"
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--leads", default="leads_with_email.csv")
    p.add_argument("--allow-risky", action="store_true", help="also keep BounceBan 'risky' results")
    p.add_argument("--dry-run", action="store_true", help="count emails, call nothing")
    p.add_argument("--out", default="verified_leads.csv")
    p.add_argument("--rejected", default="rejected_emails.csv")
    a = p.parse_args(argv)
    rows = read_csv(a.leads)
    # drop duplicates before spending credits
    seen, uniq = set(), []
    for r in rows:
        e = (r.get("email") or "").strip().lower()
        if e and e not in seen:
            seen.add(e)
            uniq.append({**r, "email": e})
    if a.dry_run:
        dry_run_print("verification plan", {"rows": len(rows), "unique_emails": len(uniq),
                                             "millionverifier_calls": len(uniq)})
        return 0
    env = require_env("MILLIONVERIFIER_API_KEY")
    bb_key = None

    def mv(e):
        return millionverifier(e, env["MILLIONVERIFIER_API_KEY"])

    def bb(e, mode):
        nonlocal bb_key
        bb_key = bb_key or require_env("BOUNCEBAN_API_KEY")["BOUNCEBAN_API_KEY"]
        return bounceban(e, bb_key, mode)

    safe, rejected = [], []
    for r in uniq:
        try:
            c = classify(r["email"], mv, bb, a.allow_risky)
        except (ApiError, RuntimeError) as e:
            c = {"safe": False, "mv_result": "", "bb_result": "", "reason": f"error: {str(e)[:150]}"}
        row = {**r, "verify_mv": c["mv_result"], "verify_bb": c["bb_result"], "verify_reason": c["reason"]}
        (safe if c["safe"] else rejected).append(row)
        log(f"{r['email']}: {'SAFE' if c['safe'] else 'REJECT'} ({c['reason']})")
    cols = (list(uniq[0].keys()) if uniq else []) + ["verify_mv", "verify_bb", "verify_reason"]
    write_csv(a.out, safe, cols)
    write_csv(a.rejected, rejected, cols)
    print(f"{len(safe)} safe to send, {len(rejected)} rejected -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
