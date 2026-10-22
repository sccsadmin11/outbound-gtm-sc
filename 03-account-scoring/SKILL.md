---
name: account-scoring
description: Build a target account list from the ICP in strategy.json with DiscoLike only, qualify each account yes/no with DiscoLike's ICP check, score it 0-100 and write qualified_accounts.csv with score and reason.
---

# 03 Account scoring (DiscoLike only)

## Purpose
Turn the ICP into a ranked list of companies that actually fit, with a short reason for every yes and no. This skill uses DiscoLike and nothing else.

## Inputs
- `strategy.json` from skill 02 (`icp.icp_text`, `negate_icp_text`, `countries`, `employee_range`, `lookalike_domains`, `exclude`).

## Outputs
- `qualified_accounts.csv`: only qualified accounts, sorted by score.
- `scored_accounts.csv`: every account with score and reason (useful to tune the ICP).

Columns: `domain, company_name, qualified, score, reason, similarity, icp_fit, icp_confidence, footprint, employees, industry, linkedin_url, description`.

## Env vars
| Var | Where to get it |
|---|---|
| `DISCOLIKE_API_KEY` | DiscoLike app -> Account -> API keys (https://discolike.com) |

## How it works
1. `GET /v1/discover` with `icp_text`, `negate_icp_text`, `country`, `employee_range`, lookalike `domain`s, `exclude_domain` (your own domain is always excluded) and `exclude_leadgen=true`.
2. `POST /v1/validate/icp` with `integration_id: "native-icp"` on the returned domains, then poll `GET /v1/discogen/status/{task_id}`. Each domain gets Fit yes/no, a confidence and a reasoning line.
3. Score 0-100 = 55% similarity + 35% ICP confidence + 10% digital footprint (capped at 400 of 800). Qualified = Fit yes AND score >= `--min-score` (default 60).

## Steps (agent run instructions)
1. Preview the query, no API call:
   ```bash
   python 03-account-scoring/scripts/score_accounts.py --strategy strategy.json --dry-run
   ```
2. Check the market size:
   ```bash
   python 03-account-scoring/scripts/score_accounts.py --strategy strategy.json --count-only
   ```
3. Run it (start small, then raise `--max-records`):
   ```bash
   python 03-account-scoring/scripts/score_accounts.py --strategy strategy.json --max-records 200 --min-score 60
   ```
4. Read 10 rows of `scored_accounts.csv` with the user. If good companies are scored "no", tighten `icp_text` or `negate_icp_text` in `strategy.json` and re-run.

## Notes
- DiscoLike runs at most 3 ICP validation tasks at once. The script waits and retries on 429.
- `--skip-validate` scores on similarity + footprint only. Cheaper, less accurate.

## Open TODOs
- The `/discogen/status` response schema is not published. The parser reads `results` as a dict or list and finds the Fit / Confidence / Reasoning columns by name, case-insensitive.
- Max domains per `/validate/icp` call is not documented. The script sends batches of 100.

## Handoff
`qualified_accounts.csv` -> **04-people-waterfall**.
