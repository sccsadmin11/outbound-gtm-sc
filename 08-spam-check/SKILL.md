---
name: spam-check
description: Scan the generated sequence (and per-lead merge var values) for spam trigger words and risky formatting, suggest replacements, and fail until no hits remain.
---

# 08 Spam check

## Purpose
Catch spam trigger words before the campaign goes live. This runs locally, needs no API key, and blocks the next step while any hit remains.

The word list in `data/spam_words.json` is modeled on Mailmeteor's spam words list: https://mailmeteor.com/blog/spam-words (7 categories: money, too good to be true, overpromise, urgency, health, tech/security, gambling/adult).

## Inputs
- `sequence.json` from skill 07.
- `verified_leads.csv` (optional, recommended). Per-lead values such as `{{market_insight}}` get scanned too.

## Outputs
- `spam_report.json`: `passed`, `hit_count`, `hits[]` (where, match, category, suggestion) and `template_notes[]`.
- Exit code 0 = pass, 1 = fail.

## What it flags
- Any phrase from the list (case-insensitive, whole words). Merge vars are ignored.
- `!!` or more.
- ALL CAPS words of 4+ letters.
- More than `--max-links` links (default 1) and any link shortener.

Words inside the verbatim templates (for example "the best" in Email 2B) cannot be changed, so they are listed as notes and do not fail the check.

## Env vars
None.

## Steps (agent run instructions)
1. Run:
   ```bash
   python 08-spam-check/scripts/spam_check.py --sequence sequence.json --leads verified_leads.csv
   ```
2. On FAIL, for each hit: edit the slot value in `copy_config.json` (or the lead column) using the suggestion. Never edit the template text.
3. Re-run skill 07, then this skill, until it passes.
4. Only if a hit is a false positive that you want to keep (it happens, the list has common words like "check" or "deal"), add it to `data/allowlist.txt` and say why in the commit.

## Handoff
A passing `spam_report.json` + `sequence.json` -> **09-plusvibe-campaign**. Skill 11 re-checks that the report passed and matches the current sequence.
