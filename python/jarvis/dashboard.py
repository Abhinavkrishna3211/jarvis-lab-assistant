"""Dashboard data. On the board, App Lab's web_ui brick serves assets/index.html and main.py exposes
these handlers; on a laptop, make_server() serves the same page with the stdlib (simulator only)."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db

PAGE = Path(__file__).resolve().parents[2] / "assets" / "index.html"


def state(engine):
    con, today = engine.con, engine.today().isoformat()
    items = [{"name": i["name"], "location": i["location"], "avail": db.available(con, i),
              "low": i["kind"] == "component" and db.available(con, i) <= i["low_stock_at"]}
             for i in db.all_items(con)]
    loans = [{**l, "late": l["due_date"] < today} for l in db.open_loans(con)]
    p = engine.pending
    pend = f"{p['intent'].title()} {p['qty']} {p['item']['name']} for {p['borrower']}" if p else None
    last = con.execute("SELECT result FROM events ORDER BY id DESC LIMIT 1").fetchone()
    return {"items": items, "loans": loans, "pending": pend, "last": last[0] if last else ""}


def make_server(engine, host="0.0.0.0", port=8000):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(200); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_GET(self):
            if self.path == "/api/state":
                self._send(json.dumps(state(engine)))
            else:
                self._send(PAGE.read_bytes(), "text/html; charset=utf-8")

        def do_POST(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/api/confirm":
                self._send(json.dumps({"reply": engine.confirm(q.get("yes") == "1")}))
            elif u.path == "/api/say":
                self._send(json.dumps({"reply": engine.handle(q.get("text", ""))}))
            else:
                self._send("{}")

    return ThreadingHTTPServer((host, port), H)
