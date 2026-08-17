#!/usr/bin/env python3
"""
Type settings at a running ASCII camera.

    python3 tools/asciicam_cli.py                 # interactive
    python3 tools/asciicam_cli.py scheme green    # one command, then exit
    python3 tools/asciicam_cli.py help

Talks to the app over its Unix socket, so it drives whichever copy is already
running - including the systemd service, which has no terminal of its own and
cannot be typed at any other way. Nothing is applied here: lines go to the
render loop, which validates them and says what happened.

Type `help` for the settings, `show` for their current values, and Ctrl-D or
`quit` to leave. Quitting the client does not stop the camera.
"""

import argparse
import os
import socket
import sys

DEFAULT_SOCKET = "/home/rod/Projects/AsciiArt/asciicam.sock"

# The app terminates each reply with a NUL, so a multi-line answer - `help` is
# thirty-odd lines - can be read whole rather than guessed at by counting
# newlines or waiting for a timeout.
END = b"\x00"


def connect(path):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    sock.connect(path)
    return sock


def ask(sock, line):
    """Send one line, return the app's whole reply."""
    sock.sendall((line + "\n").encode("utf-8"))
    buffer = b""
    while END not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("the app closed the connection")
        buffer += chunk
    return buffer.split(END, 1)[0].decode("utf-8", "replace").rstrip("\n")


def interactive(sock):
    """A prompt, with line editing and history when readline is available."""
    try:
        import readline            # noqa: F401  - importing it is the effect
    except ImportError:
        pass

    print("Connected. `help` for the settings, `show` for their values, "
          "Ctrl-D to leave.")
    while True:
        try:
            line = input("ascii> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line in ("quit", "exit"):
            return 0
        if not line:
            continue
        try:
            reply = ask(sock, line)
        except (OSError, ConnectionError) as e:
            print(f"lost the app: {e}", file=sys.stderr)
            return 1
        if reply:
            print(reply)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="*",
                        help="a single command to send, instead of prompting")
    parser.add_argument("--socket", default=os.environ.get(
        "ASCIICAM_SOCKET", DEFAULT_SOCKET),
        help="path to the app's command socket")
    args = parser.parse_args(argv)

    try:
        sock = connect(args.socket)
    except OSError as e:
        print(f"Could not reach the camera on {args.socket}: {e}\n"
              "Is it running? Try: systemctl status ascii-camera.service",
              file=sys.stderr)
        return 1

    try:
        if args.command:
            reply = ask(sock, " ".join(args.command))
            if reply:
                print(reply)
            return 0
        return interactive(sock)
    except (OSError, ConnectionError) as e:
        print(f"lost the app: {e}", file=sys.stderr)
        return 1
    finally:
        sock.close()


if __name__ == "__main__":
    sys.exit(main())
