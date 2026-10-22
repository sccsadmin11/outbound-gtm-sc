---
name: launch-qa
description: Run the pre-launch checklist on a PlusVibe campaign (clean verified leads, filled merge vars, signature and opt-out, spam check, sending settings, reply webhook) and write a pass/fail report. Any failure blocks the launch.
---

# 11 QA

## Purpose
One last gate before anything sends. The campaign from skill 09 stays paused until every check here passes. Only this skill can launch it, and only with `--launch`.

## Checks
| Check | Passes when |
|---|---|
| leads_unique | No email appears twice |
| leads_verified | Every email passed skill 06 (`verify_mv=ok` or `verify_bb=deliverable`) and is not in `rejected_emails.csv` |
| merge_vars_filled | Every `{{var}}` in every subject and body has a value for every lead. No raw template slot is left |
| signature_opt_out | The signature and the opt-out line are in every email (text and HTML) |
| spam_check_passed | `spam_report.json` passed and its hash matches the current `sequence.json` |
| plusvibe_settings | Daily limit = connected inboxes x 15, send_priority 0.5 (50/50 new vs follow-up), plain text on, open tracking off, every ACTIVE Google inbox connected |
| webhook_reachable | The relay from skill 10 answers `GET /health`. In `--live` mode a PlusVibe webhook must also point at `<relay>/plusvibe` |

## Inputs
- `verified_leads.csv` (06 or the copy of it used in 07), `rejected_emails.csv` (06)
- `sequence.json` (07), `spam_report.json` (08), `campaign_state.json` (09)
- `inboxes_connected.csv` (01), relay URL (10)

## Outputs
- `qa_report.json` and `qa_report.md` (see `examples/qa_report.md` and `examples/qa_report_failed.md`).
- Exit code 0 = pass, 1 = fail.

## Env vars
Only for `--live`: `PLUSVIBE_API_KEY`, `PLUSVIBE_WORKSPACE_ID` (https://app.plusvibe.ai/v2/settings/api-access). Live mode only makes GET calls, except `--launch`.

## Steps (agent run instructions)
1. Offline run on local files:
   ```bash
   python 11-qa/scripts/qa.py --leads verified_leads.csv --rejected rejected_emails.csv \
     --sequence sequence.json --spam-report spam_report.json --campaign-state campaign_state.json \
     --inboxes inboxes_connected.csv --relay-url https://relay.yourdomain.example
   ```
2. Live read-back from PlusVibe (read-only):
   ```bash
   python 11-qa/scripts/qa.py ...same flags... --live
   ```
3. If a check fails, fix it in the skill that owns it (06 leads, 07 copy, 08 spam, 09 settings, 10 webhook), then run QA again. Never edit the report.
4. Show the user `qa_report.md`. Launch only when they say so:
   ```bash
   python 11-qa/scripts/qa.py ...same flags... --live --launch --dry-run   # shows the launch call
   python 11-qa/scripts/qa.py ...same flags... --live --launch             # starts sending
   ```

## Notes
- The opt-out line defaults to the one in `sequence.json`. Pass `--opt-out` to enforce a specific line.
- `{{sender_first_name}}` is filled by PlusVibe from the sending inbox, so it is not required in the lead rows.
- TODO: the `/hook/list` response shape is not documented in detail. QA looks for the relay URL anywhere in the response.

## Handoff
PASS -> campaign launched -> replies flow into **10-speed-to-lead**. FAIL -> back to the skill named in the report.
