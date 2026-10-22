# GTM strategy prompt

You are building the go-to-market strategy for a cold email campaign.

Inputs:
- The company URL: {{company_url}}
- `site_notes.md` (from `scripts/fetch_site.py`)
- Anything the user tells you about their offer, pricing and customers

Rules:
- Only use facts you can point to on the site or that the user gave you. Do not invent numbers, customers, results or logos. If a proof point has no source, leave it out.
- Plain, direct language. Short sentences. No hype words.
- Write for cold traffic: people who have never heard of the company.

Produce `strategy.json` that matches `templates/strategy.template.json`:

1. **core_offer**: what they sell, in one line, and the outcome the buyer gets.
2. **icp**: one sentence `icp_text` that a semantic search engine can match against company websites (what the company does, who it sells to, size, region). Add `negate_icp_text` for look-alikes you do NOT want (agencies, resellers, competitors). Fill `industries`, `employee_range` as `"min,max"`, `countries` as ISO-2 codes, and 3 to 5 `lookalike_domains` of real best-fit customers if the user names any.
3. **personas**: 2 to 4 buyer personas. For each: exact job `titles` to search for, `exclude_titles` (intern, assistant, etc.) and what they care about.
4. **pains**: 3 to 6 pains, each tied to a persona, with the cost of doing nothing.
5. **front_end_offers**: exactly 3 small, low-friction offers for cold traffic. Each one is a piece of the core offer split out so a stranger can say yes fast (an audit, a teardown, a sample, a free first deliverable, a lead magnet). For each: what they get, which piece of the core offer it comes from, and a one-line CTA.
6. **proof_points**: real results, case studies, notable customers or credentials, each with a `source` URL or "provided by user".

Then run:
```bash
python 02-gtm-strategy/scripts/render_strategy.py --in strategy.json --out strategy.md
```
Fix anything it flags, then show the user `strategy.md` and ask for edits before moving on.
