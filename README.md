# outbound-gtm-sc

11 outbound GTM skills that take you from zero infrastructure to replying to warm leads fast. Every step runs through real, documented HTTP APIs (or the Clay CLI), so you can run it from a terminal or hand each `SKILL.md` to an AI agent.

Each skill is a folder with:

- `SKILL.md`: what it does, inputs, outputs, env vars, steps and the handoff to the next skill
- `scripts/`: Python you can run
- `examples/`: fake data (Acme, `.example` domains) that shows the exact file shapes

Skills pass data to each other as plain CSV and JSON files.

## The 11 skills

| # | Skill | One line |
|---|---|---|
| 01 | [infra-setup](01-infra-setup/SKILL.md) | Check domain availability and price on Porkbun, create Google inboxes on Zapmail, then connect them to PlusVibe. |
| 02 | [gtm-strategy](02-gtm-strategy/SKILL.md) | Turn your website into one strategy file: ICP, personas, pains, proof and 3 front-end offers. |
| 03 | [account-scoring](03-account-scoring/SKILL.md) | Pull lookalike accounts from DiscoLike and keep only the ones that fit your ICP. |
| 04 | [people-waterfall](04-people-waterfall/SKILL.md) | Find the right people per account: Clay -> QuickEnrich -> Blitz -> GetLeads, stop at the first hit. |
| 05 | [email-waterfall](05-email-waterfall/SKILL.md) | Find work emails: QuickEnrich -> Blitz -> GetLeads -> Prospeo, stop at the first hit. |
| 06 | [email-verification](06-email-verification/SKILL.md) | Verify with MillionVerifier, send the unclear ones to BounceBan, drop the rest. |
| 07 | [copy-generator](07-copy-generator/SKILL.md) | Fill proven templates (3 x Email 1, 2 x Email 2) with your offer, signature and opt-out. |
| 08 | [spam-check](08-spam-check/SKILL.md) | Scan every subject, body and merge value for spam trigger words before anything is uploaded. |
| 09 | [plusvibe-campaign](09-plusvibe-campaign/SKILL.md) | Build the PlusVibe campaign: plain text, no tracking, inboxes x 15 per day, all columns as custom vars. |
| 10 | [speed-to-lead](10-speed-to-lead/SKILL.md) | PlusVibe reply -> Clay classifies and drafts -> draft saved in PlusVibe + Slack ping to the rep. Never auto-sends. |
| 11 | [launch-qa](11-qa/SKILL.md) | A gate that checks leads, copy, spam, settings and the webhook, and blocks launch on any fail. |

## Install

Python 3.10 or newer.

```bash
git clone https://github.com/sccsadmin11/outbound-gtm-sc.git
cd outbound-gtm-sc
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in only the keys for the skills you run
```

`.env.example` lists every key and where to get it. `.env` is in `.gitignore`, never commit it.

Skill 04 also uses the Clay CLI (https://github.com/clay-run/agent-plugins). Install it and run `clay login`. See [04-people-waterfall/SKILL.md](04-people-waterfall/SKILL.md).

## Run order

Run the skills in number order. Each one reads the files the previous one wrote.

```
01 domains + inboxes ---------------------------------> inboxes_connected.csv
02 strategy.json -> 03 qualified_accounts.csv -> 04 people.csv -> 05 leads_with_email.csv
   -> 06 verified_leads.csv -> 07 sequence.json -> 08 spam_report.json
   -> 09 campaign_state.json (campaign created, still paused)
   -> 10 relay + webhook running
   -> 11 QA gate -> launch only if every check passes
```

The `examples/` folder in every skill shows what each file looks like.

## Safety built in

- **No keys in the repo.** Every key is read from env vars (`.env`).
- **`--dry-run` on every script that writes to a third-party system.** Run it first, every time.
- **Nothing gets bought by accident.** The domain step only checks availability and price. Buying needs `buy --confirm-purchase` and a cost cap.
- **Replies are never sent automatically.** Skill 10 only saves drafts in PlusVibe and pings a human in Slack.
- **The campaign stays paused** until the QA gate in skill 11 passes and you run it with `--live --launch`.
- Some provider fields could not be fully confirmed from public docs. They are marked `TODO` in the code and in each `SKILL.md`. Check them on your first small run.

## Tests

Unit tests mock every HTTP call, so they need no keys and spend nothing:

```bash
python3 -m unittest discover -s tests
```

## Folder tree

```
outbound-gtm-sc
├── 01-infra-setup
│   ├── examples
│   │   ├── domain_check.csv
│   │   ├── domains.txt
│   │   ├── inbox_plan.csv
│   │   ├── inboxes.csv
│   │   ├── inboxes_connected.csv
│   │   └── senders.csv
│   ├── scripts
│   │   ├── plusvibe_inboxes.py
│   │   ├── porkbun_domains.py
│   │   └── zapmail_inboxes.py
│   └── SKILL.md
├── 02-gtm-strategy
│   ├── examples
│   │   ├── strategy.json
│   │   └── strategy.md
│   ├── scripts
│   │   ├── fetch_site.py
│   │   └── render_strategy.py
│   ├── templates
│   │   ├── prompt.md
│   │   └── strategy.template.json
│   └── SKILL.md
├── 03-account-scoring
│   ├── examples
│   │   ├── qualified_accounts.csv
│   │   └── scored_accounts.csv
│   ├── scripts
│   │   └── score_accounts.py
│   └── SKILL.md
├── 04-people-waterfall
│   ├── examples
│   │   ├── people.csv
│   │   └── people_not_found.csv
│   ├── scripts
│   │   └── people_waterfall.py
│   └── SKILL.md
├── 05-email-waterfall
│   ├── examples
│   │   ├── emails_not_found.csv
│   │   └── leads_with_email.csv
│   ├── scripts
│   │   └── email_waterfall.py
│   └── SKILL.md
├── 06-email-verification
│   ├── examples
│   │   ├── rejected_emails.csv
│   │   └── verified_leads.csv
│   ├── scripts
│   │   └── verify_emails.py
│   └── SKILL.md
├── 07-copy-generator
│   ├── examples
│   │   ├── copy_config.json
│   │   ├── preview.md
│   │   ├── sequence.json
│   │   └── verified_leads.csv
│   ├── scripts
│   │   └── generate_copy.py
│   ├── templates
│   │   └── email_templates.json
│   └── SKILL.md
├── 08-spam-check
│   ├── data
│   │   ├── allowlist.txt
│   │   ├── replacements.json
│   │   └── spam_words.json
│   ├── examples
│   │   └── spam_report.json
│   ├── scripts
│   │   └── spam_check.py
│   └── SKILL.md
├── 09-plusvibe-campaign
│   ├── examples
│   │   └── campaign_state.json
│   ├── scripts
│   │   └── create_campaign.py
│   └── SKILL.md
├── 10-speed-to-lead
│   ├── clay
│   │   ├── prompts
│   │   │   ├── classify_reply.md
│   │   │   └── draft_reply.md
│   │   ├── clay_setup.md
│   │   └── http_callback.md
│   ├── config
│   │   ├── reps.example.json
│   │   └── routing.json
│   ├── examples
│   │   ├── sample_clay_callback.json
│   │   └── sample_plusvibe_reply.json
│   ├── scripts
│   │   ├── business_hours.py
│   │   ├── register_webhook.py
│   │   └── relay.py
│   └── SKILL.md
├── 11-qa
│   ├── examples
│   │   ├── qa_report.json
│   │   ├── qa_report.md
│   │   └── qa_report_failed.md
│   ├── scripts
│   │   └── qa.py
│   └── SKILL.md
├── lib
│   ├── copy_utils.py
│   ├── gtm_common.py
│   ├── plusvibe.py
│   └── providers.py
├── tests
│   ├── _helpers.py
│   └── test_skills.py
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
└── requirements.txt
```

## License

MIT. See [LICENSE](LICENSE).
