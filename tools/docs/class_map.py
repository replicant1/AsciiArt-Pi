#!/usr/bin/env python3
"""
One page saying what every class in this app is, and what it inherits.

    python3 tools/docs/class_map.py            # print it
    python3 tools/docs/class_map.py --write    # regenerate docs/class-map.md
    python3 tools/docs/class_map.py --check    # fail if that file is out of date

The module map answers "what is this file for". This answers the question one
level down, which the module map cannot: what are the *things*, and how many of
them are there. Twenty-nine classes across twenty-one modules is not obvious
from either the file names or the directory tree.

It also shows what each class inherits, which the source only tells you if you
open all twenty-one files. Three of these are threads and one is an HTTP
handler; that is a fact about how the program behaves - what may block, what
needs a lock - and it is now on one line instead of spread across the code.

Read by parsing rather than importing, deliberately. Half these modules need
hardware or third-party packages that only exist on the Pi (spidev, picamera2,
lgpio, curses), so anything that imported them could only ever run in one
place. ast.parse runs anywhere, which is also why the summaries can be trusted:
nothing here executes the code it describes.

The grouping is not defined here. It comes from tools/docs/module_map.py, which
reads it from the package tree - one statement of the architecture, in the one
place that already owns it.
"""

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from module_map import ENTRY, ROOT, packages, summary   # noqa: E402

OUTPUT = ROOT / "docs" / "class-map.md"


def _name(node):
    """Render a base class or decorator back to roughly what was written."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _name(node.func)
    if isinstance(node, ast.Subscript):
        return _name(node.value)
    return ast.unparse(node) if hasattr(ast, "unparse") else "?"


def classes_in(path):
    """
    Every top-level class in one module, in the order it is written.

    Nested classes are skipped. There are none in the app today, and the ones
    that turn up in tests are stand-ins whose shape is nobody's business but
    the test's.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        doc = ast.get_docstring(node) or ""
        first = next((line.strip() for line in doc.splitlines() if line.strip()),
                     "(no docstring)")
        bases = [_name(b) for b in node.bases]
        decorators = [f"@{_name(d)}" for d in node.decorator_list]
        methods = [n.name for n in node.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and not n.name.startswith("_")]
        found.append({
            "name": node.name,
            "module": path.name,
            "bases": bases or decorators or [],
            "methods": len(methods),
            "summary": first,
        })
    return found


def render():
    """The whole page, as text."""
    groups = ((("Entry point"), list(ENTRY)),) + tuple(
        (title, mods) for title, _, mods in packages())

    out = [
        "# Class map",
        "",
        "Every class in the running app: where it lives, what it inherits, how",
        "much surface it has, and what it is for.",
        "",
        "**Generated - do not edit.** `python3 tools/docs/class_map.py --write`",
        "rebuilds it, and `tests/docs/class_map_test.py` fails if it is stale.",
        "Each summary is the class's own first docstring line.",
        "",
        "`Base` is what the class inherits, or its decorator when that is the",
        "more useful fact - a `@dataclass` and a `NamedTuple` behave nothing",
        "alike, and neither is an ordinary class. `Methods` counts public ones",
        "only, so it reads as surface rather than size.",
        "",
    ]
    total = 0
    for title, modules in groups:
        rows = []
        for name in modules:
            path = ROOT / name
            if path.name == "__init__.py":
                continue
            for found in classes_in(path):
                rows.append(found)
        if not rows:
            continue
        out += [f"## {title}", "",
                "| Class | In | Base | Methods | What it is for |",
                "|---|---|---|---:|---|"]
        for row in rows:
            total += 1
            base = ", ".join(f"`{b}`" for b in row["bases"]) or "—"
            out.append(f"| `{row['name']}` | `{row['module']}` | {base} "
                       f"| {row['methods']} | {row['summary']} |")
        out.append("")

    out += ["---", "", f"{total} classes.", ""]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    page = render()
    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(page, encoding="utf-8")
        print(f"wrote {OUTPUT.relative_to(ROOT)}")
        return 0
    if args.check:
        if not OUTPUT.exists():
            print(f"{OUTPUT.relative_to(ROOT)} does not exist; run --write",
                  file=sys.stderr)
            return 1
        if OUTPUT.read_text(encoding="utf-8") != page:
            print(f"{OUTPUT.relative_to(ROOT)} is out of date; run: "
                  "python3 tools/docs/class_map.py --write", file=sys.stderr)
            return 1
        print("class map is current")
        return 0
    print(page)
    return 0


if __name__ == "__main__":
    sys.exit(main())
