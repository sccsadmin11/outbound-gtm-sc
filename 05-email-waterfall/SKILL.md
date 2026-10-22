---
name: email-waterfall
description: Find a work email for every person in people.csv with a waterfall (QuickEnrich -> BlitzAPI -> GetLeads -> Prospeo) that stops at the first email found.
---

# 05 Email waterfall

## Purpose
Get a work email for every person from skill 04 at the lowest cost: try the cheapest or best-hit-rate provider first and only fall through when it misses.

## Inputs
- `people.csv` from skill 04. Rows that already have an email (GetLeads returns one) are kept and not looked up again, unless you pass `--ignore-existing`.

## Outputs
- `leads_with_email.csv`: every column from `people.csv` plus `email`, `email_status` (what the provider said, if anything) and `email_source`. One row per unique email.
- `emails_not_found.csv`: people with no email, plus what each provider returned.

## Env vars
| Var | Where to get it |
|---|---|
| `QUICKENRICH_API_KEY` | QuickEnrich dashboard -> API (docs: https://app.quickenrich.io/docs) |
| `BLITZ_API_KEY` | BlitzAPI dashboard: https://app.blitz-api.ai |
| `GETLEADS_API_KEY` | https://app.getleads.io/api-keys |
| `PROSPEO_API_KEY` | Prospeo dashboard -> API (docs: https://prospeo.io/api-docs) |

A provider with no key is skipped, not fatal.

## Waterfall
| Step | Provider | Call | Needs |
|---|---|---|---|
| 1 | QuickEnrich | `GET /api/employees/search` | `linkedin_url`, or `company_url` + first + last name |
| 2 | BlitzAPI | `POST /v2/enrichment/email` | `person_linkedin_url` |
| 3 | GetLeads | `POST /api/v1/enrich/from-linkedin` or `/enrich/from-person` | LinkedIn URL, or name + `email_domain` |
| 4 | Prospeo | `POST https://api.prospeo.io/enrich-person` with `only_verified_email: true` | LinkedIn URL or name + company website |

## Steps (agent run instructions)
1. Preview how many lookups will run:
   ```bash
   python 05-email-waterfall/scripts/email_waterfall.py --people people.csv --dry-run
   ```
2. Run:
   ```bash
   python 05-email-waterfall/scripts/email_waterfall.py --people people.csv --out leads_with_email.csv
   ```
3. Report the found / not-found counts and which provider found what (`email_source`).

Provider "found" is not "verified". Always run skill 06 next.

## Open TODOs
- QuickEnrich `/api/employees/search`: on a miss the docs show an empty `data`. The script treats an empty list, missing object or 404 as a miss.

## Handoff
`leads_with_email.csv` -> **06-email-verification**.
