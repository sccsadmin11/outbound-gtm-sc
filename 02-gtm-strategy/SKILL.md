---
name: gtm-strategy
description: Turn a company URL into a cold outbound strategy (core offer, ICP, personas, pains, 3 front-end offers for cold traffic, proof points) saved as strategy.json and strategy.md.
---

# 02 GTM strategy

## Purpose
Decide who to email and what to offer them before spending a single credit on data. Every later skill reads `strategy.json`.

## Inputs
- A company URL (yours, or the client's you are running outbound for).
- Optional: notes from the user on pricing, best customers and results they can prove.

## Outputs
- `site_notes.md`: readable text pulled from the site.
- `strategy.json`: structured strategy (schema in `templates/strategy.template.json`).
- `strategy.md`: the same strategy, readable, for the user to approve.

## Env vars
None. `fetch_site.py` only reads public web pages.

## Steps (agent run instructions)
1. Pull the site:
   ```bash
   python 02-gtm-strategy/scripts/fetch_site.py https://acme.example --out site_notes.md
   ```
2. Read `templates/prompt.md` and follow it. Use `site_notes.md` plus anything the user tells you. Write `strategy.json`.
3. Validate and render:
   ```bash
   python 02-gtm-strategy/scripts/render_strategy.py --in strategy.json --out strategy.md
   ```
   It fails if a field is missing, if there are not exactly 3 front-end offers, or if a proof point has no source.
4. Show `strategy.md` to the user. Edit until they approve.

## Front-end offers
The core offer is usually too big for a cold email. Split it into 3 small pieces a stranger can say yes to fast: a teardown, an audit, a sample, a calculator, a checklist. Each one maps back to a part of the core offer, so a yes leads into the real sale.

## Rules
- No invented stats, customers or results. A proof point without a source gets cut.
- `icp.icp_text` is one plain sentence. DiscoLike matches it against company websites in skill 03.
- `personas[].titles` are the job titles skill 04 searches for.

## Handoff
`strategy.json` -> **03-account-scoring** (ICP), **04-people-waterfall** (personas), **07-copy-generator** (offers, pains, proof). See `examples/strategy.json` for a filled example.
