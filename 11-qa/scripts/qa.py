#!/usr/bin/env python3
"""Pre-launch QA. Every check must pass or the campaign stays paused.

Checks
  1. leads_unique        no duplicate emails
  2. leads_verified      every email passed skill 06 (MillionVerifier ok or BounceBan deliverable)
  3. merge_vars_filled   every merge var in every email has a value for every lead
  4. signature_opt_out   signature + opt-out line in every email body
  5. spam_check_passed   spam_report.json passed and matches the current sequence.json
  6. plusvibe_settings   daily limit = connected inboxes x 15, 50/50 (send_priority 0.5),
                         plain text, open tracking off, all ACTIVE Google inboxes connected
  7. webhook_reachable   relay GET /health answers ok (+ a PlusVibe webhook points at it in --live mode)

Modes
  default   offline: settings come from campaign_state.json (skill 09)
  --live    read-back from the PlusVibe API (read-only GET calls)
  --launch  after a full pass, activate the campaign (POST /campaign/launch). Needs --live.
            Combine with --dry-run to see what would happen. Launching sends real email.

Output: qa_report.json + qa_report.md. Exit code 0 = pass, 1 = fail (launch blocked).
Env (live only): PLUSVIBE_API_KEY, PLUSVIBE_WORKSPACE_ID
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from copy_utils import MERGE_RE, SLOT_RE, SYSTEM_VARS, render  # noqa: E402
from gtm_common import BROWSER_UA, dry_run_print, read_csv, read_json, write_json  # noqa: E402

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TRUE_VALUES = {"yes", "1", "true", 1, True}
FALSE_VALUES = {"no", "0", "false", 0, False, "", None}


def result(name: str, ok: bool, detail: str, items: list | None = None) -> dict:
    return {"check": name, "passed": bool(ok), "detail": detail, "items": (items or [])[:50]}


# ---------------------------------------------------------------- lead checks
def check_unique(leads: list[dict]) -> dict:
    seen, dupes = set(), []
    for r in leads:
        e = (r.get("email") or "").strip().lower()
        if e in seen:
            dupes.append(e)
        seen.add(e)
    return result("leads_unique", not dupes and bool(leads),
                  f"{len(leads)} leads, {len(dupes)} duplicate(s)" if leads else "no leads", dupes)


def is_verified(r: dict, allow_risky: bool) -> bool:
    mv = (r.get("verify_mv") or "").strip().lower()
    bb = (r.get("verify_bb") or "").strip().lower()
    return mv == "ok" or bb == "deliverable" or (allow_risky and bb == "risky")


def check_verified(leads: list[dict], rejected: set[str], allow_risky: bool) -> dict:
    bad = []
    for r in leads:
        e = (r.get("email") or "").strip().lower()
        if not EMAIL_RE.match(e):
            bad.append(f"{e or '(empty)'}: malformed")
        elif e in rejected:
            bad.append(f"{e}: in rejected_emails.csv")
        elif not is_verified(r, allow_risky):
            bad.append(f"{e}: no passing verification (verify_mv={r.get('verify_mv', '')}, verify_bb={r.get('verify_bb', '')})")
    return result("leads_verified", not bad, f"{len(leads) - len(bad)}/{len(leads)} verified", bad)


# ---------------------------------------------------------------- copy checks
def variations(seq: dict):
    for st in seq.get("steps", []):
        for v in st.get("variations", []):
            yield f"Email {st['step']}{v['variation']}", v


def check_merge_vars(seq: dict, leads: list[dict]) -> dict:
    problems = []
    for label, v in variations(seq):
        text = f"{v.get('subject', '')}\n{v.get('body_text', '')}"
        for slot in SLOT_RE.findall(text):
            if not MERGE_RE.fullmatch("{{" + slot + "}}"):
                problems.append(f"{label}: unfilled template slot {{{{{slot}}}}}")
        for r in leads:
            _, missing = render(text, r)
            missing = sorted(set(missing) - SYSTEM_VARS)
            if missing:
                problems.append(f"{label} -> {r.get('email')}: no value for {', '.join(missing)}")
    return result("merge_vars_filled", not problems, "all merge vars have values" if not problems
                  else f"{len(problems)} problem(s)", problems)


def check_signature(seq: dict, expected_opt_out: str | None) -> dict:
    sig = (seq.get("signature") or "").strip()
    opt = (expected_opt_out or seq.get("opt_out") or "").strip()
    problems = []
    if not sig:
        problems.append("sequence.json has no signature")
    if not opt:
        problems.append("no opt-out line configured")
    for label, v in variations(seq):
        body = v.get("body_text", "")
        if sig and sig not in body:
            problems.append(f"{label}: signature missing")
        if opt and opt not in body:
            problems.append(f"{label}: opt-out line missing")
        if opt and opt.replace("'", "&#x27;") not in v.get("body_html", "") and opt not in v.get("body_html", ""):
            problems.append(f"{label}: opt-out line missing from body_html")
    return result("signature_opt_out", not problems, "signature + opt-out in every email" if not problems
                  else f"{len(problems)} problem(s)", problems)


def check_spam(report_path: Path, seq_path: Path) -> dict:
    if not report_path.exists():
        return result("spam_check_passed", False, f"{report_path} not found (run skill 08)")
    rep = read_json(report_path)
    sha = hashlib.sha256(seq_path.read_bytes()).hexdigest()
    if not rep.get("passed"):
        return result("spam_check_passed", False, f"{rep.get('hit_count')} spam hit(s) open", rep.get("hits"))
    if rep.get("sequence_sha256") != sha:
        return result("spam_check_passed", False, "sequence.json changed after the spam check. Run skill 08 again.")
    return result("spam_check_passed", True, "passed, matches current sequence.json")


# ---------------------------------------------------------------- PlusVibe
def expected_inboxes(inbox_csv: str | None, live_accounts: list[dict] | None) -> set[str] | None:
    """ACTIVE Google inboxes that should be on the campaign."""
    from plusvibe import is_active_google
    if live_accounts is not None:
        pool = [a for a in live_accounts if is_active_google(a)]
        emails = {str(a.get("email", "")).lower() for a in pool}
        if inbox_csv:
            emails &= {r["email"].lower() for r in read_csv(inbox_csv)}
        return emails
    if inbox_csv:
        return {r["email"].lower() for r in read_csv(inbox_csv) if is_active_google(r)}
    return None


def check_settings(s: dict, connected: list[str], expected: set[str] | None, per_inbox: int) -> dict:
    problems = []
    n = len(connected)
    if n == 0:
        problems.append("no inboxes connected")
    want = n * per_inbox
    if int(s.get("daily_limit") or 0) != want:
        problems.append(f"daily_limit is {s.get('daily_limit')}, expected {n} inboxes x {per_inbox} = {want}")
    if float(s.get("send_priority", -1)) != 0.5:
        problems.append(f"send_priority is {s.get('send_priority')}, expected 0.5 (50/50 new vs follow-up)")
    new_lim = s.get("daily_limit_new_lead")
    if new_lim not in (None, "") and int(new_lim) != want // 2:
        problems.append(f"daily_limit_new_lead is {new_lim}, expected {want // 2}")
    if s.get("send_as_txt") not in TRUE_VALUES:
        problems.append(f"send_as_txt is {s.get('send_as_txt')!r}, expected plain text")
    if s.get("is_emailopened_tracking") not in FALSE_VALUES:
        problems.append(f"open tracking is {s.get('is_emailopened_tracking')!r}, expected off")
    if "is_unsubscribed_link" in s and s.get("is_unsubscribed_link") not in FALSE_VALUES:
        problems.append("PlusVibe unsubscribe link is on (the copy already has the opt-out line)")
    if expected is not None:
        missing = sorted(expected - {c.lower() for c in connected})
        if missing:
            problems.append(f"{len(missing)} ACTIVE Google inbox(es) not connected: {', '.join(missing)}")
    return result("plusvibe_settings", not problems,
                  f"{n} inboxes, limit {s.get('daily_limit')}, priority {s.get('send_priority')}" if not problems
                  else f"{len(problems)} problem(s)", problems)


def live_settings(pv, campaign_id: str) -> tuple[dict, list[str]]:
    camp = pv.get_campaign(campaign_id)
    if not camp:
        raise SystemExit(f"campaign {campaign_id} not found in PlusVibe")
    connected = [a if isinstance(a, str) else a.get("email", "") for a in pv.campaign_accounts(campaign_id)]
    return camp, connected


# ---------------------------------------------------------------- webhook
def check_webhook(relay_url: str | None, hooks=None, session=requests) -> dict:
    if not relay_url:
        return result("webhook_reachable", False, "no --relay-url given (deploy skill 10 first)")
    url = relay_url.rstrip("/") + "/health"
    try:
        r = session.get(url, timeout=10, headers={"User-Agent": BROWSER_UA})
        ok = r.status_code == 200 and r.json().get("ok") is True
    except (requests.RequestException, ValueError) as e:
        return result("webhook_reachable", False, f"{url} not reachable: {type(e).__name__}")
    if not ok:
        return result("webhook_reachable", False, f"{url} answered {r.status_code}")
    if hooks is not None:
        # TODO: /hook/list response shape is not documented in detail; we search every string value for the relay URL.
        target = relay_url.rstrip("/") + "/plusvibe"
        if target not in repr(hooks):
            return result("webhook_reachable", False, f"relay is up but no PlusVibe webhook points at {target} "
                          "(run 10-speed-to-lead/scripts/register_webhook.py)")
        return result("webhook_reachable", True, f"{url} ok and PlusVibe webhook registered")
    return result("webhook_reachable", True, f"{url} ok")


# ---------------------------------------------------------------- report
def write_report(checks: list[dict], meta: dict, out_json: str, out_md: str) -> dict:
    passed = all(c["passed"] for c in checks)
    rep = {"passed": passed, "launch_allowed": passed, "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           **meta, "checks": checks}
    write_json(out_json, rep)
    lines = [f"# QA report: {'PASS' if passed else 'FAIL (launch blocked)'}", "",
             f"Campaign: {meta.get('campaign_name') or ''} ({meta.get('campaign_id') or 'n/a'}), mode: {meta['mode']}", "",
             "| Check | Result | Detail |", "|---|---|---|"]
    for c in checks:
        lines.append(f"| {c['check']} | {'PASS' if c['passed'] else 'FAIL'} | {c['detail']} |")
    for c in checks:
        if not c["passed"] and c["items"]:
            lines += ["", f"## {c['check']}", *[f"- {i}" for i in c["items"]]]
    Path(out_md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rep


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--leads", default="verified_leads.csv")
    p.add_argument("--rejected", help="rejected_emails.csv from skill 06")
    p.add_argument("--sequence", default="sequence.json")
    p.add_argument("--spam-report", default="spam_report.json")
    p.add_argument("--campaign-state", default="campaign_state.json")
    p.add_argument("--inboxes", help="inboxes_connected.csv from skill 01 (expected inboxes)")
    p.add_argument("--opt-out", help="opt-out line that must be in every email (default: from sequence.json)")
    p.add_argument("--per-inbox", type=int, default=15)
    p.add_argument("--allow-risky", action="store_true")
    p.add_argument("--relay-url", help="public URL of the skill 10 relay")
    p.add_argument("--live", action="store_true", help="read settings back from PlusVibe (read-only)")
    p.add_argument("--launch", action="store_true", help="activate the campaign if every check passes (sends email)")
    p.add_argument("--dry-run", action="store_true", help="with --launch: show the launch call, do not make it")
    p.add_argument("--out", default="qa_report.json")
    p.add_argument("--md", default="qa_report.md")
    a = p.parse_args(argv)
    if a.launch and not a.live:
        p.error("--launch needs --live (QA must read the real campaign settings first)")

    leads = read_csv(a.leads)
    rejected = {r.get("email", "").lower() for r in read_csv(a.rejected)} if a.rejected else set()
    seq_path = Path(a.sequence)
    seq = read_json(seq_path)
    state = read_json(a.campaign_state) if Path(a.campaign_state).exists() else {}
    cid = state.get("campaign_id")

    checks = [check_unique(leads), check_verified(leads, rejected, a.allow_risky),
              check_merge_vars(seq, leads), check_signature(seq, a.opt_out),
              check_spam(Path(a.spam_report), seq_path)]

    pv = hooks = None
    if a.live:
        from plusvibe import PlusVibe
        pv = PlusVibe()
        if not cid:
            raise SystemExit(f"no campaign_id in {a.campaign_state}")
        settings, connected = live_settings(pv, cid)
        expected = expected_inboxes(a.inboxes, pv.list_accounts())
        hooks = pv.list_webhooks()
    else:
        settings = state
        connected = state.get("inbox_emails") or []
        expected = expected_inboxes(a.inboxes, None)
    checks.append(check_settings(settings, connected, expected, a.per_inbox) if (state or a.live)
                  else result("plusvibe_settings", False, f"{a.campaign_state} not found (run skill 09)"))
    checks.append(check_webhook(a.relay_url, hooks))

    rep = write_report(checks, {"mode": "live" if a.live else "offline", "campaign_id": cid,
                                "campaign_name": state.get("name"), "lead_count": len(leads)}, a.out, a.md)
    for c in checks:
        print(f"{'PASS' if c['passed'] else 'FAIL'}  {c['check']}: {c['detail']}")
    if not rep["passed"]:
        print(f"QA FAILED. Launch blocked. See {a.md}")
        return 1
    print("QA PASSED.")
    if a.launch:
        if a.dry_run:
            dry_run_print("launch campaign (starts sending)", {"campaign_id": cid})
        else:
            pv.launch_campaign(cid)
            print(f"campaign {cid} launched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
