# Connecting your Gmail

One-time setup, roughly five minutes. You create your own Google Cloud OAuth client, so the
credentials are yours — there is no shared app, no middleman server, and nobody else's project sees
your mail.

If this feels like too much friction, skip it entirely: generate `data.json` yourself using
[SCHEMA.md](SCHEMA.md) and the tool never touches Google.

---

## 1. Create a project

Go to [console.cloud.google.com](https://console.cloud.google.com/) and create a new project. Name it
whatever you like — `report-tracker` is fine. Free tier is plenty.

## 2. Enable the Gmail API

**APIs & Services → Library → search "Gmail API" → Enable.**

## 3. Configure the consent screen

**APIs & Services → OAuth consent screen.**

- User type: **External**
- App name: anything
- User support email and developer contact: your own address
- Scopes: you can leave this blank here; the tool requests what it needs at sign-in time
- **Test users: add your own Gmail address.** This is the step people miss, and without it sign-in
  fails with `access_denied`.

Leave the app in **Testing**. You do not need to publish it or go through Google verification — a
Testing app works indefinitely for accounts listed as test users. Note that refresh tokens for
Testing apps expire after 7 days, so you'll re-run `--auth` occasionally. That's a Google policy, not
a bug here.

## 4. Create the OAuth client

**APIs & Services → Credentials → Create Credentials → OAuth client ID.**

- Application type: **Desktop app**
- Name: anything

Download the JSON. Save it in the repo root as exactly:

```
credentials.json
```

It is already gitignored. Do not commit it.

## 5. Sign in

```bash
pip install -r requirements.txt
python gmail_sync.py --auth
```

A browser window opens for Google sign-in. You'll see an "unverified app" warning — that's expected,
it's your own app. Click **Advanced → Go to (your app name)**.

On success the token is written to `token.json` and the mailbox address is printed.

## 6. Scan

```bash
python gmail_sync.py --dry-run      # see what it finds, write nothing
python gmail_sync.py --months 12    # write data.json
python server.py                    # open the UI
```

---

## Scopes, and what they let the tool do

| Scope | Why |
|---|---|
| `gmail.readonly` | Read threads to work out report status |
| `gmail.compose` | Create drafts for follow-ups |

**There is no send scope.** The tool can put a draft in your Drafts folder; it cannot send mail on your
behalf. That's deliberate and not configurable — outbound mail to a security team should be a
deliberate human action every single time.

You can revoke access whenever you like at
[myaccount.google.com/permissions](https://myaccount.google.com/permissions), then delete `token.json`.

---

## Troubleshooting

**`access_denied` on sign-in** — your address isn't in the test users list. Step 3.

**`credentials.json not found`** — the downloaded file kept its long default name. Rename it exactly.

**Token stops working after about a week** — expected for apps in Testing. Re-run
`python gmail_sync.py --auth`.

**The scan finds nothing** — the classifier looks for mail you *sent* to security intake addresses
(`security@`, `bounty@`, `disclosure@` and similar) or with report-shaped subject lines. If you report
through platform web forms rather than email, there's nothing in your mailbox to find — add those
reports manually in the UI instead.

**It found things that aren't reports** — delete them from `data.json`, or set the status and let them
sit at the bottom. Please also open an issue with an *invented* example thread that reproduces the
misfire. Never paste real report content.
