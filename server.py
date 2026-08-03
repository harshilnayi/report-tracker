#!/usr/bin/env python3
"""
Local report tracker for bug bounty / VDP submissions.

Binds to 127.0.0.1 only. Nothing is exposed off this machine.

  python server.py            -> http://127.0.0.1:8787
  python server.py --port N   -> use a different port

Files it touches, all in this directory:
  data.json               read-only baseline, written by gmail_sync.py
  state.json              your local edits (status overrides, notes, added reports)
  follow-up-queue.json    follow-up requests you queue from the UI
"""

import argparse
import json
import os
import sys
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "data.json")
SAMPLE_FILE = os.path.join(HERE, "data.sample.json")
STATE_FILE = os.path.join(HERE, "state.json")
QUEUE_FILE = os.path.join(HERE, "follow-up-queue.json")
ESCALATION_FILE = os.path.join(HERE, "escalation-queue.json")

_lock = threading.Lock()


class SingleInstanceHTTPServer(HTTPServer):
    """HTTPServer sets allow_reuse_address=1, which on Windows lets a second process
    hijack a port that is already being listened on. We want the opposite: a second
    launch must fail to bind so it can detect the running instance and just open a tab."""
    allow_reuse_address = False


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  ! could not read {os.path.basename(path)}: {exc}", file=sys.stderr)
        return default


def _write_json(path, payload):
    """Write via a temp file then replace, so an interrupted write can't truncate."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _shift_sample(data):
    """Slide every date in the sample forward so the newest event is ~2 days old.

    Without this the demo silently rots: ship it in January and by June every
    sample report reads as 150 days silent, which teaches the wrong thing about
    what the colours mean."""
    if not data.get("programs"):
        return data
    dates = [e["date"] for p in data["programs"] for r in p["reports"]
             for e in r.get("events", []) if e.get("date")]
    dates += [r["sent"] for p in data["programs"] for r in p["reports"] if r.get("sent")]
    if not dates:
        return data

    try:
        newest = max(datetime.strptime(d, "%Y-%m-%d") for d in dates)
    except ValueError:
        return data
    delta = (datetime.now() - timedelta(days=2)) - newest

    def bump(d):
        try:
            return (datetime.strptime(d, "%Y-%m-%d") + delta).strftime("%Y-%m-%d")
        except ValueError:
            return d

    for p in data["programs"]:
        for r in p["reports"]:
            if r.get("sent"):
                r["sent"] = bump(r["sent"])
            for e in r.get("events", []):
                if e.get("date"):
                    e["date"] = bump(e["date"])
    data["generated"] = datetime.now().strftime("%Y-%m-%d")
    return data


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    # Quieter logs: one line per request, no noise for static assets.
    def log_message(self, fmt, *args):
        msg = fmt % args
        if "/api/" in msg:
            print(f"  {msg}")

    def _send_json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()

        if self.path == "/api/state":
            with _lock:
                return self._send_json(_read_json(STATE_FILE, {}))

        if self.path == "/api/queue":
            with _lock:
                return self._send_json(_read_json(QUEUE_FILE, []))

        if self.path == "/api/escalation":
            with _lock:
                return self._send_json(_read_json(ESCALATION_FILE, []))

        if self.path == "/api/data":
            with _lock:
                if os.path.exists(DATA_FILE):
                    return self._send_json(_read_json(DATA_FILE, {}))
                sample = _shift_sample(_read_json(SAMPLE_FILE, {}))
                sample["isSample"] = True
                return self._send_json(sample)

        return super().do_GET()

    def do_POST(self):
        payload = self._read_body()
        if payload is None:
            return self._send_json({"ok": False, "error": "bad or empty JSON body"}, 400)

        if self.path == "/api/state":
            with _lock:
                _write_json(STATE_FILE, payload)
            return self._send_json({"ok": True})

        if self.path == "/api/queue":
            item = {
                "queuedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "handled": False,
                **payload,
            }
            with _lock:
                queue = _read_json(QUEUE_FILE, [])
                if not isinstance(queue, list):
                    queue = []
                queue.append(item)
                _write_json(QUEUE_FILE, queue)
            print(f"  + queued follow-up: {item.get('programName')} / {item.get('reportTitle')}")
            return self._send_json({"ok": True, "queueLength": len(queue)})

        if self.path == "/api/escalation":
            item = {
                "queuedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "handled": False,
                **payload,
            }
            with _lock:
                queue = _read_json(ESCALATION_FILE, [])
                if not isinstance(queue, list):
                    queue = []
                queue.append(item)
                _write_json(ESCALATION_FILE, queue)
            print(f"  ! ESCALATION queued: {item.get('programName')} "
                  f"({item.get('daysSilent')}d silent, disclose by {item.get('disclosureDeadline')})")
            return self._send_json({"ok": True, "queueLength": len(queue)})

        if self.path == "/api/queue/clear":
            with _lock:
                _write_json(QUEUE_FILE, [])
            print("  - queue cleared")
            return self._send_json({"ok": True})

        if self.path == "/api/escalation/clear":
            with _lock:
                _write_json(ESCALATION_FILE, [])
            print("  - escalation queue cleared")
            return self._send_json({"ok": True})

        return self._send_json({"ok": False, "error": "unknown endpoint"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    using_sample = not os.path.exists(DATA_FILE)
    if using_sample and not os.path.exists(SAMPLE_FILE):
        sys.exit(f"Neither data.json nor data.sample.json found in {HERE} - nothing to serve.")

    url = f"http://127.0.0.1:{args.port}/"

    # Double-clicking the desktop shortcut twice shouldn't error out. If the port is
    # already taken, assume it's our own server and just point the browser at it.
    try:
        server = SingleInstanceHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        print(f"\n  Already running -> {url}\n  Opening browser.\n")
        webbrowser.open(url)
        return

    data = _read_json(SAMPLE_FILE if using_sample else DATA_FILE, {})
    n_programs = len(data.get("programs", []))
    n_reports = sum(len(p.get("reports", [])) for p in data.get("programs", []))

    print()
    print(f"  Report tracker  ->  {url}")
    if using_sample:
        print("  Showing SAMPLE data (fictional). Run 'python gmail_sync.py' to load your own.")
    print(f"  {n_programs} programs, {n_reports} reports, mailbox {data.get('mailbox', '?')}")
    print(f"  Follow-up queue:   {QUEUE_FILE}")
    print(f"  Escalation queue:  {ESCALATION_FILE}")
    print("  Local only (127.0.0.1). Ctrl+C to stop.")
    print()

    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
