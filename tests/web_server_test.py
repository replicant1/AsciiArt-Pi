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
import logging
import re
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

import commands                                   # noqa: E402
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
    check("both boxes are there, one per radio",
          ['id="f-ask"' in page, 'id="f-raw"' in page], [True, True])
    # Matched loosely on purpose. These broke once when a data-dest attribute
    # was added between id and value - the markup was right and the test was
    # asserting the order somebody had happened to type the attributes in.
    check("your own words is the row selected to begin with",
          bool(re.search(r'id="m-ask"[^>]*\bchecked', page)), True)
    check("each box hints with an example rather than an instruction",
          ['placeholder="warmer, and blockier characters"' in page,
           'placeholder="scheme amber"' in page], [True, True])
    check("each half of the page says what it is",
          ['>What to send</h2>' in page,
           '>What the camera said</h2>' in page], [True, True])
    # A title that names no section is decoration. These have to be attached,
    # or a screen reader announces two unlabelled regions and the headings
    # float free of what they describe.
    check("and each title labels its own section",
          ['aria-labelledby="t-send"' in page,
           'aria-labelledby="t-back"' in page], [True, True])

    # The button names where the text goes, so the page has to know. Only the
    # row that spends an API call may say "model" - a row mislabelled here
    # would promise a free instant answer and quietly bill for one, or the
    # reverse, which is worse than an unlabelled button.
    dests = re.findall(r'id="m-(\w+)"[^>]*\bdata-dest="(\w+)"', page)
    check("every row declares where its text goes",
          [d[0] for d in dests], ["show", "help", "reset", "ask", "raw"])
    check("and only your own words goes to the model",
          [d[0] for d in dests if d[1] == "model"], ["ask"])
    check("the button starts by naming a destination",
          ">Send to the camera</button>" in page, True)

    check("it needs nothing off the internet",
          ("http://" not in page.replace("http://127.0.0.1", "")
           and "https://" not in page), True)
    check("loading the page sends the app nothing", app.received, [])

    # The first three radios are a shortcut for typing, so what they type has
    # to be real. A radio for a command the app does not have would fail only
    # when somebody picked it, and would answer "there is no setting called
    # ..." to a person who had typed nothing at all.
    modes = re.findall(r'name="mode"[^>]*\bvalue="(\w+)"', page)
    check("five radios, in the order the form lists them",
          modes, ["show", "help", "reset", "ask", "raw"])
    check("the three command radios are commands the app accepts",
          [m for m in modes[:3] if m not in commands.WORDS], [])
    check("and the other two are the typing rows, not commands",
          [m for m in modes[3:] if m in commands.WORDS], [])

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

# --- 6. what a client should not be able to get away with -------------------
section("6. what a client should not be able to get away with")

app = FakeApp()
with Served(app.path) as web:
    # The command socket is newline-framed, so a line carrying its own newline
    # is two commands in one request. That matters beyond tidiness: costs_money
    # only ever sees the first word, so "show\nask ..." is billed as free and
    # slips past the rate limit entirely - and the second reply is left unread
    # on a socket this closes.
    status, body = request(web.port, "/ask", {"line": "show\nask spend money"})
    check("a line carrying a newline is refused", status, 400)
    check("and not one byte of it reaches the app", app.received, [])
    status, body = request(web.port, "/ask", {"line": "show\rask spend money"})
    check("a carriage return is refused too", status, 400)
    status, body = request(web.port, "/ask", {"line": "show\x00ask spend money"})
    check("and a NUL, which is what ends a reply", status, 400)
    check("still nothing reached the app", app.received, [])
    check("a trailing newline is forgiven, not refused",
          request(web.port, "/ask", {"line": "show\n"})[0], 200)
    check("and arrives without it", app.received[-1], "show")

    # A full-length line must survive its own JSON envelope. Capping the body
    # at the socket's line limit rejected lines shorter than the limit, because
    # the quotes and the field name are part of the body and not part of the
    # line.
    long_line = "contrast " + "1" * 4081        # 4090, body 4101
    status, body = request(web.port, "/ask", {"line": long_line})
    check("a 4090-character line is not defeated by JSON overhead",
          status, 200)
    check("and arrives whole", app.received[-1], long_line)

    status, body = request(web.port, "/ask", {"line": "x" * (web_server.MAX_LINE + 1)})
    check("but a line past the socket's own limit is refused", status, 413)
    check("in its own terms", "line" in body["error"], True)

# The log has to name the limit actually in force. A refusal logged as
# "over 20 in 60 s" by a server configured for 1 in 30 sends whoever is
# diagnosing it looking for a burst that never happened.
records = []


class Grab(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())


grab = Grab()
web_server.logger.addHandler(grab)
with Served(app.path, limit=web_server.AskLimit(limit=1, window=30.0)) as web:
    request(web.port, "/ask", {"line": "ask one"})
    request(web.port, "/ask", {"line": "ask two"})
web_server.logger.removeHandler(grab)
refusals = [m for m in records if "Refusing an ask" in m]
check("one refusal was logged", len(refusals), 1)
check("and it quotes the limit this server was given",
      ["1" in m and "30" in m for m in refusals], [True])

# HTTP/1.1 means keep-alive by default. An early return that never reads the
# body leaves those bytes in the stream, and the next request on that
# connection starts reading a JSON fragment as a request line.
with Served(app.path) as web:
    raw = socket.create_connection(("127.0.0.1", web.port), timeout=5)
    payload = b'{"line": "show"}'
    raw.sendall(b"POST /nowhere HTTP/1.1\r\nHost: x\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n"
                + payload)
    got = b""
    try:
        while True:
            chunk = raw.recv(4096)
            if not chunk:
                break
            got += chunk
        closed = True
    except socket.timeout:
        closed = False          # still waiting for a request we cannot send
    raw.close()
    check("a response the body was never read for closes the connection",
          closed, True)
    check("and says so, so the client does not try to reuse it",
          b"Connection: close" in got, True)

# A client that announces a body and then says nothing must not hold a thread
# for ever - ThreadingHTTPServer hands out one per connection.
#
# Two checks, because one is not enough. The behavioural half below turns the
# timeout down to a second so the suite does not sit for fifteen, which means
# it proves the mechanism works but would still pass with the shipped default
# deleted - it sets its own. So the value that actually ships is pinned
# separately, underneath.
was = web_server.Handler.timeout
web_server.Handler.timeout = 1.0
try:
    with Served(app.path) as web:
        stall = socket.create_connection(("127.0.0.1", web.port), timeout=8)
        stall.sendall(b"POST /ask HTTP/1.1\r\nHost: x\r\n"
                      b"Content-Length: 500\r\n\r\n")   # and then nothing
        started = time.monotonic()
        try:
            while stall.recv(4096):
                pass
            gave_up = time.monotonic() - started
        except socket.timeout:
            gave_up = None
        stall.close()
        check("a stalled client is dropped rather than held", gave_up is not None,
              True)
        check("and dropped promptly", gave_up is not None and gave_up < 5.0, True)
finally:
    web_server.Handler.timeout = was

check("the shipped handler carries the shipped timeout",
      web_server.Handler.timeout, web_server.READ_TIMEOUT)
check("and it is a bound worth having",
      0 < web_server.READ_TIMEOUT <= 60, True)

app.stop()

print(f"\n{'-' * 60}\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
