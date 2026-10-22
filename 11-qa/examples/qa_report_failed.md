# QA report: FAIL (launch blocked)

Campaign: Acme Q3 fleets (000000000000000000c0ffee), mode: offline

| Check | Result | Detail |
|---|---|---|
| leads_unique | PASS | 3 leads, 0 duplicate(s) |
| leads_verified | FAIL | 0/3 verified |
| merge_vars_filled | FAIL | 3 problem(s) |
| signature_opt_out | PASS | signature + opt-out in every email |
| spam_check_passed | PASS | passed, matches current sequence.json |
| plusvibe_settings | PASS | 6 inboxes, limit 90, priority 0.5 |
| webhook_reachable | FAIL | no --relay-url given (deploy skill 10 first) |

## leads_verified
- dana.whitfield@acmefreight.example: no passing verification (verify_mv=, verify_bb=)
- marco@acmefreight.example: no passing verification (verify_mv=, verify_bb=)
- priya.nair@acmefoods.example: no passing verification (verify_mv=, verify_bb=)

## merge_vars_filled
- Email 1B -> dana.whitfield@acmefreight.example: no value for market_insight
- Email 1B -> marco@acmefreight.example: no value for market_insight
- Email 1B -> priya.nair@acmefoods.example: no value for market_insight
