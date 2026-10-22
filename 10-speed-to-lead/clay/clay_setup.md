# Clay setup (webhook table)

1. In Clay: New table -> import source **Webhook**. Copy the webhook URL into `CLAY_WEBHOOK_URL`.
   If you turn on webhook authentication in Clay, put the token in `CLAY_WEBHOOK_AUTH_TOKEN`.
   The relay sends it as `x-clay-webhook-auth` (TODO: confirm the header name shown in your Clay webhook settings).
2. Send one test row. Start the relay with `--dry-run` and replay the sample, or wait for a real reply.
   Clay then creates these columns from the JSON:
   `reply_id, callback_url, lead_email, first_name, last_name, company_name, job_title, company_website, inbox,
   sender_first_name, subject, reply_text, plusvibe_label, plusvibe_sentiment, campaign_name, step, variation`.
3. Add an AI column **Reply class** with `prompts/classify_reply.md`.
4. Add an AI column **Draft reply** with `prompts/draft_reply.md` and its run condition.
5. Add an HTTP API column **Send to relay** as in `http_callback.md`.
6. Turn on auto-run for the table so every new row runs all three columns.

The relay saves the draft in PlusVibe, so Clay never needs your PlusVibe key, and nothing is ever sent automatically.
