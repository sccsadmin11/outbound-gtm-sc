# Clay AI column: "Reply class"

Model: any Clay AI model. Output type: text. Paste this as the prompt and map the /columns.

```
You classify replies to a cold email. Read the reply and answer with exactly one label from this list, nothing else:

interested
meeting_request
question
referral
not_now
not_interested
ooo
unsubscribe

Rules:
- meeting_request: they propose or ask for a call, meeting, time or calendar link.
- interested: positive, wants more info, but no meeting asked for yet.
- question: they ask something (price, how it works, who you are) without a clear yes or no.
- referral: they point you to someone else, or say they are the wrong person.
- not_now: timing is wrong, "reach out next quarter", "busy now".
- not_interested: a clear no, without asking to be removed.
- ooo: automatic out-of-office or vacation reply.
- unsubscribe: "remove me", "stop", "unsubscribe", "no thx", or any request to stop emailing.
- If two fit, pick the one that needs the fastest human action (meeting_request > interested > question > referral).

Original subject: /subject
Their reply:
/reply_text
```
