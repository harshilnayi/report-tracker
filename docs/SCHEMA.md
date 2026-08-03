# data.json schema

If you'd rather not connect Google, generate this file yourself. The tool only cares that the shape is
right — an AI coding agent with mailbox access, a script against Fastmail or Proton, or a
hand-written file all work identically.

If `data.json` exists, it is used and the Google path is never touched.

---

## Shape

```jsonc
{
  "generated": "2026-01-15",              // ISO date, shown in the sidebar
  "mailbox": "you@example.com",           // label only
  "scope": "free text describing what you chose to include",

  "statusVocab": { "awaiting": "…" },     // optional; display help only

  "programs": [
    {
      "id": "acme",                       // unique, stable, [a-z0-9-]
      "name": "Acme Corp",
      "platform": "Bug bounty",           // free text: "Immunefi", "VDP", "Direct"…
      "contact": "security@acme.example",
      "note": "optional banner shown at the top of the program",

      "reports": [
        {
          "id": "acme-1",                 // unique across the WHOLE file, stable
          "title": "Cross-tenant IDOR in /v2/objects",
          "detail": "one or two sentences of context",
          "sent": "2025-11-20",           // ISO date. Drives every day-count.
          "status": "awaiting",           // see table below
          "severity": "high",             // critical|high|medium|low|unknown
          "bounty": "$500 USD",           // optional, shown as a chip
          "threadId": "1a2b3c4d5e6f7890", // optional Gmail thread id, makes the
                                          // "Open in Gmail" link work
          "events": [
            { "date": "2025-11-20", "by": "you",  "what": "Report sent" },
            { "date": "2025-11-22", "by": "them", "what": "Automated acknowledgement" }
          ]
        }
      ]
    }
  ]
}
```

## Status values

| Value | Meaning |
|---|---|
| `awaiting` | Sent. No response of any kind. |
| `acked` | Automated acknowledgement only. No human has engaged. |
| `in_progress` | A human confirmed they are looking at it. |
| `needs_action` | Blocked on you, not on them. |
| `accepted` | Validated as a real finding. |
| `paid` | Bounty received. |
| `rejected` | Closed. Not accepted. |
| `duplicate` | Closed as a duplicate. |

`accepted`, `paid`, `rejected` and `duplicate` count as closed. Everything else is open and keeps
accruing silence.

## Events

`by` is exactly `"you"` or `"them"`. It drives three things:

- **Days silent** — measured from the most recent `them` event, or from `sent` if they have never
  replied at all. A follow-up you send does *not* reset it, which is the point.
- **Whose turn** — "ball in their court" if the last event is yours, "your move" if it's theirs.
- **Follow-up count** — every `you` event after the first is treated as a chase.

Keep events in any order; the UI sorts them by date.

## IDs must be stable

Your edits in `state.json` are keyed by report `id`. If a regenerated `data.json` assigns different
ids, every note, status override and queue entry orphans.

`gmail_sync.py` uses the Gmail thread id, which is stable across scans. If you're generating the file
yourself, use something equally durable — a thread id or a content hash, not an array index.

## Minimal valid file

```json
{
  "generated": "2026-01-15",
  "mailbox": "you@example.com",
  "programs": [
    {
      "id": "acme",
      "name": "Acme Corp",
      "contact": "security@acme.example",
      "reports": [
        {
          "id": "acme-1",
          "title": "Something is broken",
          "sent": "2025-12-01",
          "status": "awaiting",
          "events": [{ "date": "2025-12-01", "by": "you", "what": "Report sent" }]
        }
      ]
    }
  ]
}
```

## Files the tool writes back

Don't hand-edit these while the server is running.

| File | Contents |
|---|---|
| `state.json` | `{ "overrides": { "<reportId>": {status, note, title} }, "added": [...] }` |
| `follow-up-queue.json` | Array of queued follow-ups with full thread context |
| `escalation-queue.json` | Array of queued escalations, with routes and disclosure deadline |

All are gitignored. Re-running `gmail_sync.py` rewrites `data.json` only — it backs the old one up to
`data.json.bak` and never touches `state.json`.
