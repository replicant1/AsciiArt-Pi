"""
A local command channel into the running app.

The app spends its life inside a render loop, and the settings it owns may only
be changed from that loop's own thread - _adopt repaints the window, rebuilds
the ASCII generator and talks to the panel worker, none of which is safe from
anywhere else. So this does not apply anything. It accepts lines on a Unix
socket, hands each one to the loop, and waits for the loop to say what happened.

That indirection is the point rather than an inconvenience. The queue it feeds
is where a phone's HTTP handler will deliver utterances later; a web request and
a typed line become the same thing one step in, and the loop keeps its single
entry point.

Why a Unix socket and not a TCP port: it is a file, so the kernel's own
permissions decide who may connect, and nothing is reachable from the network at
all. The app usually runs as a systemd service with no terminal attached, which
rules out reading a command from stdin - and that is exactly the copy worth
being able to drive.

Each connection gets its own thread. An earlier version served one at a time,
reasoning that two people typing settings at one camera was not worth
supporting - which missed that one person's *interactive prompt* holds its
connection open for as long as it is on screen. A single idle client starved
every other, including one-shot commands, and the only symptom was a timeout.
Commands still cannot interleave where it matters: they are applied by the
render loop, one at a time, in the order it takes them off the queue.
"""

import logging
import os
import socket
import threading
from queue import Empty, Queue

logger = logging.getLogger(__name__)

# How long a client waits for the render loop to pick its line up and answer.
# The loop polls once per frame, and once per 50 ms when frozen, so this is
# generous by two orders of magnitude - it exists to stop a client hanging for
# ever against an app that has wedged, not to bound normal work.
REPLY_TIMEOUT = 5.0

# Lines longer than this are refused rather than buffered. Nothing legitimate
# comes close, and it stops a stuck client growing memory without limit.
MAX_LINE = 4096

# Connections served at once. An interactive prompt holds one for as long as it
# is open, so this is "how many shells may have the CLI up", not "how many
# commands at a time" - the render loop applies those one at a time regardless.
MAX_CLIENTS = 8


class CommandServer(threading.Thread):
    """Accepts typed lines on a Unix socket and queues them for the app."""

    def __init__(self, path, name="commands"):
        """
        Args:
            path: filesystem path for the socket. Created with mode 0600, so
                only the user running the app can talk to it.
        """
        super().__init__(name=name, daemon=True)
        self.path = path
        self.inbox = Queue()
        self._stopping = threading.Event()
        self._sock = None
        self._clients = []
        self.served = 0

    def start(self):
        """Bind and listen, then start accepting. Raises if it cannot bind."""
        # A socket file left behind by a killed process would make bind fail
        # with EADDRINUSE for ever. Removing it is only safe once nothing is
        # listening on it, which connecting is the way to find out - a live app
        # would accept, and the caller should be told rather than displaced.
        if os.path.exists(self.path):
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(0.5)
                probe.connect(self.path)
            except OSError:
                logger.info("Removing stale command socket at %s", self.path)
                os.unlink(self.path)
            else:
                probe.close()
                raise RuntimeError(
                    f"another instance is already listening on {self.path}")
            finally:
                probe.close()

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        os.chmod(self.path, 0o600)
        self._sock.listen(MAX_CLIENTS)
        # So the accept loop notices _stopping rather than blocking for ever.
        self._sock.settimeout(0.5)
        logger.info("Command socket listening on %s", self.path)
        super().start()
        return self

    def run(self):
        while not self._stopping.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                self._clients = [t for t in self._clients if t.is_alive()]
                continue
            except OSError:
                break

            self._clients = [t for t in self._clients if t.is_alive()]
            if len(self._clients) >= MAX_CLIENTS:
                # Refuse rather than queue: a client that is never served looks
                # exactly like an app that has stopped answering, which is the
                # confusion this whole change exists to remove.
                logger.warning("Refusing a command client: %d already "
                               "connected", len(self._clients))
                self._send(conn, "too many clients connected")
                try:
                    conn.close()
                except OSError:
                    pass
                continue

            # Its own thread, so an interactive prompt sitting open cannot stop
            # anything else being served.
            worker = threading.Thread(target=self._run_client, args=(conn,),
                                      name="command-client", daemon=True)
            self._clients.append(worker)
            worker.start()

        logger.info("Command server stopped after %d command(s)", self.served)

    def _run_client(self, conn):
        """
        One client, start to finish, on its own thread.

        Not called _handle. threading.Thread grew a private `_handle` attribute
        in Python 3.13, and a method of that name on a subclass is shadowed by
        it - so `target=self._handle` quietly passed a _ThreadHandle object
        instead of a function and every client thread died on arrival with
        "'_thread._ThreadHandle' object is not callable". Subclassing Thread
        means sharing its namespace; check a new private name against it.
        """
        try:
            self._serve(conn)
        except Exception as e:
            logger.error("Command connection failed: %s", e, exc_info=True)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _serve(self, conn):
        """Read lines from one client until it goes away."""
        conn.settimeout(1.0)
        buffer = b""
        while not self._stopping.is_set():
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return                      # client hung up
            buffer += chunk
            if len(buffer) > MAX_LINE:
                self._send(conn, "line too long")
                return
            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    self._send(conn, "")
                    continue
                self._send(conn, self._ask(line))

    def _ask(self, line):
        """Hand one line to the render loop and wait for its answer."""
        answer = Queue(maxsize=1)
        self.inbox.put((line, answer))
        self.served += 1
        try:
            return answer.get(timeout=REPLY_TIMEOUT)
        except Empty:
            # The loop is not draining. Say so plainly rather than leave the
            # client looking at nothing: on this hardware a wedged render loop
            # is a real possibility and the difference between "refused" and
            # "never answered" is worth being able to see.
            logger.error("No reply from the render loop for %r", line)
            return "(the app did not answer - is it still rendering?)"

    def _send(self, conn, text):
        """Reply, terminated so the client knows the answer is complete."""
        try:
            conn.sendall((text + "\n\x00").encode("utf-8"))
        except OSError:
            pass

    def take(self):
        """
        Everything waiting, as (line, answer queue) pairs. Never blocks.

        Called from the render loop once per pass, in the same place keys and
        the encoder are read, so a typed setting lands exactly where a keypress
        would and cannot arrive halfway through a frame.
        """
        pending = []
        while True:
            try:
                pending.append(self.inbox.get_nowait())
            except Empty:
                return pending

    def stop(self):
        """Stop listening and remove the socket file."""
        self._stopping.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self.is_alive():
            self.join(timeout=2.0)
        try:
            os.unlink(self.path)
        except OSError:
            pass
