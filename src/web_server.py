"""
A phone, over WiFi, into the same queue a typed line lands in.

The enclosure seals the box. Its east wall carries mini-HDMI and USB-C power and
nothing else, so the input inventory is the encoder, the shutdown button, the
camera and WiFi - and everything on that list except WiFi carries a few bits per
second. Natural language needs a keyboard, and the best keyboard available is
the one already in a pocket.

So this serves one page to a phone on the LAN and forwards whatever is typed
into it to the app's command socket, verbatim. It is a *client* of that socket,
exactly like tools/asciicam_cli.py, which is the whole design:

    phone -> HTTP -> this -> Unix socket -> resolver -> render loop

Nothing new reaches the render loop. A web request becomes a typed line one step
in, and from there it is indistinguishable from one somebody typed at the CLI -
same validation, same wording, same single entry point. This process knows
nothing about RenderConfig, the parser or the panel, and cannot learn: its whole
vocabulary is "a line of text" and "the reply that came back".

Why a separate process rather than a thread inside the app:

  * The render loop is not put at risk by a socket bug, a wedged client or a
    listener that fails to bind. The worst this can do is not answer.
  * It can be started, stopped and tested with the camera running. The service
    owns /dev/spidev0.0 and the camera; this owns a TCP port, and the two never
    contend. Every test below runs against the live app without disturbing it.
  * The money can be switched off on its own. Asks cost per request, so being
    able to stop the thing that accepts them from strangers - without stopping
    the camera - is worth a second systemd unit.

Two decisions about exposure, both deliberate:

  * **IPv4 only.** This Pi has a globally routable IPv6 address, and a listener
    on it would be reachable from outside the house the moment the router
    permits it. Binding AF_INET means there is no such address to reach; "do not
    expose it" is easier to guarantee by not listening on anything routable than
    by trusting a firewall rule nobody will re-check.
  * **Private source addresses only.** A request whose peer is not RFC1918,
    loopback or link-local is refused before the body is read. This is a second
    fence behind the first, and it is the one that still stands if somebody
    port-forwards the box by accident.

And one about cost. `ask` spends an API call; every other line is free. So the
rate limit counts asks only, per process rather than per client - the hazard
being guarded is a bill, and a bill does not care which phone ran it up.

Run it:

    python3 src/web_server.py                    # 0.0.0.0:8080, LAN only
    python3 src/web_server.py --port 9000
    python3 src/web_server.py --host 127.0.0.1   # for tests

Then open http://<the Pi's address>:8080/ on the phone.
"""

import argparse
import ipaddress
import json
import logging
import os
import socket
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

DEFAULT_SOCKET = "/home/rod/Projects/AsciiArt/asciicam.sock"
DEFAULT_PORT = 8080

# The app terminates every reply with a NUL so a multi-line answer - `help` is
# thirty-odd lines - can be read whole rather than guessed at by counting
# newlines. Same constant as tools/asciicam_cli.py, same reason.
END = b"\x00"

# Generous, because an ask crosses two networks: this to the app, and the app to
# the model. A typed setting answers within a frame. Matching the CLI's 90 s
# matters - a client that gave up sooner would report a failure for a change the
# camera had already made.
SOCKET_TIMEOUT = 90.0

# Refused rather than buffered, and the same 4096 the command socket enforces on
# a line. Nothing typed on a phone comes close.
MAX_BODY = 4096

# Asks per window, counted across every client. 20 a minute is far more than a
# person types and far less than a loop costs.
ASK_LIMIT = 20
ASK_WINDOW = 60.0


class Forwarder:
    """Sends one line to the app's command socket and returns its reply."""

    def __init__(self, path=DEFAULT_SOCKET, timeout=SOCKET_TIMEOUT):
        self.path = path
        self.timeout = timeout

    def send(self, line):
        """
        Args:
            line: exactly what should arrive at the app, newline excluded.

        Returns:
            The app's whole reply, NUL stripped.

        Raises:
            OSError: the socket is not there, or went away mid-request.
        """
        # A connection per request rather than one held open. The app charges a
        # client slot for an open connection (MAX_CLIENTS is 8) and an idle web
        # server holding one for hours would spend a slot on nothing; a phone
        # types once a minute at most, so the connect cost is free.
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.path)
            sock.sendall((line + "\n").encode("utf-8"))
            buffer = b""
            while END not in buffer:
                chunk = sock.recv(4096)
                if not chunk:
                    raise OSError("the app closed the connection")
                buffer += chunk
            return buffer.split(END, 1)[0].decode("utf-8", "replace").rstrip("\n")
        finally:
            sock.close()

    def alive(self):
        """Whether the app is listening, without sending it anything."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        try:
            sock.connect(self.path)
            return True
        except OSError:
            return False
        finally:
            sock.close()


class AskLimit:
    """
    A sliding window over the requests that cost money.

    Only asks are counted. `show`, `help` and a typed setting are free and are
    never refused - a rate limit that locked somebody out of `reset` because
    they had been experimenting with phrasing would be protecting the wrong
    thing.
    """

    def __init__(self, limit=ASK_LIMIT, window=ASK_WINDOW):
        self.limit = limit
        self.window = window
        self._times = deque()
        self._lock = threading.Lock()

    def allow(self, now=None):
        """True if another ask may go through, recording it if so."""
        now = time.monotonic() if now is None else now
        with self._lock:
            while self._times and now - self._times[0] >= self.window:
                self._times.popleft()
            if len(self._times) >= self.limit:
                return False
            self._times.append(now)
            return True


def costs_money(line):
    """Whether this line would send the utterance to a language model."""
    tokens = line.strip().split(None, 1)
    return bool(tokens) and tokens[0].lower() == "ask"


def is_local(address):
    """
    Whether a peer address is somewhere on this house's network.

    A malformed address is not local. Anything that is not plainly private is
    refused rather than puzzled over.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>ASCII Camera</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px;
    background: #12100c; color: #e8dcc0;
    font: 16px/1.45 system-ui, -apple-system, sans-serif;
    -webkit-text-size-adjust: 100%;
  }
  h1 { margin: 0 0 12px; font-size: 18px; font-weight: 600; letter-spacing: .02em; }
  h1 .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%;
            background: #6b6255; margin-right: 8px; vertical-align: middle; }
  h1.up .dot { background: #7fbf5f; }
  form { display: flex; gap: 8px; }
  input[type=text] {
    flex: 1 1 auto; min-width: 0;
    padding: 14px; border-radius: 10px;
    border: 1px solid #3a352c; background: #1c1913; color: inherit;
    font: inherit;
  }
  input[type=text]:focus { outline: 2px solid #b8873a; outline-offset: -1px; }
  button {
    padding: 14px 18px; border-radius: 10px; border: 0;
    background: #b8873a; color: #12100c; font: 600 16px system-ui, sans-serif;
  }
  button:disabled { opacity: .5; }
  .row { display: flex; align-items: center; gap: 14px;
         margin: 12px 0; flex-wrap: wrap; }
  label { display: flex; align-items: center; gap: 7px; font-size: 14px;
          color: #b9ad93; }
  input[type=checkbox] { width: 18px; height: 18px; accent-color: #b8873a; }
  .chip {
    background: #241f18; color: #cbbfa3;
    border: 1px solid #3a352c; border-radius: 999px;
    padding: 7px 13px; font: 14px system-ui, sans-serif;
  }
  #out {
    margin-top: 14px; padding: 12px;
    background: #0c0a07; border: 1px solid #2a251d; border-radius: 10px;
    font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
    white-space: pre-wrap; word-break: break-word;
    min-height: 3em; max-height: 60vh; overflow-y: auto;
  }
  .said { color: #8f836d; }
  .err  { color: #d98a6a; }
  .sep  { border: 0; border-top: 1px solid #2a251d; margin: 10px 0; }
</style>
</head>
<body>
<h1 id="head"><span class="dot"></span>ASCII Camera</h1>

<form id="form" autocomplete="off">
  <input id="line" type="text" enterkeyhint="send" autocapitalize="none"
         placeholder="warmer, and blockier characters">
  <button id="go" type="submit">Send</button>
</form>

<div class="row">
  <label><input id="nl" type="checkbox" checked> say it in your own words</label>
  <button class="chip" type="button" data-raw="show">show</button>
  <button class="chip" type="button" data-raw="help">help</button>
  <button class="chip" type="button" data-raw="reset">reset</button>
</div>

<div id="out">Type what you want to see.</div>

<script>
(function () {
  var out = document.getElementById('out');
  var box = document.getElementById('line');
  var nl = document.getElementById('nl');
  var go = document.getElementById('go');
  var head = document.getElementById('head');
  var busy = false;

  function show(said, reply, bad) {
    var entry = document.createElement('div');
    var q = document.createElement('div');
    q.className = 'said';
    q.textContent = '› ' + said;
    var a = document.createElement('div');
    if (bad) { a.className = 'err'; }
    a.textContent = reply;
    entry.appendChild(q);
    entry.appendChild(a);
    if (out.firstChild && out.firstChild.nodeType === 1) {
      var rule = document.createElement('hr');
      rule.className = 'sep';
      out.insertBefore(rule, out.firstChild);
      out.insertBefore(entry, rule);
    } else {
      out.textContent = '';
      out.appendChild(entry);
    }
    while (out.children.length > 40) { out.removeChild(out.lastChild); }
  }

  function send(line, said) {
    if (busy) { return; }
    busy = true;
    go.disabled = true;
    var was = go.textContent;
    go.textContent = '…';
    fetch('ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ line: line })
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, d: d }; });
    }).then(function (res) {
      var d = res.d || {};
      show(said, d.reply || d.error || '(no answer)', !res.ok || !!d.error);
    }).catch(function (e) {
      show(said, 'could not reach the camera: ' + e, true);
    }).then(function () {
      busy = false;
      go.disabled = false;
      go.textContent = was;
    });
  }

  document.getElementById('form').addEventListener('submit', function (e) {
    e.preventDefault();
    var said = box.value.trim();
    if (!said) { return; }
    send(nl.checked ? 'ask ' + said : said, said);
    box.value = '';
  });

  var chips = document.querySelectorAll('.chip');
  for (var i = 0; i < chips.length; i++) {
    chips[i].addEventListener('click', function () {
      var raw = this.getAttribute('data-raw');
      send(raw, raw);
    });
  }

  fetch('health').then(function (r) { return r.json(); }).then(function (d) {
    if (d.camera) { head.className = 'up'; }
  }).catch(function () {});
})();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    """One request. The server instance carries the forwarder and the limit."""

    server_version = "AsciiCamWeb/1.0"
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if not self._local():
            return
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/health":
            # Deliberately does not send the app a line. A health check that
            # cost an API call, or woke the render loop, would be a worse
            # problem than the one it diagnoses.
            self._json(200, {"ok": True,
                             "camera": self.server.forwarder.alive()})
        else:
            self._json(404, {"error": f"nothing at {path}"})

    def do_POST(self):
        if not self._local():
            return
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path != "/ask":
            self._json(404, {"error": f"nothing at {path}"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "unreadable Content-Length"})
            return
        if length > MAX_BODY:
            self._json(413, {"error": "that is too long to be a command"})
            return

        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            line = payload["line"]
        except (ValueError, TypeError, KeyError):
            self._json(400, {"error": 'expected JSON like {"line": "..."}'})
            return
        if not isinstance(line, str):
            self._json(400, {"error": "line must be text"})
            return

        line = line.strip()
        if not line:
            self._json(400, {"error": "nothing to send"})
            return

        if costs_money(line) and not self.server.limit.allow():
            logger.warning("Refusing an ask: over %d in %.0f s",
                           ASK_LIMIT, ASK_WINDOW)
            self._json(429, {"error": "too many asks in the last minute - "
                                      "every setting can still be typed by "
                                      "name, and asking works again shortly"})
            return

        try:
            reply = self.server.forwarder.send(line)
        except socket.timeout:
            self._json(504, {"error": "the camera took too long to answer"})
        except OSError as e:
            # The app not being up is the single likeliest failure here, and it
            # is not this process's fault, so say which of the two is missing.
            logger.error("Could not reach the app: %s", e)
            self._json(503, {"error": f"could not reach the camera: {e}"})
        else:
            logger.info("%s -> %r", line, reply.splitlines()[:1])
            self._json(200, {"line": line, "reply": reply})

    def _local(self):
        """Refuse and close on anything that is not on the house network."""
        peer = self.client_address[0]
        if is_local(peer):
            return True
        logger.warning("Refusing a request from %s", peer)
        self._json(403, {"error": "this camera only answers its own network"})
        return False

    def _json(self, status, payload):
        self._send(status, json.dumps(payload).encode("utf-8"),
                   "application/json")

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Nothing here is for anybody else, and a phone browser caching the
        # page across a version change is a support call waiting to happen.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        """Into the log, not onto stderr, so journalctl sees one stream."""
        logger.debug("%s %s", self.client_address[0], fmt % args)


class WebServer(ThreadingHTTPServer):
    """A LAN-bound listener, IPv4 only, holding the socket path it forwards to."""

    # Explicit, though it is the default: binding AF_INET is what keeps this off
    # the Pi's globally routable IPv6 address. See the module docstring.
    address_family = socket.AF_INET
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host, port, forwarder, limit=None):
        super().__init__((host, port), Handler)
        self.forwarder = forwarder
        self.limit = limit if limit is not None else AskLimit()


def serve(host="0.0.0.0", port=DEFAULT_PORT, socket_path=DEFAULT_SOCKET):
    """Build a server and hand it back, not yet serving."""
    return WebServer(host, port, Forwarder(socket_path))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="0.0.0.0",
                    help="address to bind (default every IPv4 interface)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--socket", default=os.environ.get(
        "ASCIICAM_SOCKET", DEFAULT_SOCKET),
        help="the running app's command socket")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        server = serve(args.host, args.port, args.socket)
    except OSError as e:
        print(f"Could not listen on {args.host}:{args.port}: {e}",
              file=sys.stderr)
        return 1

    if not server.forwarder.alive():
        # Not fatal. The camera restarts on its own and the page says so; a web
        # server that refused to start because the app was mid-restart would be
        # unreachable exactly when somebody wanted to know what was wrong.
        logger.warning("The camera is not listening on %s yet - serving "
                       "anyway", args.socket)

    logger.info("Serving the phone page on http://%s:%d/ (LAN only)",
                args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
