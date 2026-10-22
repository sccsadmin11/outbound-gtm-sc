#!/usr/bin/env python3
"""Build, qualify and score an account list with DiscoLike only.

1. GET  /discover        ICP text + filters from strategy.json -> candidate accounts
2. POST /validate/icp    DiscoLike's native ICP check (Fit yes/no + reasoning)
   GET  /discogen/status/{task_id}  poll until done
3. Score 0-100 = 55% similarity + 35% ICP confidence + 10% digital footprint
   (footprint capped at 400). With --skip-validate: 85% similarity + 15% footprint.
   qualified = ICP fit is yes AND score >= --min-score.

Docs: https://docs.discolike.com
Env:  DISCOLIKE_API_KEY (DiscoLike app -> Account -> API keys)
Use --count-only first to see how many accounts match (cheap), and
--dry-run to print the query without calling the API.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from gtm_common import (  # noqa: E402
    ApiError, dry_run_print, http, log, normalize_domain, read_json, require_env, write_csv,
)

BASE = "https://api.discolike.com/v1"
VALIDATE_BATCH = 100  # TODO: max domains per /validate/icp call is not documented; 100 is a safe guess
FIELDS = ["domain", "company_name", "qualified", "score", "reason", "similarity", "icp_fit",
          "icp_confidence", "footprint", "employees", "industry", "linkedin_url", "description"]


def headers() -> dict:
    key = require_env("DISCOLIKE_API_KEY")["DISCOLIKE_API_KEY"]
    # DiscoLike docs use `x-discolike-key`; their OpenAPI file names the scheme `X-API-Key`.
    # Header names are case-insensitive, so we send the documented one plus the spec one.
    return {"x-discolike-key": key, "X-API-Key": key}


def discover_params(strategy: dict, max_records: int, min_similarity: int | None) -> dict:
    icp = strategy["icp"]
    params: dict = {
        "icp_text": icp["icp_text"],
        "max_records": max_records,
        "exclude_leadgen": "true",
    }
    if icp.get("negate_icp_text"):
        params["negate_icp_text"] = icp["negate_icp_text"]
    if icp.get("countries"):
        params["country"] = list(icp["countries"])
    if icp.get("employee_range") and icp["employee_range"] != "min,max":
        params["employee_range"] = icp["employee_range"]
    if icp.get("lookalike_domains"):
        params["domain"] = [normalize_domain(d) for d in icp["lookalike_domains"]][:10]
    excl = [normalize_domain(d) for d in icp.get("exclude") or []]
    if strategy.get("company", {}).get("url"):
        excl.append(normalize_domain(strategy["company"]["url"]))
    if excl:
        params["exclude_domain"] = sorted(set(excl))[:100]
    if min_similarity is not None:
        params["min_similarity"] = min_similarity
    return params


def discover(params: dict) -> list[dict]:
    return http("GET", f"{BASE}/discover", headers=headers(), params=params, timeout=120) or []


def count(params: dict) -> int:
    p = {k: v for k, v in params.items() if k not in ("max_records", "min_similarity", "icp_text",
                                                        "negate_icp_text", "domain")}
    return int((http("GET", f"{BASE}/count", headers=headers(), params=p) or {}).get("count", 0))


def _pick(d: dict, *names: str):
    """Case-insensitive lookup of the first matching key (DiscoLike column
    names depend on the task, e.g. 'ICP Fit', 'Fit', 'ICP Score')."""
    low = {str(k).lower(): v for k, v in d.items()}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    for k, v in low.items():
        if any(n.lower() in k for n in names):
            return v
    return None


def parse_validation(status: dict) -> dict[str, dict]:
    """Normalize a finished /discogen/status payload to {domain: {fit, confidence, reason}}.

    TODO: the status response schema is not published. We accept
    `results` as {domain: {...}} or as a list of {domain, ...} rows.
    """
    res = status.get("results") or status.get("data") or {}
    rows = res.items() if isinstance(res, dict) else ((r.get("domain"), r) for r in res)
    out = {}
    for domain, r in rows:
        if not domain or not isinstance(r, dict):
            continue
        fit = _pick(r, "fit", "icp fit", "icp_fit", "qualified")
        conf = _pick(r, "confidence", "icp score", "score")
        reason = _pick(r, "reasoning", "reason", "explanation") or ""
        out[normalize_domain(domain)] = {
            "fit": "yes" if str(fit).strip().lower() in ("yes", "true", "1", "fit") else "no",
            "confidence": to_pct(conf),
            "reason": str(reason).strip(),
        }
    return out


def to_pct(v) -> float:
    """Map a confidence that may be 0-1, 1-10, 0-100 or High/Medium/Low to 0-100."""
    if v is None:
        return 0.0
    if isinstance(v, str):
        m = {"high": 90, "medium": 60, "med": 60, "low": 30}
        if v.strip().lower() in m:
            return float(m[v.strip().lower()])
        try:
            v = float(v.strip().rstrip("%"))
        except ValueError:
            return 0.0
    v = float(v)
    if v <= 1:
        return v * 100
    if v <= 10:
        return v * 10
    return min(v, 100.0)


def validate(icp_text: str, domains: list[str], poll: int = 10, timeout: int = 1800) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(domains), VALIDATE_BATCH):
        batch = domains[i:i + VALIDATE_BATCH]
        body = {"icp_text": icp_text, "domains": batch, "context_mode": "website",
                "integration_id": "native-icp", "web_search": False}
        while True:
            try:
                task = http("POST", f"{BASE}/validate/icp", headers=headers(), json_body=body)
                break
            except ApiError as e:
                if e.status == 429:  # max 3 concurrent tasks
                    time.sleep(60)
                    continue
                raise
        tid = task["task_id"]
        deadline = time.time() + timeout
        while True:
            st = http("GET", f"{BASE}/discogen/status/{tid}", headers=headers())
            s = str(st.get("status", "")).lower()
            if s in ("completed", "complete", "done", "success"):
                out.update(parse_validation(st))
                break
            if s in ("failed", "error", "cancelled") or time.time() > deadline:
                log(f"validation task {tid} ended with status {s or 'timeout'}")
                break
            time.sleep(poll)
    return out


def score_row(acc: dict, v: dict | None, min_score: float) -> dict:
    sim = float(acc.get("similarity") or 0)
    fp = float(acc.get("score") or 0)
    conf = v["confidence"] if v else 0.0
    fit = v["fit"] if v else "not checked"
    fp_pct = min(fp / 400, 1) * 100  # footprint capped at 400 of 800
    if v is None:  # --skip-validate: similarity + footprint only
        score = round(0.85 * sim + 0.15 * fp_pct)
    else:
        score = round(0.55 * sim + 0.35 * conf + 0.10 * fp_pct)
    qualified = (fit == "yes" or v is None) and score >= min_score
    reasons = []
    if v and v["reason"]:
        reasons.append(v["reason"])
    reasons.append(f"similarity {sim:.0f}/100, footprint {fp:.0f}/800")
    if fit == "no":
        reasons.insert(0, "DiscoLike ICP check: not a fit")
    elif score < min_score:
        reasons.insert(0, f"score below {min_score:g}")
    industries = acc.get("industry_groups") or {}
    linkedin = next((u for u in acc.get("social_urls") or [] if "linkedin.com/company" in u), "")
    return {
        "domain": normalize_domain(acc.get("domain", "")),
        "company_name": acc.get("name") or "",
        "qualified": "yes" if qualified else "no",
        "score": score,
        "reason": "; ".join(reasons),
        "similarity": sim, "icp_fit": fit, "icp_confidence": conf, "footprint": fp,
        "employees": acc.get("employees") or "",
        "industry": ", ".join(industries) if isinstance(industries, dict) else str(industries),
        "linkedin_url": linkedin,
        "description": (acc.get("description") or "")[:300],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--strategy", default="strategy.json")
    p.add_argument("--max-records", type=int, default=200, help="5-10000, default 200")
    p.add_argument("--min-similarity", type=int, default=None)
    p.add_argument("--min-score", type=float, default=60)
    p.add_argument("--skip-validate", action="store_true", help="score on similarity only (no ICP check credits)")
    p.add_argument("--count-only", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="print the query, call nothing")
    p.add_argument("--out", default="qualified_accounts.csv")
    p.add_argument("--all-out", default="scored_accounts.csv", help="every account, qualified or not")
    a = p.parse_args(argv)
    s = read_json(a.strategy)
    params = discover_params(s, a.max_records, a.min_similarity)
    if a.dry_run:
        dry_run_print(f"GET {BASE}/discover", params)
        return 0
    if a.count_only:
        print(f"{count(params)} companies match the filters (before ICP text ranking)")
        return 0
    accounts = discover(params)
    log(f"DiscoLike returned {len(accounts)} accounts")
    checks = {} if a.skip_validate else validate(s["icp"]["icp_text"], [normalize_domain(x["domain"]) for x in accounts])
    rows = [score_row(acc, checks.get(normalize_domain(acc["domain"])) if not a.skip_validate else None, a.min_score)
            for acc in accounts]
    rows.sort(key=lambda r: -r["score"])
    write_csv(a.all_out, rows, FIELDS)
    q = [r for r in rows if r["qualified"] == "yes"]
    write_csv(a.out, q, FIELDS)
    print(f"{len(q)}/{len(rows)} accounts qualified -> {a.out} (all scores in {a.all_out})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
