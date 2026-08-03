# Report Tracker

**Know which of your bug bounty reports have gone quiet — and do something about it.**

You send a report. Nothing comes back. Three weeks later you can't remember whether you already
followed up, whether they ever actually replied, or which of your eleven open reports is the one
rotting hardest. Spreadsheets don't help because they don't know what happened in your inbox.

This reads your mailbox, works out the real state of every submission, and shows you the pile
sorted by how badly it's stuck.

Runs entirely on your machine. Binds to `127.0.0.1`. Nothing is uploaded anywhere, ever.

---

## What it does

- **Scans Gmail** for security reports you've sent and works out the status of each from the actual
  thread — sent, robot-acked, human engaged, rejected, duplicate, paid.
- **Sorts by rot.** The sidebar puts whatever has been silent longest at the top. A big number tells
  you exactly how many days it's been since a human said anything.
- **Knows whose turn it is.** "Ball in their court" versus "your move", derived from who spoke last.
- **Follow-up queue.** Click a report, pick a tone, and it writes a work item — with the full thread
  history — to `follow-up-queue.json`. Hand that file to an LLM agent to draft the emails, or work it
  by hand.
- **Escalation queue.** For vendors that ignore even the follow-ups. Anything silent 21+ days with no
  human reply gets flagged, with a 90-day disclosure deadline computed from your original report date.
- **Yours to correct.** Every status is editable, and reports that live on a platform rather than in
  email (Immunefi, HackerOne, Cantina, MSRC) can be added by hand. Your edits live in `state.json`
  and survive every re-sync.

---

## Quick start

```bash
git clone https://github.com/harshilnayi/report-tracker.git
cd report-tracker
python server.py
```

That opens `http://127.0.0.1:8787` with fictional sample data so you can see what it does before
connecting anything. Python 3.9+, no dependencies for this part.

### Loading your own mail

Two ways in. Pick either.

**Option A — built-in Gmail sync.** One-time Google Cloud setup (about five minutes, walked through in
[docs/GOOGLE_SETUP.md](docs/GOOGLE_SETUP.md)), then:

```bash
pip install -r requirements.txt
python gmail_sync.py --auth
python gmail_sync.py --months 12
```

Your OAuth token lands in `token.json` on your disk and is never transmitted anywhere except Google.
Scopes are `gmail.readonly` and `gmail.compose` — it can read your mail and create drafts. **It cannot
send.** That is deliberate: outbound mail to a security team should be a human decision, every time.

Try `python gmail_sync.py --dry-run` first to see what it would detect without writing anything.

**Option B — bring your own data.** `data.json` is a documented, boring JSON file
([docs/SCHEMA.md](docs/SCHEMA.md)). Generate it however you like — an AI coding agent with mailbox
access, a script against a different mail provider, or by hand. If the file exists, the tool uses it
and the Google path is never touched.

---

## How the queues work

The two queues are plain JSON files. The tool doesn't email anyone and has no AI built into it — it
prepares work items and gets out of the way.

A follow-up entry carries everything needed to write a good email without re-reading the thread:
program, contact, report title, days silent, the full event timeline, your private notes, the tone you
picked, and any specific angle you typed.

The intended loop, if you use an AI assistant:

> "check the follow-up queue"

It reads the file, drafts one email per item, and puts them in your Drafts folder for you to review
and send. Nothing is sent automatically. If you don't use an assistant, the file is perfectly readable
on its own — it's a to-do list with the context already gathered.

---

## Escalation, and doing it properly

When a vendor ignores a valid report for a month, escalating is legitimate and normal. Doing it
*badly* destroys you rather than them, so this tool is opinionated about the difference.

**The escalation queue targets published and corporate channels only:**

- `security.txt` / `.well-known/security.txt`
- Published role addresses — legal@, privacy@, press@
- Named executives at the **company domain**, derived from the organisation's public email pattern
- CERT/CC, or your national CERT, by jurisdiction
- GitHub Security Advisory, for open-source targets
- A dated 90-day disclosure notice, counted from your original report

**It deliberately does not do personal addresses.** Not executives' private inboxes, not anything
harvested from breach dumps or people-search sites. Three reasons, in order of how much they should
worry you:

1. A vulnerability report arriving at someone's private email doesn't read as disclosure. It reads as
   a threat. You will hear from a lawyer, not a triager.
2. Most safe-harbour clauses require you to stay in the designated channel. Going around it is the
   standard argument for voiding your protection — and if you have an unpaid report open, it is
   trivially recast as extortion.
3. It doesn't even work as well. A CERT/CC case with a published deadline moves a company that has
   ignored five of your emails. A message to the CEO's Gmail gets you blocked.

**If you set a disclosure deadline, honour it.** Either disclose when it expires or formally extend it
in writing. A deadline you quietly let slide teaches every vendor that your deadlines are noise.

---

## Security

**`data.json` is the most sensitive file you will ever put on your disk as a bug hunter.** It contains
unpatched, undisclosed vulnerabilities in named third-party products, indexed and summarised.

- It is in `.gitignore`. Leave it there.
- Never commit it, never paste it into an issue, never attach it to a bug report.
- Git history is effectively permanent. One `git add -f` cannot be undone by deleting the file later.
- Treat a leak of this file as an uncoordinated 0-day drop against every vendor listed inside it, and
  as the end of your safe harbour with all of them simultaneously.

Same applies to `token.json` and `credentials.json`. All are gitignored.

Found a security problem in this tool? See [SECURITY.md](SECURITY.md).

---

## Status vocabulary

| Status | Meaning |
|---|---|
| `awaiting` | Sent. No response of any kind. |
| `acked` | Automated acknowledgement only. No human has engaged. |
| `in_progress` | A human confirmed they are looking at it. |
| `needs_action` | Blocked on **you**, not on them. |
| `accepted` | Validated as a real finding. |
| `paid` | Bounty received. |
| `rejected` | Closed. Not accepted. |
| `duplicate` | Closed as a duplicate. |

The distinction between `acked` and `in_progress` is the one that matters most. A robot replying is
not triage, and a lot of reports die in that gap because the acknowledgement felt like progress.

---

## Files

| File | Committed? | What it is |
|---|---|---|
| `server.py` | yes | Local web server, stdlib only |
| `index.html` | yes | The whole UI, one file, no build step |
| `gmail_sync.py` | yes | OAuth + mailbox scan → `data.json` |
| `data.sample.json` | yes | Fictional demo data |
| `data.json` | **no** | Your real reports |
| `state.json` | **no** | Your edits, notes, manual additions |
| `follow-up-queue.json` | **no** | Queued follow-ups |
| `escalation-queue.json` | **no** | Queued escalations |
| `token.json`, `credentials.json` | **no** | Your Google OAuth secrets |

---

## Accuracy

The classifier is heuristic. It reads wording to decide whether a reply was a robot or a human, and
whether a human closed the report. It will get some wrong — a politely-worded rejection can read as
engagement, and an unusual auto-responder can read as a person.

That's why every status is editable and why your corrections live in a separate file that re-syncing
never overwrites. Treat the first scan as a strong first draft, not as truth.

Run `python gmail_sync.py --self-test` to exercise the classifier offline, with no network and no
credentials.

---

## Contributing

Issues and PRs welcome. Two rules:

1. **Never paste real report data into an issue.** Redact company names and findings. If you're
   reporting a classifier bug, invent an example thread that reproduces it.
2. Keep the UI dependency-free. One HTML file, no build step, no npm. That constraint is the reason
   this thing still runs in five years.

---

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Use it, fork it, sell it if you can. If you redistribute it or ship a modified version, keep the
attribution and say what you changed — that's Apache §4(b), and it's the whole ask.

Built by [Harshil Nayi](https://github.com/harshilnayi).
