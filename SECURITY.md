# Security Policy

## Reporting a vulnerability in this tool

Open a [GitHub Security Advisory](https://github.com/harshilnayi/report-tracker/security/advisories/new)
rather than a public issue. That keeps the report private until there's a fix.

Expect a first response within 7 days. This is a solo project, not a funded programme — there is no
bounty, but you will get credit in the release notes and the advisory unless you'd rather not.

If you don't hear back in 14 days, open a public issue saying only that you're waiting on an advisory
response. Don't include details. Given what this tool is for, it would be embarrassing to be the
maintainer who ghosts a researcher.

## Threat model

This is a local, single-user tool. It binds to `127.0.0.1` and has no authentication, because anything
that can reach the port is already running as you on your machine.

**In scope:**

- Anything that causes `data.json`, `state.json`, the queue files, `token.json` or `credentials.json`
  to leave the machine
- Path traversal or arbitrary file read/write through the HTTP handlers
- XSS in the UI that could exfiltrate report contents — note that report titles and email bodies are
  attacker-influenced, since anyone can send you mail
- OAuth scope or token handling mistakes in `gmail_sync.py`
- Anything that could cause the tool to **send** mail rather than draft it

**Out of scope:**

- No authentication on the local port — that's the design
- The classifier misjudging a status; that's a bug, not a vulnerability, and statuses are editable
- Denial of service against your own localhost server
- Anything requiring an attacker who already has code execution as your user

## A warning for anyone running this

`data.json` contains unpatched, undisclosed vulnerabilities in real third-party products, together
with enough detail to act on them. It is the single most sensitive file this tool touches.

- It is gitignored. Leave it that way.
- Never commit it, never attach it to an issue, never paste it into a chat you don't control.
- If you use cloud-synced folders, be aware you are replicating other companies' unfixed 0-days into
  someone else's storage.
- If you leak it, tell the affected vendors before they find out another way.

Same handling applies to `token.json` and `credentials.json`, which grant read access to your entire
mailbox.
