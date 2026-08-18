#!/usr/bin/env python3
"""
Tests for src/web_server.py.

    python3 tests/web_server_test.py

No camera, no API key, no money. A fake app listens on a real Unix socket and
records every byte it is sent, and the tests drive a real HTTP server over a
real TCP connection to 127.0.0.1 - so what is being checked is the actual wire
behaviour, not a mock's opinion of it.

The assertion that matters most is section 2: the line the fake app receives
must be *exactly* the line the phone sent. This process is a pipe. The moment it
starts helpfully prefixing "ask ", or trimming, or lower-casing, the property
the whole design rests on - that a web request and a typed line are the same
thing one step in - stops being true, and the parser eval stops predicting what
the phone will get.

The refusal tests all check the consequence rather than the status code alone:
that the fake app was never sent anything. A 403 that still forwarded the line
would be a guard in name only.
"""

import json
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import web_server                                  # noqa: E402

PASSED = FAILED = 0


def check(name, got, want):
    global PASSED, FAILED
    if got == want:
        PASSED += 1
        print(f"  ok    {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}\n          got  {got!r}\n          want {want!r}")


def section(title):
    print(f"\n{title}\n{'-' * len(title)}")


class FakeApp(threading.Thread):
    """
    A stand-in for the running camera's command socket.

    Real socket, real NUL framing, and it keeps what it was sent. `stall` is
    how the "app is wedged" path is reached without wedging anything.
    """

    def __init__(self, reply="ok", stall=False):
        super().__init__(daemon=True)
        self.dir = tempfile.mkdtemp()
        self.path = str(Path(self.dir) / "asciicam.sock")
        self.reply = reply
        self.stall = stall
        self.received = []
        self._stopping = threading.Event()
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(self.path)
        self.sock.listen(8)
        self.sock.settimeout(0.25)
        self.start()

    def run(self):
        while not self._stopping.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,),
                             daemon=True).start()

    def _serve(self, conn):
        try:
            conn.settimeout(2.0)
            buffer = b""
            while b"\n" not in buffer:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buffer += chunk
            line = buffer.split(b"\n", 1)[0].decode("utf-8")
            self.received.append(line)
            if self.stall:
                self._stopping.wait(5.0)
                return
            conn.sendall((self.reply + "\n\x00").encode("utf-8"))
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self):
        self._stopping.set()
        try:
            self.sock.close()
        except OSError:
            pass


class Served:
    """A live web server on an ephemeral port, as a context manager."""

    def __init__(self, socket_path, limit=None, timeout=None):
        forwarder = web_server.Forwarder(
            socket_path, timeout=timeout if timeout else 10.0)
        self.server = web_server.WebServer("127.0.0.1", 0, forwarder,
                                           limit=limit)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.05},
                                       daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)


def request(port, path, body=None, raw=None):
    """One HTTP request. Returns (status, parsed-json-or-text)."""
    url = f"http://127.0.0.1:{port}{path}"
    data = None
    headers = {}
    if raw is not None:
        data = raw
        headers["Content-Type"] = "application/json"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            payload = r.read().decode("utf-8")
            status = r.status
    except urllib.error.HTTPError as e:
        payload = e.read().decode("utf-8")
        status = e.code
    try:
        return status, json.loads(payload)
    except ValueError:
        return status, payload


# --- 1. the page ------------------------------------------------------------
section("1. the page a phone loads")

app = FakeApp()
with Served(app.path) as web:
    status, page = request(web.port, "/")
    check("GET / is 200", status, 200)
    check("it is a whole HTML document", page.startswith("<!DOCTYPE html>"), True)
    check("there is somewhere to type", 'id="line"' in page, True)
    check("the natural-language toggle is on by default",
          'id="nl" type="checkbox" checked' in page, True)
    check("it needs nothing off the internet",
          ("http://" not in page.replace("http://127.0.0.1", "")
           and "https://" not in page), True)
    check("loading the page sends the app nothing", app.received, [])

    status, body = request(web.port, "/nonsense")
    check("an unknown path is 404", status, 404)

# --- 2. the line arrives verbatim -------------------------------------------
section("2. a web request is a typed line")

with Served(app.path) as web:
    status, body = request(web.port, "/ask", {"line": "ask make it warmer"})
    check("POST /ask is 200", status, 200)
    check("the app got exactly what was sent",
          app.received[-1], "ask make it warmer")
    check("the reply comes back", body["reply"], "ok")
    check("and the line it answered", body["line"], "ask make it warmer")

    request(web.port, "/ask", {"line": "scheme green"})
    check("a typed setting is not turned into an ask",
          app.received[-1], "scheme green")

    request(web.port, "/ask", {"line": "  show  "})
    check("surrounding space is trimmed, nothing else",
          app.received[-1], "show")

app.stop()

# a reply longer than one packet, with blank lines in it: proves the NUL
# framing is what ends a reply, not a newline or a lucky recv boundary
long_reply = "\n".join(f"line {i}" + " padding" * 20 for i in range(200))
long_reply = long_reply.replace("line 5 ", "\n\nline 5 ")
app = FakeApp(reply=long_reply)
with Served(app.path) as web:
    status, body = request(web.port, "/ask", {"line": "help"})
    check("a long multi-line reply survives whole", body["reply"], long_reply)
app.stop()

# --- 3. only this network ---------------------------------------------------
section("3. only this network gets an answer")

check("a house address is local", web_server.is_local("192.168.1.42"), True)
check("loopback is local", web_server.is_local("127.0.0.1"), True)
check("10.x is local", web_server.is_local("10.0.0.7"), True)
check("link-local is local", web_server.is_local("169.254.3.9"), True)
check("a unique-local v6 address is local", web_server.is_local("fd00::1"), True)
check("a public address is not", web_server.is_local("8.8.8.8"), False)
check("a routable v6 address is not",
      web_server.is_local("2405:6e00:494:e523::1"), False)
check("nonsense is not", web_server.is_local("not-an-address"), False)
check("an empty peer is not", web_server.is_local(""), False)

app = FakeApp()


class FromTheInternet(web_server.Handler):
    """
    Same handler, lying about where the request came from.

    Not 203.0.113.9, which is the documentation range and the obvious choice:
    Python counts TEST-NET-1/2/3 as private, so `is_local` correctly allows it
    and this test passed against a guard that was in fact working. A public
    address is the only kind that proves anything here.
    """

    @property
    def client_address(self):
        return ("8.8.8.8", 51000)

    @client_address.setter
    def client_address(self, value):
        pass                    # BaseRequestHandler sets this; ignore it


with Served(app.path) as web:
    web.server.RequestHandlerClass = FromTheInternet
    status, body = request(web.port, "/ask", {"line": "ask make it warmer"})
    check("a request from off the LAN is 403", status, 403)
    check("and the app was sent nothing at all", app.received, [])
    status, page = request(web.port, "/")
    check("it cannot even read the page", status, 403)

check("the listener is IPv4 only, so there is no routable address to reach",
      web_server.WebServer.address_family, socket.AF_INET)

# --- 4. the rate limit counts money, not requests ---------------------------
section("4. the rate limit counts money, not requests")

check("an ask costs", web_server.costs_money("ask make it warmer"), True)
check("case does not hide it", web_server.costs_money("ASK make it warmer"), True)
check("leading space does not hide it",
      web_server.costs_money("   ask warmer"), True)
check("a setting is free", web_server.costs_money("scheme green"), False)
check("show is free", web_server.costs_money("show"), False)
check("a word merely starting with ask is free",
      web_server.costs_money("askew 3"), False)
check("an empty line is free", web_server.costs_money(""), False)

limit = web_server.AskLimit(limit=2, window=60.0)
check("the first is allowed", limit.allow(now=0.0), True)
check("the second is allowed", limit.allow(now=1.0), True)
check("the third is refused", limit.allow(now=2.0), False)
check("still refused just inside the window", limit.allow(now=59.9), False)
check("allowed again once the window has passed", limit.allow(now=61.0), True)

with Served(app.path, limit=web_server.AskLimit(limit=2, window=60.0)) as web:
    request(web.port, "/ask", {"line": "ask one"})
    request(web.port, "/ask", {"line": "ask two"})
    sent_before = list(app.received)
    status, body = request(web.port, "/ask", {"line": "ask three"})
    check("the third ask in a minute is refused", status, 429)
    check("and never reaches the app", app.received, sent_before)
    check("the refusal says what still works",
          "typed by name" in body["error"], True)

    status, body = request(web.port, "/ask", {"line": "show"})
    check("a free command still goes through while asks are capped",
          status, 200)
    check("and it really reached the app", app.received[-1], "show")

app.stop()

# --- 5. saying what went wrong ----------------------------------------------
section("5. saying what went wrong")

missing = str(Path(tempfile.mkdtemp()) / "no-such.sock")
with Served(missing) as web:
    status, body = request(web.port, "/ask", {"line": "show"})
    check("no app listening is 503, not a crash", status, 503)
    check("and it names what is missing",
          "could not reach the camera" in body["error"], True)
    status, body = request(web.port, "/health")
    check("health still answers with the app down", status, 200)
    check("and says the camera is not there", body["camera"], False)

app = FakeApp()
with Served(app.path) as web:
    status, body = request(web.port, "/health")
    check("health sees a live app", (status, body["camera"]), (200, True))
    check("asking after health cost the app nothing", app.received, [])

    status, body = request(web.port, "/ask", raw=b"{not json")
    check("unreadable JSON is 400", status, 400)
    status, body = request(web.port, "/ask", {"lion": "show"})
    check("the wrong field is 400", status, 400)
    status, body = request(web.port, "/ask", {"line": 42})
    check("a number is not a line", status, 400)
    status, body = request(web.port, "/ask", {"line": "   "})
    check("an empty line is 400", status, 400)
    status, body = request(web.port, "/ask",
                           {"line": "ask " + "x" * web_server.MAX_BODY})
    check("an over-long body is 413", status, 413)
    check("none of those reached the app", app.received, [])

    status, body = request(web.port, "/ask/nowhere", {"line": "show"})
    check("posting to the wrong path is 404", status, 404)
app.stop()

stalled = FakeApp(stall=True)
with Served(stalled.path, timeout=0.75) as web:
    started = time.monotonic()
    status, body = request(web.port, "/ask", {"line": "show"})
    took = time.monotonic() - started
    check("an app that never answers is 504", status, 504)
    check("and it gives up promptly", took < 5.0, True)
    check("the message says who was slow",
          "took too long" in body["error"], True)
stalled.stop()

print(f"\n{'-' * 60}\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
