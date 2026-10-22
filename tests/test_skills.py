"""Unit tests for the 11 skills. All HTTP is mocked; nothing leaves the machine.

Run: python -m unittest discover -s tests -v
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from _helpers import ROOT, FakeResponse, fake_requests, load

NY = ZoneInfo("America/New_York")
ENV = {"PORKBUN_API_KEY": "pk_test", "PORKBUN_SECRET_API_KEY": "sk_test", "ZAPMAIL_API_KEY": "zm_test",
       "PLUSVIBE_API_KEY": "pv_test", "PLUSVIBE_WORKSPACE_ID": "ws_test"}


def quiet():
    return redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO())


# ------------------------------------------------------------------ 01
class TestPorkbun(unittest.TestCase):
    def setUp(self):
        self.pb = load("01-infra-setup/scripts/porkbun_domains.py")
        self.pb.time.sleep = lambda s: None

    def handler(self, method, url, kw):
        if url.endswith("/domain/checkDomain"):
            return FakeResponse(200, {"status": "SUCCESS", "domains": {
                "acmeoutbound.example": {"avail": "yes", "price": "11.08", "regularPrice": "11.08",
                                         "premium": "no", "minDuration": 1}}})
        if "/domain/create/" in url:
            body = kw["json"]
            if body.get("dryRun"):
                return FakeResponse(200, {"status": "SUCCESS", "dryRun": True, "wouldSucceed": True,
                                          "cost": body["cost"], "costDisplay": "$11.08"})
            raise AssertionError("a real purchase call was made")
        raise AssertionError(url)

    def test_buy_without_confirm_never_purchases(self):
        patch, calls = fake_requests(self.handler)
        with mock.patch.dict(os.environ, ENV), patch:
            rows = self.pb.buy(["acmeoutbound.example"], confirm=False, max_cost_cents=2000)
        self.assertIn("Not purchased", rows[0]["result"])
        creates = [c for c in calls if "/domain/create/" in c[1]]
        self.assertTrue(all(c[2]["json"].get("dryRun") is True for c in creates))

    def test_cost_cap_blocks(self):
        patch, calls = fake_requests(self.handler)
        with mock.patch.dict(os.environ, ENV), patch:
            rows = self.pb.buy(["acmeoutbound.example"], confirm=True, max_cost_cents=500)
        self.assertIn("over --max-cost-cents", rows[0]["result"])
        self.assertFalse([c for c in calls if "/domain/create/" in c[1]])

    def test_confirm_purchase_flag_is_off_by_default(self):
        with quiet()[0], quiet()[1], self.assertRaises(SystemExit):
            self.pb.main(["buy", "--help"])


class TestZapmail(unittest.TestCase):
    def test_list_never_keeps_passwords(self):
        zm = load("01-infra-setup/scripts/zapmail_inboxes.py")
        page = {"data": {"domains": [{"domain": "acmeoutbound.example", "mailboxes": [
            {"id": "m1", "email": "jamie@acmeoutbound.example", "firstName": "Jamie", "lastName": "Rivera",
             "status": "ACTIVE", "password": "p@ss", "appPassword": "abcd", "twoFactorSecret": "XYZ"}]}],
            "nextPage": None, "totalPages": 1}}
        patch, _ = fake_requests(lambda m, u, kw: FakeResponse(200, page))
        with mock.patch.dict(os.environ, ENV), patch:
            rows = zm.list_mailboxes()
        self.assertEqual(rows[0]["email"], "jamie@acmeoutbound.example")
        blob = json.dumps(rows)
        for secret in ("p@ss", "abcd", "XYZ"):
            self.assertNotIn(secret, blob)

    def test_plan_respects_max_per_domain(self):
        zm = load("01-infra-setup/scripts/zapmail_inboxes.py")
        plan = [{"domain": "acmeoutbound.example", "first_name": "J", "last_name": "R", "username": f"j{i}"} for i in range(6)]
        with self.assertRaises(ValueError):
            zm.create_mailboxes(plan, dry_run=True, domain_ids={"acmeoutbound.example": "d1"})


# ------------------------------------------------------------------ 02 / 03
class TestStrategyAndScoring(unittest.TestCase):
    def test_example_strategy_is_valid_with_3_offers(self):
        rs = load("02-gtm-strategy/scripts/render_strategy.py")
        s = json.loads((ROOT / "02-gtm-strategy/examples/strategy.json").read_text())
        self.assertEqual(rs.validate(s), [])
        broken = {**s, "front_end_offers": s["front_end_offers"][:2]}
        self.assertTrue(rs.validate(broken))

    def test_score_row_yes_no(self):
        sa = load("03-account-scoring/scripts/score_accounts.py")
        acc = {"domain": "acmefreight.example", "name": "Acme Freight Lines", "similarity": 90, "score": 400}
        yes = sa.score_row(acc, {"fit": "yes", "confidence": 80, "reason": "regional carrier"}, 60)
        no = sa.score_row(acc, {"fit": "no", "confidence": 80, "reason": "software vendor"}, 60)
        self.assertEqual((yes["qualified"], no["qualified"]), ("yes", "no"))
        self.assertTrue(yes["reason"])
        self.assertIn("not a fit", no["reason"])


# ------------------------------------------------------------------ 04 / 05
class TestWaterfalls(unittest.TestCase):
    def test_people_waterfall_stops_at_first_hit(self):
        pw = load("04-people-waterfall/scripts/people_waterfall.py")
        called = []

        def mk(name, result):
            def fn(domain, titles, exclude, limit, **kw):
                called.append(name)
                return result
            return fn
        fns = {"clay": mk("clay", []), "quickenrich": mk("quickenrich", [{"full_name": "Dana Whitfield"}]),
               "blitz": mk("blitz", [{"full_name": "X"}]), "getleads": mk("getleads", [{"full_name": "Y"}])}
        people, tried = pw.find_for({"domain": "acmefreight.example"}, {"titles": ["VP Operations"]},
                                    ["clay", "quickenrich", "blitz", "getleads"], 1, provider_fns=fns)
        self.assertEqual(called, ["clay", "quickenrich"])
        self.assertEqual(people[0]["full_name"], "Dana Whitfield")

    def test_email_waterfall_stops_and_skips_missing_keys(self):
        ew = load("05-email-waterfall/scripts/email_waterfall.py")
        called = []

        def no_key(row, domain):
            called.append("quickenrich")
            raise SystemExit("Missing env vars: QUICKENRICH_API_KEY")

        def blitz(row, domain):
            called.append("blitz")
            return {"email": "dana.whitfield@acmefreight.example", "source": "blitz"}

        def never(*a):
            raise AssertionError("waterfall did not stop")
        hit, tried = ew.find_email({"domain": "acmefreight.example", "full_name": "Dana Whitfield"},
                                   ["quickenrich", "blitz", "getleads", "prospeo"],
                                   {"quickenrich": no_key, "blitz": blitz, "getleads": never, "prospeo": never})
        self.assertEqual(hit["source"], "blitz")
        self.assertEqual(called, ["quickenrich", "blitz"])

    def test_email_waterfall_dedupes(self):
        ew = load("05-email-waterfall/scripts/email_waterfall.py")
        rows = [{"email": "a@acme.example", "people_source": "clay"}, {"email": "A@acme.example", "people_source": "blitz"}]
        with quiet()[1]:
            found, missing = ew.run(rows, ["blitz"], ignore_existing=False, fns={})
        self.assertEqual(len(found), 1)


# ------------------------------------------------------------------ 06
class TestVerification(unittest.TestCase):
    def setUp(self):
        self.v = load("06-email-verification/scripts/verify_emails.py")

    def run_case(self, mv_result, bb_result=None, allow_risky=False):
        bb_calls = []

        def bb(email, mode):
            bb_calls.append(mode)
            return {"result": bb_result}
        out = self.v.classify("dana@acmefreight.example", lambda e: {"result": mv_result}, bb, allow_risky)
        return out, bb_calls

    def test_ok_is_safe_without_bounceban(self):
        out, calls = self.run_case("ok")
        self.assertTrue(out["safe"])
        self.assertEqual(calls, [])

    def test_catch_all_goes_to_deepverify(self):
        out, calls = self.run_case("catch_all", "deliverable")
        self.assertTrue(out["safe"])
        self.assertEqual(calls, ["deepverify"])

    def test_unknown_goes_to_regular_and_risky_rejected(self):
        out, calls = self.run_case("unknown", "risky")
        self.assertFalse(out["safe"])
        self.assertEqual(calls, ["regular"])
        out, _ = self.run_case("unknown", "risky", allow_risky=True)
        self.assertTrue(out["safe"])

    def test_invalid_rejected(self):
        out, calls = self.run_case("invalid")
        self.assertFalse(out["safe"])
        self.assertEqual(calls, [])

    def test_bounceban_retries_408(self):
        self.v.time.sleep = lambda s: None
        seq = [FakeResponse(408, {"result": "verifying"}), FakeResponse(200, {"result": "deliverable"})]
        patch, calls = fake_requests(lambda m, u, kw: seq.pop(0))
        with patch:
            res = self.v.bounceban("dana@acmefreight.example", "bb_test")
        self.assertEqual(res["result"], "deliverable")
        self.assertEqual(calls[0][2]["headers"]["Authorization"], "bb_test")


# ------------------------------------------------------------------ 07
class TestCopy(unittest.TestCase):
    def setUp(self):
        self.g = load("07-copy-generator/scripts/generate_copy.py")
        self.tdoc = self.g.load_templates()
        self.cfg = json.loads((ROOT / "07-copy-generator/examples/copy_config.json").read_text())

    def test_typos_kept_verbatim(self):
        raw = json.dumps(self.tdoc)
        for typo in ("{{THe offer}}", "Whos", "i've"):
            self.assertIn(typo, raw)
        seq = self.g.build_sequence(self.cfg, self.tdoc)
        bodies = " ".join(v["body_text"] for s in seq["steps"] for v in s["variations"])
        self.assertIn("Whos", bodies)
        self.assertIn("i've", bodies)

    def test_structure_signature_opt_out(self):
        seq = self.g.build_sequence(self.cfg, self.tdoc)
        self.assertEqual([len(s["variations"]) for s in seq["steps"]], [3, 2])
        for s in seq["steps"]:
            for v in s["variations"]:
                self.assertIn(seq["signature"], v["body_text"])
                self.assertTrue(v["body_text"].endswith("If you don't want to hear from me again, just reply no thx!"))

    def test_missing_slot_fails(self):
        cfg = json.loads(json.dumps(self.cfg))
        cfg["slots"]["1A"].pop("CTA")
        with self.assertRaises(self.g.CopyError):
            self.g.build_sequence(cfg, self.tdoc)

    def test_matches_committed_example(self):
        seq = self.g.build_sequence(self.cfg, self.tdoc)
        example = json.loads((ROOT / "07-copy-generator/examples/sequence.json").read_text())
        self.assertEqual(seq["steps"], example["steps"])


# ------------------------------------------------------------------ 08
class TestSpam(unittest.TestCase):
    def setUp(self):
        self.s = load("08-spam-check/scripts/spam_check.py")
        self.seq = json.loads((ROOT / "07-copy-generator/examples/sequence.json").read_text())

    def test_example_passes(self):
        self.assertTrue(self.s.check(self.seq)["passed"])

    def test_spammy_subject_fails(self):
        seq = json.loads(json.dumps(self.seq))
        seq["steps"][0]["variations"][0]["subject"] = "FREE money, act now!!"
        rep = self.s.check(seq)
        self.assertFalse(rep["passed"])
        self.assertGreaterEqual(rep["hit_count"], 2)

    def test_merge_vars_not_scanned_but_values_are(self):
        sc = self.s.Scanner()
        self.assertEqual(sc.scan("{{free_trial}} hi", "x"), [])
        rep = self.s.check(self.seq, [{"email": "a@acme.example", "market_insight": "100% guaranteed results"}])
        self.assertFalse(rep["passed"])


# ------------------------------------------------------------------ 09
class TestCampaign(unittest.TestCase):
    def setUp(self):
        self.c = load("09-plusvibe-campaign/scripts/create_campaign.py")

    def test_daily_limit_is_inboxes_times_15_split_50_50(self):
        self.assertEqual(self.c.daily_limits(6), (90, 45))
        self.assertEqual(self.c.daily_limits(1), (15, 7))

    def test_settings_plain_text_no_tracking(self):
        args = mock.Mock(start_date="2026-11-02", timezone="America/New_York", send_from="09:00",
                         send_to="17:00", schedule_format="list")
        s = self.c.build_settings(["a" * 24], 15, 7, args)
        self.assertEqual(s["send_as_txt"], "yes")
        self.assertEqual(s["is_emailopened_tracking"], "no")
        self.assertEqual(s["send_priority"], 0.5)
        self.assertNotIn("status", s)

    def test_all_columns_become_custom_variables(self):
        row = {"email": "dana@acmefreight.example", "first_name": "Dana", "market_insight": "x", "account_score": "86"}
        lead = self.c.to_plusvibe_lead(row)
        self.assertEqual(lead["email"], "dana@acmefreight.example")
        self.assertEqual(set(lead["custom_variables"]), set(row))

    def test_only_active_google_inboxes(self):
        accs = [{"id": "1", "email": "a@x.example", "provider": "GOOGLE_WORKSPACE", "status": "ACTIVE"},
                {"id": "2", "email": "b@x.example", "provider": "SMTP", "status": "ACTIVE"},
                {"id": "3", "email": "c@x.example", "provider": "GOOGLE_WORKSPACE", "status": "PAUSED"}]
        self.assertEqual([a["id"] for a in self.c.pick_accounts(accs, None)], ["1"])

    def test_sequence_wait_times(self):
        seq = json.loads((ROOT / "07-copy-generator/examples/sequence.json").read_text())
        out = self.c.build_sequences(seq)
        self.assertEqual([len(s["variations"]) for s in out], [3, 2])
        self.assertEqual(out[0]["wait_time"], 3)


# ------------------------------------------------------------------ 10
class TestSpeedToLead(unittest.TestCase):
    def setUp(self):
        self.bh = load("10-speed-to-lead/scripts/business_hours.py")
        self.r = load("10-speed-to-lead/scripts/relay.py")

    def test_plusvibe_hmac_vector(self):
        body = b'{"webhook_event":"SYSTEM_ALERT","alert":"EMAIL_ACCOUNT_DISCONNECTED"}'
        self.assertEqual(self.r.sign("my_webhook_secret", body),
                         "a927cde9781124cf8e28e8e5886e4dff6bf7c792877211fd2a3d6e9d0cc95097")
        self.assertTrue(self.r.verify_signature("my_webhook_secret", body,
                                                "a927cde9781124cf8e28e8e5886e4dff6bf7c792877211fd2a3d6e9d0cc95097"))
        self.assertFalse(self.r.verify_signature("my_webhook_secret", body, "00"))

    def test_ping_times(self):
        t = lambda *a: dt.datetime(*a, tzinfo=NY)  # noqa: E731
        self.assertEqual(self.bh.ping_times(t(2026, 10, 23, 10, 0)), [t(2026, 10, 23, 10, 0), t(2026, 10, 23, 10, 5)])
        self.assertEqual(self.bh.ping_times(t(2026, 10, 23, 18, 0)), [t(2026, 10, 26, 9, 0), t(2026, 10, 26, 9, 5)])
        self.assertEqual(self.bh.ping_times(t(2026, 10, 24, 12, 0))[0], t(2026, 10, 26, 9, 0))
        self.assertEqual(self.bh.ping_times(t(2026, 10, 23, 16, 58)), [t(2026, 10, 23, 16, 58), t(2026, 10, 26, 9, 0)])
        self.assertEqual(self.bh.ping_times(t(2026, 10, 26, 7, 30)), [t(2026, 10, 26, 9, 0), t(2026, 10, 26, 9, 5)])

    def test_normalize_class(self):
        self.assertEqual(self.r.normalize_class("Meeting Request"), "meeting_request")
        self.assertEqual(self.r.normalize_class("Out of office"), "ooo")
        self.assertEqual(self.r.normalize_class("???"), "question")

    def make_app(self, now, dry=False):
        tmp = tempfile.mkdtemp()
        cfg = {"PLUSVIBE_WEBHOOK_SECRET": "whsec", "RELAY_SHARED_SECRET": "relsec",
               "RELAY_PUBLIC_URL": "https://relay.acme.example", "CLAY_WEBHOOK_URL": "https://clay.example/hook",
               "CLAY_WEBHOOK_AUTH_TOKEN": "", "SLACK_BOT_TOKEN": "xoxb-test", "SLACK_FALLBACK_CHANNEL": "",
               "reps": json.loads((ROOT / "10-speed-to-lead/config/reps.example.json").read_text()),
               "routing": {k: v for k, v in json.loads((ROOT / "10-speed-to-lead/config/routing.json").read_text()).items()
                           if not k.startswith("_")}}
        clock = {"now": now}
        app = self.r.Relay(cfg, self.r.Store(Path(tmp) / "state.json"), dry, clock=lambda: clock["now"])
        return app, clock

    def test_full_flow_draft_only_and_two_pings(self):
        now = dt.datetime(2026, 10, 23, 10, 0, tzinfo=NY)
        app, clock = self.make_app(now)
        raw = (ROOT / "10-speed-to-lead/examples/sample_plusvibe_reply.json").read_bytes()
        cb = (ROOT / "10-speed-to-lead/examples/sample_clay_callback.json").read_bytes()

        def handler(method, url, kw):
            self.assertNotIn("/unibox/emails/reply", url)
            if url.startswith("https://slack.com"):
                return FakeResponse(200, {"ok": True})
            return FakeResponse(200, {"status": "success"})
        patch, calls = fake_requests(handler)
        with mock.patch.dict(os.environ, ENV), patch, quiet()[1]:
            self.assertEqual(app.on_plusvibe(raw, "bad")[0], 401)
            code, body = app.on_plusvibe(raw, self.r.sign("whsec", raw))
            self.assertEqual(code, 200)
            self.assertEqual(app.on_plusvibe(raw, self.r.sign("whsec", raw))[1].get("duplicate"), body["reply_id"])
            self.assertEqual(app.on_clay(cb, "wrong")[0], 401)
            code, res = app.on_clay(cb, "relsec")
            self.assertEqual((code, res["classification"], res["draft_saved"], res["pings"]), (200, "meeting_request", True, 2))
            self.assertEqual(app.send_due_pings(), 1)
            clock["now"] = now + dt.timedelta(minutes=5)
            self.assertEqual(app.send_due_pings(), 1)
        urls = [c[1] for c in calls]
        self.assertEqual(urls[0], "https://clay.example/hook")
        self.assertTrue(any(u.endswith("/unibox/emails/save-as-draft") for u in urls))
        draft = next(c for c in calls if c[1].endswith("save-as-draft"))[2]["json"]
        self.assertEqual(draft["parent_message_id"], "000000000000000000msg001")
        self.assertEqual(draft["to"], ["dana.whitfield@acmefreight.example"])
        self.assertEqual(draft["from"], "alex@acmeoutbound.example")
        slack = [c for c in calls if "slack.com" in c[1]]
        self.assertEqual(len(slack), 2)
        self.assertEqual(slack[0][2]["json"]["channel"], "U00000000BB")

    def test_handled_cancels_second_ping(self):
        now = dt.datetime(2026, 10, 23, 10, 0, tzinfo=NY)
        app, clock = self.make_app(now, dry=True)
        raw = (ROOT / "10-speed-to-lead/examples/sample_plusvibe_reply.json").read_bytes()
        cb = (ROOT / "10-speed-to-lead/examples/sample_clay_callback.json").read_bytes()
        with quiet()[1]:
            app.on_plusvibe(raw, self.r.sign("whsec", raw))
            app.on_clay(cb, "relsec")
            self.assertEqual(app.send_due_pings(), 1)
            rid = "000000000000000000msg001"
            self.assertEqual(app.on_handled({"reply_id": [rid], "sig": ["nope"]})[0], 401)
            self.assertEqual(app.on_handled({"reply_id": [rid], "sig": [self.r.sign("relsec", rid.encode())]})[0], 200)
            clock["now"] = now + dt.timedelta(minutes=6)
            self.assertEqual(app.send_due_pings(), 0)

    def test_after_hours_queued_for_next_morning(self):
        now = dt.datetime(2026, 10, 23, 19, 0, tzinfo=NY)  # Friday evening
        app, clock = self.make_app(now, dry=True)
        raw = (ROOT / "10-speed-to-lead/examples/sample_plusvibe_reply.json").read_bytes()
        cb = (ROOT / "10-speed-to-lead/examples/sample_clay_callback.json").read_bytes()
        with quiet()[1]:
            app.on_plusvibe(raw, self.r.sign("whsec", raw))
            app.on_clay(cb, "relsec")
            self.assertEqual(app.send_due_pings(), 0)
            clock["now"] = dt.datetime(2026, 10, 26, 9, 0, tzinfo=NY)
            self.assertEqual(app.send_due_pings(), 1)

    def test_not_interested_no_draft_no_ping(self):
        now = dt.datetime(2026, 10, 23, 10, 0, tzinfo=NY)
        app, _ = self.make_app(now, dry=True)
        raw = (ROOT / "10-speed-to-lead/examples/sample_plusvibe_reply.json").read_bytes()
        with quiet()[1]:
            app.on_plusvibe(raw, self.r.sign("whsec", raw))
            code, res = app.on_clay(json.dumps({"reply_id": "000000000000000000msg001", "classification": "not interested",
                                                "draft_reply": "x"}).encode(), "relsec")
        self.assertEqual((res["draft_saved"], res["pings"]), (False, 0))


# ------------------------------------------------------------------ 11
class TestQA(unittest.TestCase):
    def setUp(self):
        self.q = load("11-qa/scripts/qa.py")
        self.seq = json.loads((ROOT / "07-copy-generator/examples/sequence.json").read_text())

    def test_duplicates_and_unverified_fail(self):
        leads = [{"email": "a@acme.example", "verify_mv": "ok"}, {"email": "A@acme.example", "verify_mv": "ok"}]
        self.assertFalse(self.q.check_unique(leads)["passed"])
        self.assertFalse(self.q.check_verified([{"email": "b@acme.example", "verify_mv": "catch_all"}], set(), False)["passed"])
        self.assertTrue(self.q.check_verified([{"email": "b@acme.example", "verify_mv": "catch_all", "verify_bb": "deliverable"}],
                                              set(), False)["passed"])

    def test_missing_merge_var_fails(self):
        lead = {"email": "a@acme.example", "first_name": "Dana", "company_name": "Acme"}
        self.assertFalse(self.q.check_merge_vars(self.seq, [lead])["passed"])  # no market_insight
        lead["market_insight"] = "saw the new depot"
        self.assertTrue(self.q.check_merge_vars(self.seq, [lead])["passed"])

    def test_missing_opt_out_fails(self):
        seq = json.loads(json.dumps(self.seq))
        v = seq["steps"][1]["variations"][1]
        v["body_text"] = v["body_text"].replace(seq["opt_out"], "")
        self.assertFalse(self.q.check_signature(seq, None)["passed"])
        self.assertTrue(self.q.check_signature(self.seq, None)["passed"])

    def test_settings(self):
        inboxes = ["a@x.example", "b@x.example"]
        good = {"daily_limit": 30, "daily_limit_new_lead": 15, "send_priority": 0.5, "send_as_txt": 1, "is_emailopened_tracking": 0}
        self.assertTrue(self.q.check_settings(good, inboxes, set(inboxes), 15)["passed"])
        self.assertFalse(self.q.check_settings({**good, "daily_limit": 50}, inboxes, set(inboxes), 15)["passed"])
        self.assertFalse(self.q.check_settings({**good, "send_as_txt": 0}, inboxes, set(inboxes), 15)["passed"])
        self.assertFalse(self.q.check_settings(good, inboxes, set(inboxes) | {"c@x.example"}, 15)["passed"])

    def test_spam_report_must_match_sequence(self):
        with tempfile.TemporaryDirectory() as d:
            seq_p = Path(d) / "sequence.json"
            seq_p.write_text(json.dumps(self.seq))
            rep_p = Path(d) / "spam_report.json"
            rep_p.write_text(json.dumps({"passed": True, "sequence_sha256": "old"}))
            self.assertFalse(self.q.check_spam(rep_p, seq_p)["passed"])
            rep_p.write_text(json.dumps({"passed": True, "sequence_sha256": hashlib.sha256(seq_p.read_bytes()).hexdigest()}))
            self.assertTrue(self.q.check_spam(rep_p, seq_p)["passed"])

    def test_webhook(self):
        sess = mock.Mock()
        sess.get.return_value = FakeResponse(200, {"ok": True})
        self.assertTrue(self.q.check_webhook("https://relay.acme.example", None, session=sess)["passed"])
        self.assertFalse(self.q.check_webhook("https://relay.acme.example", [{"url": "https://other.example"}], session=sess)["passed"])
        self.assertTrue(self.q.check_webhook("https://relay.acme.example", [{"url": "https://relay.acme.example/plusvibe"}],
                                             session=sess)["passed"])
        self.assertFalse(self.q.check_webhook(None)["passed"])

    def test_launch_requires_live(self):
        with quiet()[0], quiet()[1], self.assertRaises(SystemExit):
            self.q.main(["--launch"])


if __name__ == "__main__":
    unittest.main()
