---
name: speed-to-lead
description: Route every PlusVibe reply through a Clay webhook table that classifies it and writes a reply, save that reply as a DRAFT in PlusVibe (never auto-send), and ping the assigned rep in Slack at +0 and +5 minutes during 9-17 New York business hours.
---

# 10 Speed to lead

## Purpose
Replies go cold fast. This skill gets a classified reply, a ready draft and a Slack ping in front of the right rep within minutes, while a human still sends every email.

```
PlusVibe reply webhook -> relay /plusvibe (HMAC check)
  -> Clay webhook table: classify -> draft reply -> HTTP POST back
  -> relay /clay-callback -> PlusVibe save-as-draft (never send)
  -> Slack ping to the rep at +0 and +5 min (Mon-Fri 9-17 America/New_York)
```

**How we run it: we run this on Hermes by Nous Research.** Any always-on box that can take HTTPS traffic works (a small VPS, Fly, Railway, a Cloudflare Tunnel to a home server).

## Reply classes
| Class | Draft saved | Slack pings |
|---|---|---|
| interested | yes | 2 |
| meeting_request | yes | 2 |
| question | yes | 2 |
| referral | yes | 2 |
| not_now | yes | 1 |
| not_interested | no | 0 |
| ooo | no | 0 |
| unsubscribe | no | 1 (so someone confirms the lead is blocklisted) |

Change this in `config/routing.json`. An unknown label from Clay is treated as `question`, so a human always sees it.

## Ping timing
- Reply classified during Mon-Fri 09:00-17:00 America/New_York: ping at +0, second ping at +5 min unless the rep clicked **Mark handled**.
- Outside those hours: queued for 09:00 and 09:05 the next business day. A ping that would land after 17:00 moves to 09:00 the next business day. US holidays are not skipped.

## Inputs
- `campaign_state.json` from skill 09 (optional, limits the webhook to that campaign).
- `config/reps.json` (copy `config/reps.example.json`): who gets pinged, matched by the inbox that got the reply, then by campaign, then the default.

## Outputs
- Drafts in PlusVibe Unibox. Slack DMs to reps.
- `relay_state.json`: replies, classes and the ping queue. It survives restarts.

## Env vars
| Var | Where to get it |
|---|---|
| `PLUSVIBE_API_KEY`, `PLUSVIBE_WORKSPACE_ID` | https://app.plusvibe.ai/v2/settings/api-access |
| `PLUSVIBE_WEBHOOK_SECRET` | Make one up (`python -c "import secrets;print(secrets.token_hex(32))"`). Used to sign webhooks |
| `RELAY_SHARED_SECRET` | Make one up. Clay sends it back as `X-Relay-Secret`; it also signs the Mark handled links |
| `RELAY_PUBLIC_URL` | The public HTTPS URL of your relay, e.g. `https://relay.yourdomain.example` |
| `CLAY_WEBHOOK_URL` | Clay table -> Webhook source -> copy URL |
| `CLAY_WEBHOOK_AUTH_TOKEN` | Optional, from the Clay webhook settings |
| `SLACK_BOT_TOKEN` | https://api.slack.com/apps -> your app -> OAuth & Permissions -> Bot token (`xoxb-...`), scope `chat:write` |
| `SLACK_FALLBACK_CHANNEL` | Optional channel ID used when a rep has no Slack ID |

## Steps (agent run instructions)
1. Set up Clay with `clay/clay_setup.md` (webhook table, two AI columns with the prompts in `clay/prompts/`, one HTTP API column).
2. Copy `config/reps.example.json` to `config/reps.json` and fill in the Slack member IDs.
3. Start the relay in dry-run mode and replay the sample reply:
   ```bash
   python 10-speed-to-lead/scripts/relay.py --dry-run --port 8080
   SIG=$(python -c "import hmac,hashlib,os;print(hmac.new(os.environ['PLUSVIBE_WEBHOOK_SECRET'].encode(),open('10-speed-to-lead/examples/sample_plusvibe_reply.json','rb').read(),hashlib.sha256).hexdigest())")
   curl -X POST localhost:8080/plusvibe -H "Signature: $SIG" --data-binary @10-speed-to-lead/examples/sample_plusvibe_reply.json
   curl -X POST localhost:8080/clay-callback -H "X-Relay-Secret: $RELAY_SHARED_SECRET" --data-binary @10-speed-to-lead/examples/sample_clay_callback.json
   ```
4. Deploy it behind HTTPS at `RELAY_PUBLIC_URL`, without `--dry-run`. Check `GET /health`.
5. Register the PlusVibe webhook (dry run first):
   ```bash
   python 10-speed-to-lead/scripts/register_webhook.py --campaign-state campaign_state.json --dry-run
   python 10-speed-to-lead/scripts/register_webhook.py --campaign-state campaign_state.json
   ```
6. Reply to one of your own campaign emails from a test address and watch for the draft and the ping.

## Safety
- The relay only calls `POST /unibox/emails/save-as-draft`. It has no code path to PlusVibe's send/reply endpoint.
- Webhooks without a valid `Signature` (HMAC-SHA256 of the raw body with `PLUSVIBE_WEBHOOK_SECRET`) get a 401.
- Request logs show paths only, never query strings or secrets.

## Open TODOs
- `parent_message_id` for the draft uses the webhook's `last_email_id`. PlusVibe documents that as the reply-to id; confirm it is the same Unibox email id.
- Clay webhook auth header name (`x-clay-webhook-auth`).

## Handoff
Relay URL + webhook registered -> **11-qa** checks `GET /health` and that a PlusVibe webhook points at it.
