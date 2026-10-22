---
name: people-waterfall
description: Find the right people at every qualified account with a waterfall (Clay CLI -> QuickEnrich -> BlitzAPI -> GetLeads) that stops at the first provider with a hit for each account and persona.
---

# 04 People waterfall

## Purpose
For each qualified account and each persona in `strategy.json`, find the person to email. Providers run in order and the waterfall stops at the first hit, so you only pay the next provider when the one before it came up empty.

## Inputs
- `qualified_accounts.csv` from skill 03 (`domain`, `company_name`, `linkedin_url`, `score`).
- `strategy.json` from skill 02 (`personas[].titles`, `personas[].exclude_titles`).

## Outputs
- `people.csv`: `domain, company_name, company_linkedin_url, persona, first_name, last_name, full_name, title, linkedin_url, email, email_status, people_source, account_score`.
- `people_not_found.csv`: account/persona pairs no provider could fill, with what each provider returned.

Some providers (GetLeads, sometimes QuickEnrich) return an email along with the person. Skill 05 keeps it and skips the lookup for that row.

## Env vars
| Var | Where to get it |
|---|---|
| (Clay) | No env var. Install the CLI and run `clay login` (see below) |
| `QUICKENRICH_API_KEY` | QuickEnrich dashboard -> API (docs: https://app.quickenrich.io/docs) |
| `BLITZ_API_KEY` | BlitzAPI dashboard: https://app.blitz-api.ai |
| `GETLEADS_API_KEY` | https://app.getleads.io/api-keys |

A provider with no key is skipped, not fatal.

## Waterfall
| Step | Provider | Call |
|---|---|---|
| 1 | Clay CLI | `clay searches query-mode create --query ...` then `clay searches query-mode run <id>` |
| 2 | QuickEnrich | `GET /api/employees/dataset-search?company_url=&title=` |
| 3 | BlitzAPI | `POST /v2/enrichment/domain-to-linkedin` then `POST /v2/search/waterfall-icp-keyword` |
| 4 | GetLeads | `POST /api/v1/contacts/lookup/colleagues` with `job_titles` |

## Steps (agent run instructions)
1. Install the Clay CLI from Clay's agent plugins repo (https://github.com/clay-run/agent-plugins) and log in:
   ```bash
   git clone https://github.com/clay-run/agent-plugins && bash agent-plugins/clay/scripts/install-cli.sh --method native
   clay login        # or: clay login --device
   clay whoami
   ```
2. Check the Clay query grammar once and adjust the template if needed:
   ```bash
   clay searches query-mode reference | jq -r '.reference' > ./clay-search-reference.md
   grep -n '^##' ./clay-search-reference.md
   ```
3. Preview:
   ```bash
   python 04-people-waterfall/scripts/people_waterfall.py --accounts qualified_accounts.csv --strategy strategy.json --dry-run
   ```
4. Test on 3 accounts, then run everything:
   ```bash
   python 04-people-waterfall/scripts/people_waterfall.py --limit-accounts 3
   python 04-people-waterfall/scripts/people_waterfall.py --per-persona 1
   ```
   Change the order with `--order quickenrich blitz getleads` (for example, without Clay).
5. Spot check 10 rows: right company, current role, title fits the persona.

## Open TODOs
- Clay: the default query uses `company.domain` inside `experiences.any(...)`. That field appears in Clay's audience query docs; confirm it in `clay-search-reference.md`, or pass `--clay-query-template`. The Clay result field for the LinkedIn URL (`linkedin_url` vs `profile_url`) is read defensively.

## Handoff
`people.csv` -> **05-email-waterfall**.
