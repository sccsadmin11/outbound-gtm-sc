#!/usr/bin/env python3
"""Speed-to-lead relay: PlusVibe reply -> Clay -> PlusVibe DRAFT + Slack pings.

Routes
  POST /plusvibe       PlusVibe "ALL_EMAIL_REPLIES" webhook. Checks the HMAC
                       `Signature` header, stores the reply, forwards it to the
                       Clay webhook table with a callback URL.
  POST /clay-callback  Clay HTTP API column posts {reply_id, classification,
                       draft_reply}. Needs header X-Relay-Secret. Saves the reply
                       as a DRAFT in PlusVibe (never sends) and queues Slack pings.
  GET  /handled        Link in the Slack ping. Marks the reply handled and
                       cancels the second ping. Signed with RELAY_SHARED_SECRET.
  GET  /health         {"ok": true} for uptime checks and skill 11.

A background loop sends due Slack pings: +0 and +5 minutes, only Mon-Fri
09:00-17:00 America/New_York. Outside those hours pings are queued for 09:00
(and 09:05) the next business day.

Env: PLUSVIBE_WEBHOOK_SECRET, RELAY_SHARED_SECRET, RELAY_PUBLIC_URL, CLAY_WEBHOOK_URL,
     CLAY_WEBHOOK_AUTH_TOKEN (optional), SLACK_BOT_TOKEN, PLUSVIBE_API_KEY,
     PLUSVIBE_WORKSPACE_ID
--dry-run (or RELAY_DRY_RUN=1): verify and log everything, but do not call
Clay, PlusVibe or Slack.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "lib"))
sys.path.insert(0, str(HERE))
from business_hours import ping_times  # noqa: E402
from copy_utils import text_to_html  # noqa: E402
from gtm_common import ApiError, http, load_dotenv, log, optional_env, read_json  # noqa: E402

CLASSES = ["interested", "meeting_request", "question", "referral", "not_now", "not_interested", "ooo", "unsubscribe"]
MAX_BODY = 1_000_000


# ---------------------------------------------------------------- helpers
def sign(secret: str, raw: bytes) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def verify_signature(secret: str, raw: bytes, header: str | None) -> bool:
    return bool(header) and hmac.compare_digest(sign(secret, raw), header.strip().lower())


def normalize_class(label: str) -> str:
    s = re.sub(r"[^a-z]+", "_", (label or "").strip().lower()).strip("_")
    aliases = {"meeting": "meeting_request", "meeting_requested": "meeting_request", "out_of_office": "ooo",
               "not_right_now": "not_now", "later": "not_now", "unsub": "unsubscribe", "remove": "unsubscribe",
               "wrong_person": "referral"}
    s = aliases.get(s, s)
    return s if s in CLASSES else "question"  # unknown -> a human looks at it


def pick_rep(reps: dict, inbox: str, campaign_id: str) -> dict:
    inbox = (inbox or "").lower()
    by_inbox = {k.lower(): v for k, v in (reps.get("by_inbox") or {}).items()}
    return by_inbox.get(inbox) or (reps.get("by_campaign") or {}).get(campaign_id) or reps.get("default") or {}


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------- state
class Store:
    """Tiny JSON file store: replies + ping queue. Survives restarts."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"replies": {}, "pings": []}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)


# ---------------------------------------------------------------- app
class Relay:
    def __init__(self, cfg: dict, store: Store, dry_run: bool, clock=now_utc):
        self.cfg = cfg
        self.store = store
        self.dry = dry_run
        self.clock = clock
        self.routing = cfg["routing"]
        self.reps = cfg["reps"]

    # --- PlusVibe -> Clay
    def on_plusvibe(self, raw: bytes, signature: str | None) -> tuple[int, dict]:
        if not verify_signature(self.cfg["PLUSVIBE_WEBHOOK_SECRET"], raw, signature):
            return 401, {"error": "bad signature"}
        ev = json.loads(raw or b"{}")
        if ev.get("direction") not in (None, "", "IN"):
            return 200, {"ignored": "outbound message"}
        if "REPL" not in str(ev.get("webhook_event", "")).upper():
            return 200, {"ignored": ev.get("webhook_event")}
        reply_id = str(ev.get("last_email_id") or ev.get("message_id") or ev.get("source_message_id") or "")
        if not reply_id:
            return 400, {"error": "no message id in payload"}
        with self.store.lock:
            if reply_id in self.store.data["replies"]:
                return 200, {"duplicate": reply_id}
            rep = pick_rep(self.reps, ev.get("to_email", ""), ev.get("campaign_id", ""))
            self.store.data["replies"][reply_id] = {
                "received_at": self.clock().isoformat(), "status": "sent_to_clay", "handled": False,
                "rep": rep, "lead_email": ev.get("from_email") or ev.get("email"),
                "inbox": ev.get("to_email"), "subject": ev.get("subject", ""),
                "first_name": ev.get("first_name", ""), "company_name": ev.get("company_name", ""),
                "campaign_id": ev.get("campaign_id", ""), "snippet": (ev.get("text_body") or ev.get("snippet") or "")[:500],
            }
            self.store.save()
        payload = {
            "reply_id": reply_id,
            "callback_url": self.cfg["RELAY_PUBLIC_URL"].rstrip("/") + "/clay-callback",
            "lead_email": ev.get("from_email") or ev.get("email"),
            "first_name": ev.get("first_name", ""), "last_name": ev.get("last_name", ""),
            "company_name": ev.get("company_name", ""), "job_title": ev.get("job_title", ""),
            "company_website": ev.get("company_website", ""),
            "inbox": ev.get("to_email", ""), "sender_first_name": ev.get("sender_first_name", ""),
            "subject": ev.get("subject", ""), "reply_text": ev.get("text_body") or ev.get("snippet", ""),
            "plusvibe_label": ev.get("label", ""), "plusvibe_sentiment": ev.get("sentiment", ""),
            "campaign_name": ev.get("campaign_name", ""), "step": ev.get("step", ""), "variation": ev.get("variation", ""),
        }
        self.forward_to_clay(payload)
        return 200, {"ok": True, "reply_id": reply_id}

    def forward_to_clay(self, payload: dict):
        if self.dry:
            log(f"[dry-run] would POST reply {payload['reply_id']} to the Clay webhook")
            return
        headers = {}
        if self.cfg.get("CLAY_WEBHOOK_AUTH_TOKEN"):
            headers["x-clay-webhook-auth"] = self.cfg["CLAY_WEBHOOK_AUTH_TOKEN"]  # TODO: confirm header name in your Clay webhook settings
        try:
            http("POST", self.cfg["CLAY_WEBHOOK_URL"], headers=headers, json_body=payload, retries=3)
        except ApiError as e:
            log(f"Clay forward failed for {payload['reply_id']}: {e}")

    # --- Clay -> PlusVibe draft + Slack
    def on_clay(self, raw: bytes, secret_header: str | None) -> tuple[int, dict]:
        if not secret_header or not hmac.compare_digest(secret_header, self.cfg["RELAY_SHARED_SECRET"]):
            return 401, {"error": "bad secret"}
        body = json.loads(raw or b"{}")
        reply_id = str(body.get("reply_id", ""))
        with self.store.lock:
            r = self.store.data["replies"].get(reply_id)
        if not r:
            return 404, {"error": "unknown reply_id"}
        cls = normalize_class(body.get("classification", ""))
        route = self.routing.get(cls, {"draft": True, "pings": 2})
        draft = (body.get("draft_reply") or "").strip()
        drafted = False
        if route.get("draft") and draft:
            drafted = self.save_draft(reply_id, r, draft)
        with self.store.lock:
            r.update(classification=cls, status="drafted" if drafted else "classified", draft_saved=drafted)
            # pings start when the draft is ready: +0 and +5 min, business hours only
            for i, t in enumerate(ping_times(self.clock(), int(route.get("pings", 0)))):
                self.store.data["pings"].append({"reply_id": reply_id, "n": i + 1, "due": t.isoformat(), "status": "pending"})
            self.store.save()
        return 200, {"ok": True, "classification": cls, "draft_saved": drafted, "pings": int(route.get("pings", 0))}

    def save_draft(self, reply_id: str, r: dict, text: str) -> bool:
        subj = r.get("subject") or ""
        subj = subj if subj.lower().startswith("re:") else f"Re: {subj}".strip()
        if self.dry:
            log(f"[dry-run] would save a PlusVibe DRAFT reply to {r['lead_email']} from {r['inbox']}")
            return True
        from plusvibe import PlusVibe
        try:
            # TODO: parent_message_id = webhook last_email_id (PlusVibe says it is the reply_to_id); confirm it is the unibox email id.
            PlusVibe().save_draft(reply_id, r["inbox"], [r["lead_email"]], subj, text_to_html(text))
            return True
        except (ApiError, SystemExit) as e:
            log(f"draft save failed for {reply_id}: {e}")
            return False

    # --- pings
    def handled_url(self, reply_id: str) -> str:
        sig = sign(self.cfg["RELAY_SHARED_SECRET"], reply_id.encode())
        q = urllib.parse.urlencode({"reply_id": reply_id, "sig": sig})
        return self.cfg["RELAY_PUBLIC_URL"].rstrip("/") + "/handled?" + q

    def on_handled(self, query: dict) -> tuple[int, dict]:
        rid = (query.get("reply_id") or [""])[0]
        sig = (query.get("sig") or [""])[0]
        if not hmac.compare_digest(sign(self.cfg["RELAY_SHARED_SECRET"], rid.encode()), sig):
            return 401, {"error": "bad link"}
        with self.store.lock:
            r = self.store.data["replies"].get(rid)
            if not r:
                return 404, {"error": "unknown reply"}
            r["handled"] = True
            r["handled_at"] = self.clock().isoformat()
            for p in self.store.data["pings"]:
                if p["reply_id"] == rid and p["status"] == "pending":
                    p["status"] = "cancelled"
            self.store.save()
        return 200, {"ok": True, "handled": rid}

    def ping_text(self, r: dict, n: int, reply_id: str) -> str:
        who = f"{r.get('first_name') or ''} at {r.get('company_name') or r.get('lead_email')}".strip()
        head = "New reply" if n == 1 else "Reminder (not handled yet)"
        draft = "A draft reply is waiting in PlusVibe Unibox." if r.get("draft_saved") else "No draft. Reply by hand in PlusVibe Unibox."
        return (f"*{head}: {r.get('classification', '?').replace('_', ' ')}* from {who} ({r.get('lead_email')})\n"
                f"> {r.get('snippet', '')[:300]}\n{draft}\n<{self.handled_url(reply_id)}|Mark handled>")

    def send_due_pings(self) -> int:
        sent = 0
        now = self.clock()
        with self.store.lock:
            due = [p for p in self.store.data["pings"]
                   if p["status"] == "pending" and dt.datetime.fromisoformat(p["due"]) <= now]
        for p in due:
            with self.store.lock:
                r = self.store.data["replies"].get(p["reply_id"], {})
                if r.get("handled"):
                    p["status"] = "cancelled"
                    self.store.save()
                    continue
            ok = self.slack_post(r.get("rep", {}), self.ping_text(r, p["n"], p["reply_id"]))
            with self.store.lock:
                p["status"] = "sent" if ok else "failed"
                p["sent_at"] = now.isoformat()
                self.store.save()
            sent += ok
        return sent

    def slack_post(self, rep: dict, text: str) -> bool:
        channel = rep.get("slack_user_id") or self.cfg.get("SLACK_FALLBACK_CHANNEL")
        if not channel:
            log("no Slack user or fallback channel for this rep")
            return False
        if self.dry:
            log(f"[dry-run] would Slack {rep.get('name', channel)}: {text.splitlines()[0]}")
            return True
        try:
            res = http("POST", "https://slack.com/api/chat.postMessage",
                       headers={"Authorization": f"Bearer {self.cfg['SLACK_BOT_TOKEN']}"},
                       json_body={"channel": channel, "text": text, "unfurl_links": False})
        except ApiError as e:
            log(f"Slack error: {e}")
            return False
        if not res.get("ok"):
            log(f"Slack error: {res.get('error')}")
        return bool(res.get("ok"))


# ---------------------------------------------------------------- server
def make_handler(app: Relay):
    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, obj: dict):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(min(n, MAX_BODY))

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            try:
                if path == "/plusvibe":
                    return self._send(*app.on_plusvibe(self._body(), self.headers.get("Signature")))
                if path == "/clay-callback":
                    return self._send(*app.on_clay(self._body(), self.headers.get("X-Relay-Secret")))
            except (ValueError, KeyError) as e:
                return self._send(400, {"error": f"bad request: {type(e).__name__}"})
            self._send(404, {"error": "not found"})

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/health":
                return self._send(200, {"ok": True})
            if u.path == "/handled":
                return self._send(*app.on_handled(urllib.parse.parse_qs(u.query)))
            self._send(404, {"error": "not found"})

        def log_message(self, fmt, *args):  # no request lines with query strings (signed links) in logs
            log(f"{self.command} {urllib.parse.urlparse(self.path).path} -> {args[1] if len(args) > 1 else ''}")

    return H


def load_config(reps_path: str, routing_path: str, dry_run: bool) -> dict:
    load_dotenv()
    needed = ["PLUSVIBE_WEBHOOK_SECRET", "RELAY_SHARED_SECRET", "RELAY_PUBLIC_URL"]
    if not dry_run:
        needed += ["CLAY_WEBHOOK_URL", "SLACK_BOT_TOKEN", "PLUSVIBE_API_KEY", "PLUSVIBE_WORKSPACE_ID"]
    missing = [k for k in needed if not optional_env(k)]
    if missing:
        raise SystemExit("Missing env vars: " + ", ".join(missing) + " (see .env.example)")
    cfg = {k: optional_env(k) for k in needed + ["CLAY_WEBHOOK_URL", "CLAY_WEBHOOK_AUTH_TOKEN", "SLACK_BOT_TOKEN",
                                                 "SLACK_FALLBACK_CHANNEL"]}
    cfg["reps"] = read_json(reps_path)
    cfg["routing"] = {k: v for k, v in read_json(routing_path).items() if not k.startswith("_")}
    return cfg


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    p.add_argument("--reps", default=str(HERE.parent / "config" / "reps.json"))
    p.add_argument("--routing", default=str(HERE.parent / "config" / "routing.json"))
    p.add_argument("--state", default="relay_state.json")
    p.add_argument("--tick", type=int, default=15, help="seconds between ping checks")
    p.add_argument("--dry-run", action="store_true", default=os.environ.get("RELAY_DRY_RUN") == "1")
    a = p.parse_args(argv)
    cfg = load_config(a.reps, a.routing, a.dry_run)
    app = Relay(cfg, Store(Path(a.state)), a.dry_run)

    def loop():
        while True:
            try:
                app.send_due_pings()
            except Exception as e:  # keep the loop alive
                log(f"ping loop error: {type(e).__name__}: {e}")
            time.sleep(a.tick)

    threading.Thread(target=loop, daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(app))
    log(f"relay listening on {a.host}:{a.port} ({'DRY RUN' if a.dry_run else 'live'})")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
