# Clay HTTP API column: "Send to relay"

Run condition: "Reply class" is not empty.

- Method: `POST`
- URL: `/callback_url` (the relay sends this with every row)
- Headers:
  - `Content-Type: application/json`
  - `X-Relay-Secret: <the same value as RELAY_SHARED_SECRET>`
- Body:

```json
{
  "reply_id": "/reply_id",
  "classification": "/Reply class",
  "draft_reply": "/Draft reply"
}
```

Expected response: `{"ok": true, "classification": "...", "draft_saved": true, "pings": 2}`.
