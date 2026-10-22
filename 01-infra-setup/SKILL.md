---
name: infra-setup
description: Check domain availability and price on Porkbun (no purchase unless you pass --confirm-purchase), point domains at Zapmail, create Google Workspace inboxes through the Zapmail API, and get them into PlusVibe.
---

# 01 Infra setup

## Purpose
Get sending infrastructure ready: secondary domains, Google Workspace inboxes on each domain with DNS handled, and those inboxes connected in PlusVibe.

## Inputs
- `domains.txt`: candidate domains, one per line (see `examples/domains.txt`).
- The example files use fake `.example` domains. Use real candidate names (for example `.com`) on a live run.
- `senders.csv`: `first_name,last_name` of the people the inboxes are named after.
- How many inboxes per domain (1 to 5, Zapmail's max is 5).

## Outputs
- `domain_check.csv`: availability, first-year price, renewal price, premium flag.
- `inbox_plan.csv`: every inbox to create (domain, name, username, email).
- `domain_connect.csv`: Zapmail connection status per domain.
- `inboxes.csv`: created mailboxes (no passwords, ever).
- `inboxes_connected.csv`: which inboxes PlusVibe sees as connected and active. Skill 09 uses it.

## Env vars
| Var | Where to get it |
|---|---|
| `PORKBUN_API_KEY`, `PORKBUN_SECRET_API_KEY` | https://porkbun.com/account/api (also turn on API access per domain) |
| `ZAPMAIL_API_KEY` | Zapmail app -> Settings -> API |
| `ZAPMAIL_WORKSPACE_KEY` | Optional. Only if you use more than one Zapmail workspace |
| `PLUSVIBE_API_KEY`, `PLUSVIBE_WORKSPACE_ID` | https://app.plusvibe.ai/v2/settings/api-access |

## Money warning
- `porkbun_domains.py check` is read only. It never buys.
- `porkbun_domains.py buy` without `--confirm-purchase` only runs Porkbun's `dryRun: true` preview. No order, no charge.
- `porkbun_domains.py buy --confirm-purchase` SPENDS REAL MONEY from your Porkbun account credit. It refuses premium domains, refuses anything above `--max-cost-cents` (default 1500 = $15), and refuses if Porkbun's preview cost does not match the checked price.
- `zapmail_inboxes.py create-mailboxes` uses mailbox slots on your Zapmail plan. Run it with `--dry-run` first.

## Steps (agent run instructions)
1. Check domains (read only):
   ```bash
   python 01-infra-setup/scripts/porkbun_domains.py check --file domains.txt --out domain_check.csv
   # Try it with no keys against Porkbun's mock server:
   python 01-infra-setup/scripts/porkbun_domains.py check --mock --domains acmeoutbound.example
   ```
   Show the user the CSV. Pick domains with `available=yes`, `premium=no`.
2. Buy (only if the user explicitly says so):
   ```bash
   python 01-infra-setup/scripts/porkbun_domains.py buy --domains acmeoutbound.example            # preview only
   python 01-infra-setup/scripts/porkbun_domains.py buy --domains acmeoutbound.example --confirm-purchase   # costs money
   ```
   Already own domains elsewhere? Skip this step.
3. Point nameservers at Zapmail (Porkbun domains):
   ```bash
   python 01-infra-setup/scripts/porkbun_domains.py set-ns --file domains.txt --dry-run
   python 01-infra-setup/scripts/porkbun_domains.py set-ns --file domains.txt
   ```
   Default nameservers: `pns61.cloudns.net pns62.cloudns.com pns63.cloudns.net pns64.cloudns.uk`. Zapmail then creates MX, SPF, DKIM and DMARC for you.
4. Plan inboxes (local):
   ```bash
   python 01-infra-setup/scripts/zapmail_inboxes.py plan --domains-csv domain_check.csv --senders senders.csv --per-domain 3
   ```
5. Connect domains to Zapmail and wait (nameserver changes can take a while):
   ```bash
   python 01-infra-setup/scripts/zapmail_inboxes.py connect-domains --plan inbox_plan.csv --dry-run
   python 01-infra-setup/scripts/zapmail_inboxes.py connect-domains --plan inbox_plan.csv
   ```
   `NS_NOT_CHANGED` means the registrar change has not propagated. Re-run later.
6. Create Google Workspace mailboxes:
   ```bash
   python 01-infra-setup/scripts/zapmail_inboxes.py create-mailboxes --plan inbox_plan.csv --dry-run
   python 01-infra-setup/scripts/zapmail_inboxes.py create-mailboxes --plan inbox_plan.csv
   python 01-infra-setup/scripts/zapmail_inboxes.py list --out inboxes.csv
   ```
7. Get them into PlusVibe:
   ```bash
   python 01-infra-setup/scripts/zapmail_inboxes.py export-plusvibe --inboxes inboxes.csv --dry-run
   python 01-infra-setup/scripts/zapmail_inboxes.py export-plusvibe --inboxes inboxes.csv
   ```
   If Zapmail rejects the `PLUSVIBE` app value, use Zapmail's built-in PlusVibe export in the UI:
   https://help.zapmail.ai/en/articles/12122032-connect-your-mailboxes-to-plusvibe-everything-you-need-to-know
8. Confirm in PlusVibe (read only, exits 1 if any inbox is missing):
   ```bash
   python 01-infra-setup/scripts/plusvibe_inboxes.py --inboxes inboxes.csv --out inboxes_connected.csv
   ```
9. Let inboxes warm up in PlusVibe before launch.

## Open TODOs
- Zapmail's export endpoint documents apps like `INSTANTLY` and `SMARTLEAD` but not `PLUSVIBE`. The script tries `PLUSVIBE`; the UI export is the fallback.
- Porkbun `cost` is computed as price x minimum years. The dry-run preview must match or the script refuses to buy.

## Handoff
`inboxes_connected.csv` -> **09-plusvibe-campaign** (daily limit = active Google inboxes x 15) and **11-qa**. Next skill to run: **02-gtm-strategy**.
