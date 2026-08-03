---
name: Classifier got a status wrong
about: gmail_sync.py mislabelled a report, or missed one entirely
title: ''
labels: classifier
assignees: ''
---

> **Do not paste the real thread.** Reconstruct an equivalent example with a fictional
> company and finding. The classifier reads wording, not identities, so a faithful
> paraphrase reproduces the bug just as well as the original — and doesn't disclose
> someone's unfixed vulnerability in a public issue.

**What it decided**
e.g. `acked`

**What it should have decided**
e.g. `in_progress`

**Minimal example thread**
Keep the wording patterns that matter, change every identifying detail.

```json
{
  "id": "example",
  "subject": "Security report - example finding",
  "messages": [
    { "date": "2026-01-02T10:00:00+00:00", "from": "you@example.com",
      "to": ["security@acme.example"], "body": "..." },
    { "date": "2026-01-03T10:00:00+00:00", "from": "someone@acme.example",
      "to": ["you@example.com"], "body": "the reply wording that got misread" }
  ]
}
```

**Which wording tripped it**
If you can point at the phrase that caused the wrong branch, say so — that's usually the fix.
