#!/usr/bin/env python3
"""
One page saying what every class in this app is, and what it inherits.

    python3 tools/docs/class_map.py            # print it
    python3 tools/docs/class_map.py --write    # regenerate docs/class-overview.md
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

This page is no longer grouped by package. It is organised around three class
diagrams, and each class is described beneath the one it appears in, in
alphabetical order. The package tree is still the module map's business and is
not repeated here - what this page groups by is what a reader is trying to
understand, which is not always where the code happens to live.
"""

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from module_map import ENTRY, ROOT, packages, summary   # noqa: E402
from class_synopses import SYNOPSES, HIGHLIGHTS, DIAGRAMS  # noqa: E402

OUTPUT = ROOT / "docs" / "class-overview.md"


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
        methods, properties = [], []
        for n in node.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if n.name.startswith("_"):
                continue
            is_property = any(_name(d) == "property" for d in n.decorator_list)
            (properties if is_property else methods).append(n.name)
        fields = {n.target.id: ast.unparse(n.annotation)
                  for n in node.body
                  if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
        # What a method hands back, and what a local name was built from, so
        # that `self.lcd = self._start_lcd()` is recognised as ownership. The
        # first version followed only `self.x = Klass(...)`, and reported two
        # parts this class builds and keeps for the whole run as though it
        # merely mentioned them.
        # Locals are tracked per method, never across the class. Sharing one map
        # confused `self.display = display` in __init__, where `display` is a
        # parameter, with an unrelated local of the same name in _start_lcd -
        # and reported that this class composes an LcdDisplay it never keeps.
        built_in = {}                      # method name -> {local: class built}
        yields = {}                        # method name -> {class returned}
        for fn in node.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            here = {}
            for step in ast.walk(fn):
                if not (isinstance(step, ast.Assign) and len(step.targets) == 1
                        and isinstance(step.targets[0], ast.Name)):
                    continue
                # Any construction anywhere in the assigned expression, not
                # only a bare `Klass(...)`: this app writes
                # `server = CommandServer(path).start()`, where the outermost
                # call is `.start`, and the first version saw nothing at all.
                for call in ast.walk(step.value):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                        here[step.targets[0].id] = call.func.id
                        break
            built_in[fn.name] = here
            for step in ast.walk(fn):
                if isinstance(step, ast.Return) and step.value is not None:
                    if isinstance(step.value, ast.Name) and step.value.id in here:
                        yields.setdefault(fn.name, set()).add(here[step.value.id])
                    else:
                        for call in ast.walk(step.value):
                            if (isinstance(call, ast.Call)
                                    and isinstance(call.func, ast.Name)):
                                yields.setdefault(fn.name, set()).add(call.func.id)
                                break

        attrs, stored, built = set(), set(), set()
        for fn in node.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            locals_built = built_in.get(fn.name, {})
            for inner in ast.walk(fn):
              if isinstance(inner, ast.Assign):
                for target in inner.targets:
                    if (isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"):
                        # A name that is *called* in the assigned expression is
                        # one this class builds, so the part cannot outlive the
                        # whole: composition. A name merely stored is aggregation.
                        called = {c.func.id for c in ast.walk(inner.value)
                                  if isinstance(c, ast.Call)
                                  and isinstance(c.func, ast.Name)}
                        # `self.x = self._helper()` owns whatever _helper builds
                        for call in ast.walk(inner.value):
                            if (isinstance(call, ast.Call)
                                    and isinstance(call.func, ast.Attribute)
                                    and isinstance(call.func.value, ast.Name)
                                    and call.func.value.id == "self"):
                                for made in yields.get(call.func.attr, ()):
                                    stored.add(made)
                                    built.add(made)
                        for sub in ast.walk(inner.value):
                            if isinstance(sub, ast.Name):
                                # `self.x = local` where local was built here
                                if sub.id in locals_built:
                                    stored.add(locals_built[sub.id])
                                    built.add(locals_built[sub.id])
                                stored.add(sub.id)
                                if sub.id in called:
                                    built.add(sub.id)
        named = {s.id for s in ast.walk(node) if isinstance(s, ast.Name)}
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Assign):
                continue
            for target in inner.targets:
                if (isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and not target.attr.startswith("_")):
                    attrs.add(target.attr)
        found.append({
            "fields": fields,
            "stored": stored,
            "built": built,
            "named": named,
            "attrs": sorted(attrs),
            "name": node.name,
            "module": path.name,
            "bases": bases or decorators or [],
            "methods": methods,
            "properties": properties,
            "summary": first,
        })
    return found


def members_of(row):
    """
    Everything a box carries: the class's whole public surface, plus any
    attribute worth naming.

    The full surface, because the description below is prose now and no longer
    lists it - the diagram is the only place a reader can see what a class
    offers. Attributes are the exception: `MainRenderLooper` assigns nineteen
    of them to `self`, so HIGHLIGHTS names the few that carry meaning.

    Returned as (kind, name) pairs in UML's order - state before behaviour.
    """
    picked = HIGHLIGHTS.get(row["name"], [])
    out = [("field", n) for n in row["fields"]]
    out += [("attr", n) for n in row["attrs"] if n in picked]
    out += [("prop", n) for n in row["properties"]]
    out += [("method", n) for n in row["methods"]]
    return out


def relationships(rows):
    """
    Inheritance and reference edges, read from the source rather than listed.

    Three kinds, and the distinction is mechanical rather than a judgement:

      --|>  inheritance, straight from the class statement.
      -->   one class stores another on `self`, so it holds a reference for
            as long as it lives.
      ..>   one class names another without keeping it - raising it, returning
            it, constructing it and handing it straight on.

    A collaborator that arrives as a constructor argument does not appear,
    because the class never names its type: `MainRenderLooper` is handed a
    display and never says which kind. Those are the edges the scenarios draw,
    and this diagram deliberately does not guess at them.
    """
    names = {row["name"] for row in rows}
    inherits, holds, uses, external = [], [], [], []
    for row in rows:
        for base in row["bases"]:
            if base.startswith("@"):
                continue
            inherits.append((row["name"], base))
            if base not in names and base not in external:
                external.append(base)
        for other in sorted(row["holds"]):
            holds.append((row["name"], other))
        for other in sorted(row["uses"]):
            uses.append((row["name"], other))
    return inherits, holds, uses, external


def one_diagram(rows, members):
    """One mermaid block: the named classes, and every edge between them."""
    # In the order the split lists them, not the order the packages do: the
    # layout follows declaration order, and listing collaborators together is
    # what keeps their edges short.
    by_name = {r["name"]: r for r in rows}
    inside = [by_name[n] for n in members if n in by_name]
    keep = set(members)
    # ELK routes edges orthogonally - every line runs horizontally or
    # vertically and turns at right angles - where the default renderer draws
    # free curves that sweep across the diagram and are hard to follow back to
    # their ends.
    lines = ["```mermaid",
             "---",
             "config:",
             "  layout: elk",
             "---",
             "classDiagram",
             "    direction TB",
             ""]

    # Base classes first, so the layout ranks them above their subclasses and
    # generalisation reads upward, the way a class diagram is meant to. It also
    # keeps their edges short: declared last, they landed mid-diagram and their
    # arrows crossed everything between.
    externals = []
    for row in inside:
        for base in row["bases"]:
            if not base.startswith("@") and base not in keep and base not in externals:
                externals.append(base)
    for base in externals:
        lines += [f"    class {base} {{", "        <<external>>", "    }"]
    lines.append("")

    for row in inside:
        shown = members_of(row)
        if not shown:
            lines.append(f"    class {row['name']}")
        else:
            lines.append(f"    class {row['name']} {{")
            for kind, member in shown:
                if kind == "method":
                    lines.append(f"        +{member}()")
                elif kind == "field":
                    lines.append(f"        +{row['fields'][member]} {member}")
                else:
                    lines.append(f"        +{member}")
            lines.append("    }")
    lines.append("")
    # Written base-first. `Base <|-- Child` is the same relationship as
    # `Child --|> Base`, but it ranks the base above its subclasses, which is
    # how a class diagram is traditionally read - generalisation points up.
    for row in inside:
        for base in row["bases"]:
            if not base.startswith("@"):
                lines.append(f"    {base} <|-- {row['name']}")
    for row in inside:
        for other in sorted(row["holds"] & keep & row["built"]):
            lines.append(f"    {row['name']} *-- {other}")
        for other in sorted((row["holds"] & keep) - row["built"]):
            lines.append(f"    {row['name']} o-- {other}")
    for row in inside:
        for other in sorted(row["uses"] & keep):
            lines.append(f"    {row['name']} ..> {other}")
    lines.append("```")
    return lines


def diagram(rows):
    """The three diagrams that open the page, with a word on each."""
    out = ["## How they relate", "",
           "Three diagrams rather than one. The split cuts no relationships -",
           "every edge in the app has both ends inside one of them - and only",
           "`MainRenderLooper` appears twice, because every route arrives there.",
           "",
           "`--|>` is inheritance, straight from the class statement. `-->` means",
           "one class stores another on `self` and holds it for as long as it",
           "lives. `..>` means it names another without keeping it - raising it,",
           "returning it, or building it and handing it straight on. All three are",
           "read from the source, so none of them can drift.",
           "",
           "A collaborator that arrives as a constructor argument has no edge,",
           "because the class never names its type: `MainRenderLooper` is handed a",
           "display and never says which kind. Those are the edges a scenario",
           "draws, and these diagrams do not guess at them.",
           "",
           "Each box carries only the members its synopsis turns on; for the whole",
           "surface of a class, read its section below.",
           ""]
    for number, (title, blurb, members) in enumerate(DIAGRAMS, start=1):
        out += [f"### {title}", ""] + paragraph(blurb) + [""]
        out += one_diagram(rows, members)
        out += ["", f"**Fig {number}: {title}**", ""]
    return out


def paragraph(text, width=76):
    """A synopsis reflowed to the width the rest of docs/ is written at."""
    words = " ".join(text.split()).split(" ")
    lines, line = [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


def section(row):
    """
    One class: its heading, its own first docstring line, and its synopsis.

    No member lists. They were here and in the diagram both, and keeping two
    renderings of one fact in step was work with nothing to show for it. The
    diagram carries the whole public surface now, and this is prose.
    """
    base = ", ".join(f"`{n}`" for n in row["bases"])
    heading = f"#### `{row['name']}`"
    if base:
        heading += f" — {base}"
    return ([heading, "", f"*{row['module']}* — {row['summary']}", ""]
            + paragraph(SYNOPSES.get(row["name"], "(no synopsis)")) + [""])


def render():
    """The whole page, as text."""
    groups = ((("Entry point"), list(ENTRY)),) + tuple(
        (title, mods) for title, _, mods in packages())

    every = []
    for _, modules in groups:
        for name in modules:
            path = ROOT / name
            if path.name != "__init__.py":
                every += classes_in(path)
    known = {row["name"] for row in every}
    for row in every:
        row["holds"] = {n for n in row["stored"] if n in known and n != row["name"]}
        row["uses"] = {n for n in row["named"]
                       if n in known and n != row["name"]} - row["holds"]
    by_name = {row["name"]: row for row in every}

    out = [
        "# Class overview",
        "",
        "Every class in the running app: what it offers, and the one or two",
        "ideas worth carrying away about it. The page is organised around three",
        "diagrams, and each class is described beneath the one it appears in.",
        "",
        "**Partly generated.** The diagrams, the headings and the public surface",
        "are read from the source by `python3 tools/docs/class_map.py --write`,",
        "so they cannot drift. The synopses are written by hand in",
        "`tools/docs/class_synopses.py`, because what a class is *for* is a",
        "judgement about the design rather than a fact recoverable from it.",
        "`tests/docs/class_map_test.py` fails if the page is stale, if a class",
        "has no synopsis, or if a synopsis outlives its class.",
        "",
        "A synopsis is deliberately not an inventory of the members listed above",
        "it. It is meant to be small enough to hold in mind while reading a",
        "scenario or the architecture.",
        "",
        "**A box carries a class's whole public surface** - its fields, its",
        "properties and its methods - so the diagram is where to look for what a",
        "class offers, and the paragraph beneath it is prose rather than a second",
        "copy of the same list. Attributes are the exception: `MainRenderLooper`",
        "assigns nineteen of them to `self`, so only the few that carry meaning",
        "are drawn.",
        "",
        "Three kinds of arrow, told apart by their shaft and their head:",
        "",
        "| Arrow | Means |",
        "|---|---|",
        "| Solid shaft, hollow triangle | **Inheritance.** The triangle points at "
        "the base class, which is drawn above its subclasses. |",
        "| Solid shaft, filled diamond | **Composition.** The class builds the "
        "part itself and holds it, so the part cannot outlive the whole. The "
        "diamond sits at the owner. |",
        "| Solid shaft, hollow diamond | **Aggregation.** The class holds a part "
        "it did not build, which could outlive it. |",
        "| Dotted shaft, open arrowhead | **Dependency.** The class mentions "
        "another without keeping it - raising it, returning it, or building it "
        "and handing it straight on. |",
        "",
        "`MainRenderLooper` shows the contrast worth having. It **builds and**",
        "**owns** the camera and the image processor, so those are diamonds; it",
        "merely **names** `LcdWorker`, so that one is dotted.",
        "",
        "No hollow diamonds appear on any of the three diagrams, and that is a",
        "fact about the derivation rather than about the app. Aggregation here",
        "means a part handed in as a constructor argument, and a class never",
        "names the type of what it is given - so those relationships are",
        "invisible to a parser and are left to the scenarios to draw.",
        "",
        "All three are read from the source, so none of them can drift. A",
        "collaborator that arrives as a constructor argument has no arrow at all,",
        "because the class never names its type - `MainRenderLooper` is handed a",
        "display and never says which kind. Those are the edges a scenario draws.",
        "",
    ]

    described = set()
    for number, (title, blurb, members) in enumerate(DIAGRAMS, start=1):
        out += [f"## {title}", ""] + paragraph(blurb) + [""]
        out += one_diagram(every, members)
        out += ["", f"**Fig {number}: {title}**", ""]
        fresh = sorted(n for n in members if n not in described)
        repeated = sorted(n for n in members if n in described)
        if repeated:
            names = ", ".join(f"[`{n}`](#{n.lower()})" for n in repeated)
            out += [f"{names} appears here too, and is described above.", ""]
        out += ["### The classes in this diagram", ""]
        for name in fresh:
            out += section(by_name[name])
            described.add(name)

    out += ["---", "", f"{len(every)} classes.", ""]
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
