#!/usr/bin/env python3
"""
One page saying what every module in this app is for.

    python3 tools/module_map.py            # print it
    python3 tools/module_map.py --write    # regenerate docs/module-map.md
    python3 tools/module_map.py --check    # fail if that file is out of date

Written because the project reached twenty-one modules and seven thousand lines
of prose, and the answer to "what is this file for" had become "read it". The
summaries are each module's own first docstring line, read from the source
rather than retyped here, so this cannot drift into describing code that no
longer exists - the same argument that generates `help` and the tool schema
from SPECS instead of restating them.

What is NOT generated is the grouping. Which subsystem a module belongs to is a
statement about the architecture and has to be made by a person; a tool can
only check that the statement still covers every file, which --check does. A
module added without being placed is the drift this is here to catch, so it is
an error rather than an "ungrouped" bucket nobody would read.
"""

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "module-map.md"

# The architecture, as six subsystems and an entry point. Order is the order a
# frame travels: light in at the top, pixels out in the middle, and the ways a
# human changes what happens at the bottom.
GROUPS = (
    ("Entry point", "The process itself: argument parsing, the render loop, "
                    "and the wiring that connects everything below.",
     ("ascii_camera.py", "src/version.py")),
    ("Capture", "Getting frames off the camera and into the right shape.",
     ("src/camera.py", "src/image_processor.py")),
    ("ASCII", "Turning brightness into characters, and characters into colour.",
     ("src/ascii_art.py", "src/palettes.py", "src/window_plan.py")),
    ("Screen", "The HDMI terminal, and the stand-in for when there is none.",
     ("src/display.py", "src/headless.py")),
    ("Panel", "The 2.4 inch ILI9341 over SPI - a second, independent display.",
     ("src/lcd.py", "src/lcd_display.py", "src/lcd_worker.py",
      "src/lcd_splash.py")),
    ("Control", "Every setting, and every way a human reaches one.",
     ("src/render_config.py", "src/commands.py", "src/command_server.py",
      "src/web_server.py", "src/encoder.py")),
    ("Language", "Words in, a validated settings change out.",
     ("src/parser.py", "src/shortcuts.py", "src/asklog.py")),
)


def summary(path):
    """The module's own first docstring line, which is its index entry."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return f"(will not parse: {e})"
    doc = ast.get_docstring(tree) or ""
    for line in doc.splitlines():
        if line.strip():
            return line.strip()
    return "(no docstring)"


def every_module():
    """
    Every module that is part of the running app, entry point included.

    Two kinds of file are not modules and are skipped rather than counted:

      * Anything starting with a dot. Writing to the Pi through the SSHFS mount
        leaves macOS AppleDouble sidecars (`._camera.py` and friends) beside
        every file. They are filesystem debris, they are never synced, and
        listing them would bury the real answer under a duplicate of itself.
      * A test that has ended up in src/. That is a misplaced file rather than
        a subsystem, so it is named on stderr every run instead of being
        silently absorbed into the map - but it does not stop the map being
        generated, because policing the layout is not this tool's job.
    """
    found = {"ascii_camera.py"}
    for path in sorted((ROOT / "src").glob("*.py")):
        if path.name.startswith("."):
            continue
        if path.name.endswith("_test.py"):
            print(f"warning: src/{path.name} is a test in the source "
                  f"directory; tests live in tests/", file=sys.stderr)
            continue
        found.add(f"src/{path.name}")
    return found


def render():
    """The whole page, as text."""
    placed = {name for _, _, names in GROUPS for name in names}
    modules = every_module()          # once: it warns, and twice would nag
    missing = sorted(modules - placed)
    if missing:
        # A file nobody placed is exactly the drift this exists to catch, and a
        # map that quietly omitted it would be worse than no map.
        raise SystemExit(
            "These modules are not in any group in tools/module_map.py:\n  "
            + "\n  ".join(missing)
            + "\n\nAdd each to the subsystem it belongs to - deciding that is "
              "the point, and is not something this tool can do for you.")
    gone = sorted(placed - modules)
    if gone:
        raise SystemExit("These are grouped but no longer exist:\n  "
                         + "\n  ".join(gone))

    out = [
        "# Module map",
        "",
        "Every module in the running app, what it is for, and how big it is.",
        "",
        "**Generated - do not edit.** `python3 tools/module_map.py --write`",
        "rebuilds it, and `tests/module_map_test.py` fails if it is stale. Each",
        "summary is that module's own first docstring line, so this page cannot",
        "describe code that is no longer there.",
        "",
    ]
    total_lines = total_files = 0
    for title, blurb, names in GROUPS:
        out += [f"## {title}", "", blurb, "",
                "| Module | Lines | What it is for |",
                "|---|---:|---|"]
        for name in names:
            path = ROOT / name
            count = len(path.read_text(encoding="utf-8").splitlines())
            total_lines += count
            total_files += 1
            out.append(f"| `{name}` | {count} | {summary(path)} |")
        out.append("")
    out += [f"---", "",
            f"{total_files} modules, {total_lines:,} lines.", ""]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help=f"write {OUTPUT.relative_to(ROOT)}")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the written page is out of date")
    args = ap.parse_args(argv)

    page = render()
    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(page, encoding="utf-8")
        print(f"wrote {OUTPUT.relative_to(ROOT)}")
        return 0
    if args.check:
        if not OUTPUT.exists():
            print(f"{OUTPUT.relative_to(ROOT)} does not exist; "
                  "run --write", file=sys.stderr)
            return 1
        if OUTPUT.read_text(encoding="utf-8") != page:
            print(f"{OUTPUT.relative_to(ROOT)} is out of date; "
                  "run: python3 tools/module_map.py --write", file=sys.stderr)
            return 1
        print("module map is current")
        return 0
    print(page)
    return 0


if __name__ == "__main__":
    sys.exit(main())
