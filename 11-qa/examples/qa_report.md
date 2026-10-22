# QA report: PASS

Campaign: Acme Q3 fleets (000000000000000000c0ffee), mode: offline

| Check | Result | Detail |
|---|---|---|
| leads_unique | PASS | 2 leads, 0 duplicate(s) |
| leads_verified | PASS | 2/2 verified |
| merge_vars_filled | PASS | all merge vars have values |
| signature_opt_out | PASS | signature + opt-out in every email |
| spam_check_passed | PASS | passed, matches current sequence.json |
| plusvibe_settings | PASS | 6 inboxes, limit 90, priority 0.5 |
| webhook_reachable | PASS | https://relay.acme.example/health ok |
