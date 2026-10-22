---
name: email-verification
description: Verify every email with MillionVerifier, send catch-all and unknown results to BounceBan, and output only safe-to-send emails in verified_leads.csv.
---

# 06 Email verification

## Purpose
Protect the new inboxes. Bounces burn domain reputation fast, so only emails that pass verification move on.

## Inputs
- `leads_with_email.csv` from skill 05.

## Outputs
- `verified_leads.csv`: safe-to-send rows only, plus `verify_mv`, `verify_bb`, `verify_reason`.
- `rejected_emails.csv`: everything else, with the reason.

Duplicate emails are removed before any credit is spent.

## Env vars
| Var | Where to get it |
|---|---|
| `MILLIONVERIFIER_API_KEY` | https://app.millionverifier.com/api |
| `BOUNCEBAN_API_KEY` | https://bounceban.com/app/api/settings |

## Rules
| MillionVerifier result | Next | Safe? |
|---|---|---|
| `ok` | none | yes |
| `catch_all` | BounceBan `mode=deepverify` | only if BounceBan says `deliverable` |
| `unknown` | BounceBan `mode=regular` | only if BounceBan says `deliverable` |
| `invalid`, `disposable` | none | no |

`--allow-risky` also keeps BounceBan `risky`. Off by default.

## Calls
- MillionVerifier: `GET https://api.millionverifier.com/api/v3/?api=KEY&email=...&timeout=10`
- BounceBan: `GET https://api-waterfall.bounceban.com/v1/verify/single?email=...&mode=...` with header `Authorization: KEY`. A `408` means it is still verifying; the script re-sends the same request, which is free within 30 minutes.

## Steps (agent run instructions)
1. Count first:
   ```bash
   python 06-email-verification/scripts/verify_emails.py --leads leads_with_email.csv --dry-run
   ```
2. Try the logic for free with MillionVerifier's demo keys (fake results, no credits):
   ```bash
   MILLIONVERIFIER_API_KEY=API_KEY_FOR_OK python 06-email-verification/scripts/verify_emails.py --leads 05-email-waterfall/examples/leads_with_email.csv --out /tmp/v.csv
   ```
3. Run for real:
   ```bash
   python 06-email-verification/scripts/verify_emails.py --leads leads_with_email.csv
   ```
4. Report safe vs rejected counts and the top rejection reasons.

## Handoff
`verified_leads.csv` -> **07-copy-generator**. Skill 11 re-checks that every lead in the campaign is in this file.
