---
name: plusvibe-campaign
description: Create the PlusVibe campaign from sequence.json, connect every active Google inbox, set daily limit = inboxes x 15 with a 50/50 new vs follow-up split, plain text and no tracking, and upload leads with every column as a custom variable. Never launches.
---

# 09 PlusVibe campaign

## Purpose
Turn the checked copy and verified leads into a ready-to-launch PlusVibe campaign with the same settings every time.

## Inputs
- `sequence.json` (skill 07) and a passing `spam_report.json` (skill 08). The script refuses to run without a passing report.
- `verified_leads.csv` (skill 06).
- Optional `inboxes_connected.csv` (skill 01) to limit the campaign to the inboxes you just set up. Without it, every ACTIVE Google inbox in the workspace is used.

## Outputs
- A PlusVibe campaign (not launched).
- `campaign_state.json`: campaign id, inbox emails and ids, daily limit, lead counts. Skill 11 reads this.

## Env vars
| Var | Where to get it |
|---|---|
| `PLUSVIBE_API_KEY` | https://app.plusvibe.ai/v2/settings/api-access |
| `PLUSVIBE_WORKSPACE_ID` | Same page (workspace id) |

## Settings it applies
| Setting | Value | API field |
|---|---|---|
| Daily limit | ACTIVE Google inboxes x 15 | `schedules.daily_limit` |
| New vs follow-up | 50/50 | `send_priority: 0.5`, `daily_limit_new_lead` = half the limit |
| Format | Plain text | `send_as_txt: "yes"` |
| Tracking | Off | `is_emailopened_tracking: "no"` |
| Unsubscribe link | Off (the opt-out line is in the copy) | `is_unsubscribed_link: "no"` |
| Stop on reply | On | `stop_on_lead_replied: "yes"` |
| Schedule | Mon-Fri 09:00-17:00 America/New_York | `schedules.days/timing/timezone` |
| Inboxes | Every connected ACTIVE Google inbox | `email_accounts` |
| Sequence | Step 1 = Email 1 A/B/C, step 2 = Email 2 A/B | `sequences` |
| Leads | All CSV columns as custom variables | `/lead/add` `custom_variables` |

Calls: `POST /campaign/add/campaign`, `PATCH /campaign/update/campaign`, `POST /lead/add`, and read-only `GET /account/list`. Base `https://api.plusvibe.ai/api/v1`, header `x-api-key`.

## Steps (agent run instructions)
1. Dry run. This prints every payload. With no keys set, it uses the inboxes CSV:
   ```bash
   python 09-plusvibe-campaign/scripts/create_campaign.py --name "Acme Q3 fleets" \
     --sequence sequence.json --leads verified_leads.csv --spam-report spam_report.json \
     --inboxes inboxes_connected.csv --dry-run
   ```
2. Check the inbox count, the daily limit (= inboxes x 15) and the first lead's custom variables.
3. Run it for real (same command without `--dry-run`). This creates the campaign but does not launch it.
4. To re-apply settings to an existing campaign, add `--campaign-id <id>`.

## Open TODOs
- `schedules`: the API schema says object, the official example sends a list. The default is `list`. If the API rejects it, use `--schedule-format object`.
- No documented max leads per `/lead/add` call; the script sends batches of 100.

## Handoff
`campaign_state.json` -> **10-speed-to-lead** (webhook on the campaign) and **11-qa** (checks, then launch).
