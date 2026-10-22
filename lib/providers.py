"""People and email providers used by the waterfalls in skills 04 and 05.

Every function returns plain dicts with the same keys, so the waterfall
logic does not care which provider answered:

  person: first_name, last_name, full_name, title, linkedin_url,
          email, email_status, source
  email : email, email_status, source

Docs:
  Clay CLI       https://github.com/clay-run/agent-plugins (skills/searches)
  QuickEnrich    https://app.quickenrich.io/docs
  BlitzAPI       https://docs.blitz-api.ai
  GetLeads       https://app.getleads.io/docs
  Prospeo        https://prospeo.io/api-docs/enrich-person
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Callable

from gtm_common import ApiError, RateLimiter, http, require_env

QE_BASE = "https://app.quickenrich.io"
BLITZ_BASE = "https://api.blitz-api.ai"
GETLEADS_BASE = "https://app.getleads.io/api/v1"
PROSPEO_URL = "https://api.prospeo.io/enrich-person"

_qe_limit = RateLimiter(4)       # documented 300 requests/minute
_blitz_limit = RateLimiter(4)
_gl_limit = RateLimiter(2)
_prospeo_limit = RateLimiter(2)


def _key(name: str) -> str:
    return require_env(name)[name]


def person(first="", last="", full="", title="", linkedin="", email="", status="", source="") -> dict:
    first, last = (first or "").strip(), (last or "").strip()
    if not (first or last) and full:
        parts = full.strip().split(" ", 1)
        first, last = parts[0], parts[1] if len(parts) > 1 else ""
    return {
        "first_name": first, "last_name": last,
        "full_name": (full or f"{first} {last}").strip(),
        "title": (title or "").strip(), "linkedin_url": (linkedin or "").strip(),
        "email": (email or "").strip().lower(), "email_status": status or "", "source": source,
    }


def title_ok(title: str, exclude: list[str]) -> bool:
    t = (title or "").lower()
    return not any(x.lower() in t for x in exclude or [])


# =========================================================== Clay (CLI)
CLAY_QUERY_TEMPLATE = (
    'select from people where experiences.any(is_current = true and company.domain = "{domain}" '
    "and (job_title is_similar_to ({titles})))"
)
# TODO: `company.domain` inside experiences.any(...) is shown in Clay's audience
# queries, not in a people-search example. Run `clay searches query-mode reference`
# and adjust CLAY_QUERY_TEMPLATE (or pass --clay-query-template) if validation fails (exit 2).


def _first(d: dict, *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if v:
            return v if isinstance(v, str) else str(v)
    return ""


def clay_people(domain: str, titles: list[str], exclude: list[str], limit: int,
                template: str = CLAY_QUERY_TEMPLATE, run: Callable = subprocess.run) -> list[dict]:
    binary = shutil.which("clay")
    if not binary and run is subprocess.run:
        raise RuntimeError("clay CLI not found. Install: see 04-people-waterfall/SKILL.md")
    q = template.format(domain=domain, titles=", ".join(json.dumps(t) for t in titles))
    created = run([binary or "clay", "searches", "query-mode", "create", "--query", q],
                  capture_output=True, text=True, timeout=120)
    if created.returncode != 0:
        raise RuntimeError(f"clay create failed (exit {created.returncode}): {created.stderr[:300]}")
    sid = json.loads(created.stdout)["searchId"]
    ran = run([binary or "clay", "searches", "query-mode", "run", sid, "--limit", str(max(limit * 3, 5))],
              capture_output=True, text=True, timeout=300)
    if ran.returncode != 0:
        raise RuntimeError(f"clay run failed (exit {ran.returncode}): {ran.stderr[:300]}")
    out = []
    for r in json.loads(ran.stdout).get("data") or []:
        exp = (r.get("matched_experiences") or r.get("experiences") or [{}])[0] or {}
        # TODO: confirm Clay people-search field names (linkedin_url vs profile_url).
        p = person(r.get("first_name"), r.get("last_name"), _first(r, "full_name", "name"),
                   _first(exp, "job_title", "title") or _first(r, "job_title", "headline"),
                   _first(r, "linkedin_url", "profile_url", "url"), _first(r, "email", "work_email"),
                   "", "clay")
        if title_ok(p["title"], exclude):
            out.append(p)
    return out[:limit]


# ======================================================== QuickEnrich
def _qe_headers() -> dict:
    return {"Authorization": f"Bearer {_key('QUICKENRICH_API_KEY')}"}


def quickenrich_people(domain: str, titles: list[str], exclude: list[str], limit: int) -> list[dict]:
    _qe_limit.wait()
    data = http("GET", f"{QE_BASE}/api/employees/dataset-search", headers=_qe_headers(),
                params={"company_url": domain, "title": ", ".join(titles), "page": 1})
    out = []
    for r in (data or {}).get("data") or []:
        p = person(r.get("first_name"), r.get("last_name"), r.get("full_name", ""), r.get("title"),
                   r.get("employee_linkedin") or r.get("linkedin_url", ""), r.get("email", ""), "", "quickenrich")
        if title_ok(p["title"], exclude):
            out.append(p)
    return out[:limit]


def quickenrich_email(p: dict, domain: str) -> dict | None:
    params = ({"linkedin_url": p["linkedin_url"]} if p.get("linkedin_url")
              else {"company_url": domain, "first_name": p["first_name"], "last_name": p["last_name"]})
    _qe_limit.wait()
    try:
        data = http("GET", f"{QE_BASE}/api/employees/search", headers=_qe_headers(), params=params)
    except ApiError as e:
        if e.status == 404:
            return None
        raise
    d = (data or {}).get("data")
    # TODO: a miss returns `data: []` in our tests of the docs; a hit returns an object.
    if isinstance(d, list):
        d = d[0] if d else None
    if d and d.get("email"):
        return {"email": d["email"].lower(), "email_status": "", "source": "quickenrich"}
    return None


# =========================================================== BlitzAPI
def _blitz_headers() -> dict:
    return {"x-api-key": _key("BLITZ_API_KEY")}


def blitz_company_linkedin(domain: str) -> str:
    _blitz_limit.wait()
    data = http("POST", f"{BLITZ_BASE}/v2/enrichment/domain-to-linkedin", headers=_blitz_headers(),
                json_body={"domain": domain})
    return (data or {}).get("company_linkedin_url", "") if (data or {}).get("found") else ""


def blitz_people(domain: str, titles: list[str], exclude: list[str], limit: int,
                 company_linkedin_url: str = "") -> list[dict]:
    url = company_linkedin_url or blitz_company_linkedin(domain)
    if not url:
        return []
    _blitz_limit.wait()
    data = http("POST", f"{BLITZ_BASE}/v2/search/waterfall-icp-keyword", headers=_blitz_headers(),
                json_body={
                    "company_linkedin_url": url,
                    "cascade": [{"include_title": titles, "exclude_title": exclude or [],
                                 "location": ["WORLD"], "include_headline_search": False}],
                    "max_results": max(1, min(limit, 100)),
                })
    out = []
    for r in (data or {}).get("results") or []:
        pp = r.get("person") or {}
        cur = next((e for e in pp.get("experiences") or [] if e.get("job_is_current")), {})
        out.append(person(pp.get("first_name"), pp.get("last_name"), pp.get("full_name", ""),
                          cur.get("job_title") or pp.get("headline", ""), pp.get("linkedin_url", ""),
                          "", "", "blitz"))
    return out[:limit]


def blitz_email(p: dict, domain: str) -> dict | None:
    if not p.get("linkedin_url"):
        return None
    _blitz_limit.wait()
    data = http("POST", f"{BLITZ_BASE}/v2/enrichment/email", headers=_blitz_headers(),
                json_body={"person_linkedin_url": p["linkedin_url"]})
    if (data or {}).get("found") and data.get("email"):
        return {"email": data["email"].lower(), "email_status": "", "source": "blitz"}
    return None


# =========================================================== GetLeads
def _gl_headers() -> dict:
    return {"Authorization": f"Bearer {_key('GETLEADS_API_KEY')}"}


def _gl_row(r: dict) -> dict:
    return person(r.get("first_name"), r.get("last_name"), r.get("full_name", ""), r.get("current_title"),
                  r.get("linkedin_url", ""), r.get("work_email", ""), r.get("email_status", ""), "getleads")


def getleads_people(domain: str, titles: list[str], exclude: list[str], limit: int,
                    company_linkedin_url: str = "") -> list[dict]:
    body = {"job_titles": titles, "limit_per_item": max(limit * 3, 5), "offset": 0}
    if company_linkedin_url:
        body["linkedin_company_url"] = company_linkedin_url  # current employees only
    else:
        body["email_domain"] = domain
    _gl_limit.wait()
    data = http("POST", f"{GETLEADS_BASE}/contacts/lookup/colleagues", headers=_gl_headers(),
                json_body=body, timeout=90)
    rows = [_gl_row(r) for r in (data or {}).get("contacts") or [] if isinstance(r, dict)]
    return [p for p in rows if title_ok(p["title"], exclude)][:limit]


def getleads_email(p: dict, domain: str) -> dict | None:
    if p.get("linkedin_url"):
        path, body = "/enrich/from-linkedin", {"items": [{"linkedin_url": p["linkedin_url"]}], "limit_per_item": 1}
    elif p.get("first_name") and p.get("last_name"):
        path, body = "/enrich/from-person", {"items": [{"first_name": p["first_name"], "last_name": p["last_name"],
                                                        "email_domain": domain}]}
    else:
        return None
    _gl_limit.wait()
    data = http("POST", GETLEADS_BASE + path, headers=_gl_headers(), json_body=body, timeout=90)
    for r in (data or {}).get("results") or []:
        if r.get("success") and r.get("email"):
            status = ((r.get("data") or {}).get("email_status") or "")
            return {"email": r["email"].lower(), "email_status": status, "source": "getleads"}
    return None


# ============================================================ Prospeo
def prospeo_email(p: dict, domain: str, company_name: str = "") -> dict | None:
    data_in = {"company_website": domain}
    if p.get("linkedin_url"):
        data_in["linkedin_url"] = p["linkedin_url"]
    if p.get("first_name"):
        data_in["first_name"] = p["first_name"]
    if p.get("last_name"):
        data_in["last_name"] = p["last_name"]
    if company_name:
        data_in["company_name"] = company_name
    _prospeo_limit.wait()
    try:
        data = http("POST", PROSPEO_URL, headers={"X-KEY": _key("PROSPEO_API_KEY")},
                    json_body={"only_verified_email": True, "data": data_in})
    except ApiError as e:
        if e.status in (400, 404) and "NO_MATCH" in e.body:
            return None  # not charged
        raise
    if (data or {}).get("error"):
        return None
    em = ((data or {}).get("person") or {}).get("email") or {}
    if em.get("email"):
        return {"email": em["email"].lower(), "email_status": em.get("status", ""), "source": "prospeo"}
    return None


PEOPLE_PROVIDERS = {
    "clay": clay_people,
    "quickenrich": quickenrich_people,
    "blitz": blitz_people,
    "getleads": getleads_people,
}
EMAIL_PROVIDERS = {
    "quickenrich": quickenrich_email,
    "blitz": blitz_email,
    "getleads": getleads_email,
    "prospeo": prospeo_email,
}
