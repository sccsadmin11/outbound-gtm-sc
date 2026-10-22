---
name: copy-generator
description: Fill the five verbatim cold email templates (Email 1 A/B/C, Email 2 A/B) from a config and the GTM strategy, add the signature and opt-out line, and output a PlusVibe-ready sequence.json with merge vars.
---

# 07 Copy generator

## Purpose
Turn the strategy from skill 02 into the 5-email sequence. The templates are fixed. The agent only writes the slot values, so copy quality comes from the strategy, not from rewriting the frame.

## The templates (verbatim, in `templates/email_templates.json`)
**Email 1A**
```
First_name, {{the value prop in one line}}.

{{CTA}}

P.S. line
```
**Email 1B**
```
First_name, {{market insight we found}}.

{{How it ties into the offer}}

{{THe offer}}

{{CTA}}
```
**Email 1C**
```
First_name, {{i made a lead magnet for you to solve XYZ problem}}

{{CTA}}
```
**Email 2A**
```
First_name, the reason I reached out to you the other day is because we help companies like {{COMPANY}} solve X problem (tied to the offer this cold email thread is trying to sell).

We recently worked with {{someone similar to COMPANY}} and generated them ABC result.

{{insert offer}}

{{CTA}}.
```
**Email 2B**
```
Whos the best person to reach at {{COMPANY}} regarding X?

If i've reached the wrong person could you point me in the right direction?

Thank you
```
Do not fix the typos (`{{THe offer}}`, `Whos`, `i've`). They are part of the template.

## What gets filled
| In the template | Becomes |
|---|---|
| `First_name` | `{{first_name}}` (PlusVibe merge var) |
| `{{COMPANY}}` | `{{company_name}}` (PlusVibe merge var) |
| any other `{{slot}}` | your value from `slots.<template>.<slot name>` |
| `P.S. line` (1A) | `P.S. ` + `plain.1A.ps_line` |
| `X problem (tied to ...)` (2A) | `plain.2A.problem` |
| `ABC result` (2A) | `plain.2A.result`. Use a real result you can back up. Never invent one |
| `regarding X?` (2B) | `regarding ` + `plain.2B.topic` + `?` |

Every email then gets, in this order:
```
<filled template>

<sender.name>
<sender.title>, <sender.company>
<sender.website>

<opt_out>
```
The default opt-out is `If you don't want to hear from me again, just reply no thx!`. Set `sender.name` to a literal name, or to `{{sender_first_name}}` so PlusVibe uses the first name of whichever inbox sends.

Slot values can use merge vars: `{{first_name}}`, `{{company_name}}`, or any column in `verified_leads.csv` (for example a per-lead `{{market_insight}}` column). Skill 09 uploads every column as a PlusVibe custom variable.

## Inputs
- `copy_config.json` (start from `examples/copy_config.json`).
- `strategy.json` from skill 02 (the source for the slot values).
- `verified_leads.csv` from skill 06 (used for the preview and the merge var check).

## Outputs
- `sequence.json`: 2 steps, with variations A/B/C and A/B. Each has a subject, `body_text`, `body_html` and the merge vars it uses. Email 2 subjects are empty so the email goes out as a reply in the same thread.
- `preview.md`: the first N leads fully rendered.

## Env vars
None. This skill writes local files only.

## Steps (agent run instructions)
1. Copy `examples/copy_config.json` to `copy_config.json`.
2. Fill it from `strategy.json`:
   - 1A value prop: `core_offer.one_liner`, rewritten in the reader's words, one line.
   - 1B: a market insight per lead. Put it in a `market_insight` column if it differs by lead.
   - 1B `THe offer`, 1C lead magnet, 2A `insert offer`: the 3 `front_end_offers`.
   - 2A `someone similar to COMPANY` and `ABC result`: only from `proof_points` that have a source.
   - CTAs: short questions. Low commitment.
3. Generate:
   ```bash
   python 07-copy-generator/scripts/generate_copy.py --config copy_config.json --leads verified_leads.csv
   ```
   Exit code 2 = a slot is missing. Exit code 1 = some lead is missing a merge var value.
4. Read `preview.md` out loud. Fix the config, not the templates.

## Handoff
`sequence.json` -> **08-spam-check** -> **09-plusvibe-campaign**.
