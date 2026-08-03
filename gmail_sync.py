#!/usr/bin/env python3
"""
Scan a Gmail mailbox for bug bounty / VDP submissions and build data.json.

    python gmail_sync.py --auth        one-time Google sign-in
    python gmail_sync.py               scan and write data.json
    python gmail_sync.py --dry-run     scan and print, write nothing
    python gmail_sync.py --self-test   run the classifier tests, no network

Your OAuth token and the resulting data.json stay on this machine. Nothing is
uploaded anywhere. See docs/GOOGLE_SETUP.md for the one-time Google Cloud step.

The classifier is heuristic on purpose. It gets you 90% of the way in one pass;
the UI lets you correct the rest, and your corrections are never overwritten by
a later scan.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "data.json")
TOKEN_FILE = os.path.join(HERE, "token.json")
CREDS_FILE = os.path.join(HERE, "credentials.json")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]

# ---------------------------------------------------------------- heuristics

# Mailbox names companies publish for security intake.
INTAKE_LOCALPARTS = {
    "security", "secure", "seclert", "secalert", "psirt", "infosec", "appsec",
    "bounty", "bugbounty", "bug-bounty", "vdp", "vulnerability", "vulnerabilities",
    "vulnerability-report", "vuln", "disclosure", "disclosures",
    "responsible-disclosure", "security-report", "cert", "abuse-security",
}

# Subject wording that marks a message as a report even when the address is a
# person rather than a role account (plenty of small projects work that way).
SUBJECT_HINTS = [
    "security report", "vulnerability", "responsible disclosure", "bug bounty",
    "bugbounty", "security advisory", "vdp report", "security issue",
    "disclosure:", "security finding", "poc", "cve-",
]

# A reply matching these is a robot, not a human picking up the report.
AUTOMATED_MARKERS = [
    "this is an automated", "automated email", "automated response",
    "do not reply", "no human will read", "please do not respond",
    "we have received your", "thank you for your submission",
    "this email confirms that we have received", "acknowledge receipt",
    "has been created from your email", "a ticket has been created",
    "your request is registered", "we will review",
]

# Outcome wording, checked against the newest human reply. Order matters:
# the first match wins, so paid/accepted are tested before rejection language.
CLOSURE_PATTERNS = [
    ("paid", [r"payment (has been )?sent", r"paypal payment", r"bounty (has been )?paid",
              r"we(?: have|'ve) sent (?:you )?(?:the )?(?:reward|bounty|payment)"]),
    ("accepted", [r"valid finding", r"we can offer", r"we are offering",
                  r"reward of", r"awarded", r"triaged as (?:high|critical|medium)"]),
    ("duplicate", [r"\bduplicate\b", r"already (?:been )?reported", r"previously submitted",
                   r"already aware of this (?:issue|report)"]),
    ("rejected", [r"not (?:a )?(?:valid|eligible|in scope)", r"out of scope",
                  r"informative(?:ly)? clos", r"intended behaviou?r", r"by design",
                  r"we are closing", r"closing this", r"not rewardable",
                  r"does not qualify", r"won'?t fix", r"declin"]),
]

SEV_HINTS = [
    ("critical", [r"\bcritical\b", r"\brce\b", r"remote code execution", r"\bp1\b"]),
    ("high",     [r"\bhigh\b", r"\bidor\b", r"cross-tenant", r"privilege escalation",
                  r"\bssrf\b", r"authentication bypass", r"\bp2\b"]),
    ("low",      [r"\blow\b", r"\bminor\b", r"informational", r"\bp4\b"]),
    ("medium",   [r"\bmedium\b", r"\bxss\b", r"\bcsrf\b", r"\bp3\b"]),
]

NOISE_DOMAINS = {
    "google.com", "accounts.google.com", "googlemail.com", "gmail.com",
    "email.openai.com", "tm.openai.com", "mailer-daemon.googlemail.com",
    "linkedin.com", "github.com", "notifications.github.com",
}


def addr_of(s):
    """Pull a bare address out of 'Name <a@b.c>' or 'a@b.c'."""
    if not s:
        return ""
    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", s)
    return m.group(0).lower() if m else ""


def domain_of(email):
    return email.split("@", 1)[1].lower() if "@" in email else ""


def root_domain(d):
    """news.acme.co.uk -> acme.co.uk (good enough for grouping)."""
    parts = d.split(".")
    if len(parts) <= 2:
        return d
    if parts[-2] in {"co", "com", "org", "net", "ac", "gov"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def program_name(dom):
    base = root_domain(dom).split(".")[0]
    return base.replace("-", " ").title()


def is_report(to_addrs, subject):
    """Does this outbound message look like a vulnerability report?"""
    subj = (subject or "").lower()
    for a in to_addrs:
        local = a.split("@", 1)[0].lower()
        dom = domain_of(a)
        if dom in NOISE_DOMAINS:
            continue
        if local in INTAKE_LOCALPARTS:
            return True
        if any(local.startswith(p) for p in ("security", "bounty", "disclosure", "vuln")):
            return True
    if any(h in subj for h in SUBJECT_HINTS):
        # Guard against replying to a newsletter that happens to say "security".
        return any(domain_of(a) not in NOISE_DOMAINS for a in to_addrs)
    return False


def is_automated(body):
    low = (body or "").lower()
    return any(m in low for m in AUTOMATED_MARKERS)


def guess_severity(text):
    low = (text or "").lower()
    for sev, pats in SEV_HINTS:
        if any(re.search(p, low) for p in pats):
            return sev
    return "unknown"


def guess_outcome(body):
    """Return a closed status, or None if the reply doesn't close anything."""
    low = (body or "").lower()
    for status, pats in CLOSURE_PATTERNS:
        if any(re.search(p, low) for p in pats):
            return status
    return None


def classify_thread(thread, me):
    """
    thread: {"id", "subject", "messages":[{"id","date","from","to","body"}...]}
    me:     the mailbox owner's address

    Returns a report dict, or None if this thread isn't a security report.
    Pure function. No network. Covered by --self-test.
    """
    msgs = sorted(thread.get("messages", []), key=lambda m: m.get("date", ""))
    if not msgs:
        return None

    mine = [m for m in msgs if addr_of(m.get("from")) == me]
    theirs = [m for m in msgs if addr_of(m.get("from")) != me]
    if not mine:
        return None  # we only track things you actually reported

    first = mine[0]
    to_addrs = [addr_of(a) for a in (first.get("to") or []) if addr_of(a)]
    if not is_report(to_addrs, thread.get("subject")):
        return None

    counterpart = next((a for a in to_addrs if domain_of(a) not in NOISE_DOMAINS), None)
    if not counterpart:
        return None

    human = [m for m in theirs if not is_automated(m.get("body"))]
    if human:
        status = guess_outcome(human[-1].get("body")) or "in_progress"
    elif theirs:
        status = "acked"
    else:
        status = "awaiting"

    events = []
    for m in msgs:
        by = "you" if addr_of(m.get("from")) == me else "them"
        if by == "you":
            what = "Report sent" if m is first else "Follow-up sent"
        elif is_automated(m.get("body")):
            what = "Automated acknowledgement"
        else:
            what = "Reply: " + re.sub(r"\s+", " ", (m.get("body") or ""))[:160].strip()
        events.append({"date": (m.get("date") or "")[:10], "by": by, "what": what})

    return {
        "id": thread["id"],
        "title": thread.get("subject") or "(no subject)",
        "detail": re.sub(r"\s+", " ", (first.get("body") or ""))[:280].strip(),
        "sent": (first.get("date") or "")[:10],
        "status": status,
        "severity": guess_severity((thread.get("subject") or "") + " " + (first.get("body") or "")),
        "threadId": thread["id"],
        "events": events,
        "_contact": counterpart,
    }


def build_data(threads, me):
    """Group classified reports into programs keyed by the counterpart domain."""
    programs = {}
    for t in threads:
        rep = classify_thread(t, me)
        if not rep:
            continue
        contact = rep.pop("_contact")
        dom = root_domain(domain_of(contact))
        prog = programs.setdefault(dom, {
            "id": re.sub(r"[^a-z0-9]+", "-", dom).strip("-"),
            "name": program_name(dom),
            "platform": "Email",
            "contact": contact,
            "reports": [],
        })
        prog["reports"].append(rep)

    for p in programs.values():
        p["reports"].sort(key=lambda r: r["sent"], reverse=True)

    return {
        "generated": datetime.now(timezone.utc).date().isoformat(),
        "mailbox": me,
        "scope": "Auto-detected bug bounty / VDP reports. Statuses are heuristic — correct them in the UI.",
        "statusVocab": {
            "awaiting": "Sent. No response of any kind.",
            "acked": "Automated acknowledgement only. No human has engaged.",
            "in_progress": "A human confirmed they are looking at it.",
            "needs_action": "Blocked on YOU, not on them.",
            "accepted": "Validated as a real finding.",
            "paid": "Bounty received.",
            "rejected": "Closed. Not accepted.",
            "duplicate": "Closed as a duplicate.",
        },
        "programs": sorted(programs.values(), key=lambda p: p["name"].lower()),
    }


# ---------------------------------------------------------------- gmail glue

def get_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("Missing deps. Run:  pip install -r requirements.txt")

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_FILE):
                sys.exit(
                    "credentials.json not found.\n"
                    "Create a Google Cloud OAuth client (Desktop app), download the JSON,\n"
                    "and save it here as credentials.json. See docs/GOOGLE_SETUP.md."
                )
            creds = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES).run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def header(payload, name):
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def extract_body(payload):
    """Walk the MIME tree for the first text/plain part."""
    import base64

    def decode(data):
        return base64.urlsafe_b64decode(data.encode()).decode("utf-8", "replace")

    if payload.get("mimeType", "").startswith("text/plain"):
        data = payload.get("body", {}).get("data")
        if data:
            return decode(data)
    for part in payload.get("parts", []) or []:
        found = extract_body(part)
        if found:
            return found
    return ""


def fetch_threads(svc, months):
    since = (datetime.now(timezone.utc) - timedelta(days=30 * months)).strftime("%Y/%m/%d")
    query = f"after:{since} (in:sent OR in:inbox) -in:chats"
    thread_ids, token = [], None
    while True:
        resp = svc.users().threads().list(
            userId="me", q=query, pageToken=token, maxResults=100).execute()
        thread_ids += [t["id"] for t in resp.get("threads", [])]
        token = resp.get("nextPageToken")
        if not token:
            break

    print(f"  {len(thread_ids)} threads in the last {months} months. Reading...")
    out = []
    for i, tid in enumerate(thread_ids, 1):
        if i % 25 == 0:
            print(f"    {i}/{len(thread_ids)}")
        try:
            t = svc.users().threads().get(userId="me", id=tid, format="full").execute()
        except Exception as exc:                      # one bad thread must not kill the run
            print(f"    ! skipped {tid}: {exc}")
            continue
        msgs = []
        for m in t.get("messages", []):
            p = m.get("payload", {})
            msgs.append({
                "id": m.get("id"),
                "date": datetime.fromtimestamp(
                    int(m.get("internalDate", 0)) / 1000, timezone.utc).isoformat(),
                "from": header(p, "From"),
                "to": [a.strip() for a in header(p, "To").split(",") if a.strip()],
                "body": extract_body(p),
            })
        out.append({"id": tid, "subject": header(
            t["messages"][0].get("payload", {}), "Subject"), "messages": msgs})
    return out


# ---------------------------------------------------------------- self-test

def self_test():
    me = "hunter@example.com"
    cases = [
        ("silent report", {
            "id": "t1", "subject": "Security report - IDOR in /api/orders",
            "messages": [{"date": "2026-01-02T10:00:00+00:00", "from": me,
                          "to": ["security@acme.com"], "body": "Full writeup attached."}]},
         "awaiting"),
        ("robot ack only", {
            "id": "t2", "subject": "Responsible disclosure - stored XSS",
            "messages": [
                {"date": "2026-01-02T10:00:00+00:00", "from": me,
                 "to": ["security@acme.com"], "body": "Details."},
                {"date": "2026-01-02T10:01:00+00:00", "from": "security@acme.com",
                 "to": [me], "body": "This is an automated response. We have received your report."}]},
         "acked"),
        ("human engaged", {
            "id": "t3", "subject": "Bug bounty - SSRF",
            "messages": [
                {"date": "2026-01-02T10:00:00+00:00", "from": me,
                 "to": ["bounty@acme.com"], "body": "Details."},
                {"date": "2026-01-03T10:00:00+00:00", "from": "jo@acme.com",
                 "to": [me], "body": "Thanks, we reproduced it and are working on a fix."}]},
         "in_progress"),
        ("closed as dupe", {
            "id": "t4", "subject": "Security report - signature bypass",
            "messages": [
                {"date": "2026-01-02T10:00:00+00:00", "from": me,
                 "to": ["security@acme.com"], "body": "Details."},
                {"date": "2026-01-04T10:00:00+00:00", "from": "jo@acme.com",
                 "to": [me], "body": "This is a duplicate of an earlier report."}]},
         "duplicate"),
        ("rewarded", {
            "id": "t5", "subject": "Security report - cross-origin XSS",
            "messages": [
                {"date": "2026-01-02T10:00:00+00:00", "from": me,
                 "to": ["security@acme.com"], "body": "Details."},
                {"date": "2026-01-05T10:00:00+00:00", "from": "jo@acme.com",
                 "to": [me], "body": "Valid finding. We can offer a $500 USD reward."}]},
         "accepted"),
        ("rejected", {
            "id": "t6", "subject": "Security report - draft metadata exposure",
            "messages": [
                {"date": "2026-01-02T10:00:00+00:00", "from": me,
                 "to": ["security@acme.com"], "body": "Details."},
                {"date": "2026-01-06T10:00:00+00:00", "from": "jo@acme.com",
                 "to": [me], "body": "This is intended behaviour, closing this."}]},
         "rejected"),
    ]

    failures = 0
    for label, thread, expected in cases:
        got = classify_thread(thread, me)
        status = got["status"] if got else None
        ok = status == expected
        failures += not ok
        print(f"  [{'ok ' if ok else 'FAIL'}] {label:<18} expected={expected:<12} got={status}")

    # Things that must NOT be picked up as reports.
    negatives = [
        ("newsletter", {"id": "n1", "subject": "Your weekly security digest",
                        "messages": [{"date": "2026-01-02T10:00:00+00:00",
                                      "from": "news@email.openai.com", "to": [me], "body": "hi"}]}),
        ("job application", {"id": "n2", "subject": "Application - Intern",
                             "messages": [{"date": "2026-01-02T10:00:00+00:00", "from": me,
                                           "to": ["info@company.com"], "body": "I am applying."}]}),
    ]
    for label, thread in negatives:
        got = classify_thread(thread, me)
        ok = got is None
        failures += not ok
        print(f"  [{'ok ' if ok else 'FAIL'}] {label:<18} correctly ignored={ok}")

    # Grouping
    data = build_data([c[1] for c in cases], me)
    ok = len(data["programs"]) == 1 and len(data["programs"][0]["reports"]) == 6
    failures += not ok
    print(f"  [{'ok ' if ok else 'FAIL'}] grouping          1 program / 6 reports={ok}")

    print(f"\n  {'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    return 1 if failures else 0


# ---------------------------------------------------------------- entrypoint

def main():
    ap = argparse.ArgumentParser(description="Build data.json from your Gmail mailbox.")
    ap.add_argument("--auth", action="store_true", help="run Google sign-in and exit")
    ap.add_argument("--months", type=int, default=12, help="how far back to scan (default 12)")
    ap.add_argument("--dry-run", action="store_true", help="print a summary, write nothing")
    ap.add_argument("--self-test", action="store_true", help="test the classifier offline")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())

    svc = get_service()
    if args.auth:
        me = svc.users().getProfile(userId="me").execute()["emailAddress"]
        print(f"  Signed in as {me}. Token saved to token.json.")
        return

    me = svc.users().getProfile(userId="me").execute()["emailAddress"]
    print(f"  Mailbox: {me}")
    data = build_data(fetch_threads(svc, args.months), me)

    n_prog = len(data["programs"])
    n_rep = sum(len(p["reports"]) for p in data["programs"])
    print(f"\n  Found {n_prog} programs / {n_rep} reports.")
    for p in data["programs"]:
        print(f"    {p['name']:<24} {len(p['reports'])} report(s)  {p['contact']}")

    if args.dry_run:
        print("\n  --dry-run: nothing written.")
        return

    if os.path.exists(DATA_FILE):
        backup = DATA_FILE + ".bak"
        os.replace(DATA_FILE, backup)
        print(f"\n  Previous data.json moved to {os.path.basename(backup)}")

    with open(DATA_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print(f"  Wrote {DATA_FILE}")
    print("  Your edits in state.json are untouched. Start the UI with: python server.py")


if __name__ == "__main__":
    main()
