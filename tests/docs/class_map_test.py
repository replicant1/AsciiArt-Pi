#!/usr/bin/env python3
"""
Check docs/class-overview.md still describes the classes that are there.

    python3 tests/docs/class_map_test.py

Same bargain as the module map: the page is only trustworthy because it is
generated, and "generated" only means something if something fails when the
committed copy stops matching. That is this.

It also holds one line that is not about staleness. Every class must have a
docstring, because the map's right-hand column is that docstring and a class
without one puts "(no docstring)" on a published page. That is a better outcome
than a wrong description, but it is not a good one, and the moment to notice is
when the class is written.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "docs"))

import class_map                                       # noqa: E402
from class_synopses import SYNOPSES, HIGHLIGHTS, DIAGRAMS  # noqa: E402
import module_map                                      # noqa: E402

PASSED = FAILED = 0


def check(name, got, want):
    global PASSED, FAILED
    if got == want:
        PASSED += 1
        print(f"  ok    {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}\n          got  {got!r}\n          want {want!r}")


print("the class map")
print("-------------")

page = class_map.render()

# Every class the app defines has to appear. Parsing the app a second way here
# rather than reusing the tool's own walk: a tool that skipped a module would
# otherwise agree with itself and both would be wrong.
import ast                                             # noqa: E402

found = set()
for path in sorted(list((ROOT / "src").rglob("*.py")) + [ROOT / "ascii_camera.py"]):
    if path.name.startswith(".") or path.name == "__init__.py":
        continue
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ClassDef):
            found.add(node.name)

# Matched as a table row, not as a name appearing somewhere on the page. A
# bare `Name` search passes when the name turns up inside another class's
# summary - "wraps `Forwarder`" would vouch for a Forwarder row that is not
# there - which is a completeness check that cannot detect the one thing it
# exists to detect.
rows = {line[6:].split("`")[0]
        for line in page.splitlines()
        if line.startswith("#### `")}
missing = sorted(name for name in found if name not in rows)
check("every class in the app has its own section", missing, [])
check("and no section is for something that no longer exists",
      sorted(rows - found), [])
check("and there are enough of them to be worth a page", len(found) > 10, True)

check("the committed page exists", class_map.OUTPUT.exists(), True)
check("and is what the tool produces right now",
      class_map.OUTPUT.read_text(encoding="utf-8") == page, True)

# The bases column is the reason this page says more than the module map, so
# it has to be right about the ones that matter most: what runs on its own
# thread is a fact about how the program behaves.
check("the threads are shown as threads",
      all(f"### `{name}` — `threading.Thread`" in page
          for name in ("LcdWorker", "CommandServer")), True)
check("and their base is named", page.count("`threading.Thread`"), 2)

# --- the half that is written by hand ---------------------------------------
#
# The page is only partly generated: the synopses come from class_synopses.py
# because "what is this class for" is not recoverable from the source. That
# makes two new ways to rot, neither of them visible on the page - a class
# added with no synopsis renders as "(no synopsis)", and a synopsis for a
# deleted class simply sits there reading as current.
check("every class has a hand-written synopsis",
      sorted(found - set(SYNOPSES)), [])
check("and no synopsis outlives its class",
      sorted(set(SYNOPSES) - found), [])
check("so none of them fell through to the placeholder",
      "(no synopsis)" in page, False)

# --- the diagram at the top --------------------------------------------------
#
# Each box carries only the members its synopsis turns on, and which those are
# is hand-picked in HIGHLIGHTS. That is a third way to rot: a member renamed in
# the source leaves a box naming something that no longer exists, and mermaid
# will happily draw it. So every highlighted name is looked up in the class's
# real members - methods, properties, NamedTuple fields and the attributes it
# assigns to self.
members = {}
for path in sorted(list((ROOT / "src").rglob("*.py")) + [ROOT / "ascii_camera.py"]):
    if path.name.startswith(".") or path.name == "__init__.py":
        continue
    for c in class_map.classes_in(path):
        members[c["name"]] = (set(c["methods"]) | set(c["properties"])
                              | set(c["fields"]) | set(c["attrs"]))

unknown = sorted(f"{cls}.{m}" for cls, picks in HIGHLIGHTS.items()
                 for m in picks if m not in members.get(cls, set()))
check("every highlighted member exists on its class", unknown, [])
check("and every class has a highlights entry",
      sorted(set(members) - set(HIGHLIGHTS)), [])
check("and no highlights entry outlives its class",
      sorted(set(HIGHLIGHTS) - set(members)), [])
check("every class appears in the diagram",
      sorted(n for n in members if f"class {n}" not in page), [])

# and prove it can fail, by running the same lookup over a doctored table
def highlight_faults(table):
    return sorted(f"{cls}.{m}" for cls, picks in table.items()
                  for m in picks if m not in members.get(cls, set()))

check("the highlight check passes the real table", highlight_faults(HIGHLIGHTS), [])
check("and fails one naming a member that was renamed away",
      highlight_faults({**HIGHLIGHTS, "RenderConfig": ["with_changes", "gone"]}),
      ["RenderConfig.gone"])
check("and fails one naming a class that no longer exists",
      highlight_faults({**HIGHLIGHTS, "Vanished": ["anything"]}),
      ["Vanished.anything"])

# --- the edges in the diagram ------------------------------------------------
#
# The relationships are derived, not listed, so the risk is not that they rot
# but that the derivation is wrong in a way that reads as authoritative. These
# check the three kinds against the source a second way: an inheritance edge
# has to be in the class statement, a `holds` edge has to be a name the class
# assigns to self, and the two kinds must not overlap.
import re                                               # noqa: E402

edges = {"inherit": set(), "holds": set(), "uses": set()}
for line in page.splitlines():
    line = line.strip()
    # written base-first: `Base <|-- Child`
    if m := re.match(r"^([\w.]+) <\|-- (\w+)$", line):
        edges["inherit"].add((m.group(2), m.group(1)))
    elif m := re.match(r"^(\w+) [*o]-- (\w+)$", line):
        edges["holds"].add(m.groups())
    elif m := re.match(r"^(\w+) \.\.> (\w+)$", line):
        edges["uses"].add(m.groups())

check("the diagram has edges of all three kinds",
      sorted(k for k, v in edges.items() if not v), [])

by_name = {}
for path in sorted(list((ROOT / "src").rglob("*.py")) + [ROOT / "ascii_camera.py"]):
    if path.name.startswith(".") or path.name == "__init__.py":
        continue
    for c in class_map.classes_in(path):
        by_name[c["name"]] = c

# --- what a box carries ------------------------------------------------------
#
# The member lists used to appear in the diagram and again under it, and the
# two drifted: thirty members were drawn in a box and mentioned nowhere in the
# text. They are in one place now - the box - and the description is prose. So
# what has to be checked is that a box draws a class's whole public surface,
# and nothing that is not a member of it.
drawn = {}
for line in page.splitlines():
    if line.startswith("    class ") and line.rstrip().endswith("{"):
        current = line.strip()[len("class "):-1].strip()
        drawn.setdefault(current, [])
    elif line.startswith("        +"):
        token = line.strip()[1:]
        token = token.split()[-1] if " " in token else token
        drawn[current].append(token.rstrip("()"))

not_a_member, missing_surface = [], []
for name, shown in drawn.items():
    row = by_name.get(name)
    if row is None:                       # an <<external>> base, which has none
        continue
    real = (set(row["fields"]) | set(row["attrs"])
            | set(row["properties"]) | set(row["methods"]))
    not_a_member += [f"{name}.{m}" for m in shown if m not in real]
    surface = set(row["fields"]) | set(row["properties"]) | set(row["methods"])
    missing_surface += [f"{name}.{m}" for m in surface if m not in shown]

check("every member a box draws is a real member of that class",
      sorted(set(not_a_member)), [])
check("and a box draws the class's whole public surface",
      sorted(set(missing_surface)), [])
check("and the descriptions no longer repeat it",
      [k for k in ("**Methods:**", "**Properties:**", "**Fields:**")
       if k in page], [])

# and prove both can fail, by running the same comparison over a doctored box
def box_faults(name, shown):
    row = by_name[name]
    real = (set(row["fields"]) | set(row["attrs"])
            | set(row["properties"]) | set(row["methods"]))
    surface = set(row["fields"]) | set(row["properties"]) | set(row["methods"])
    return (sorted(f"{name}.{m}" for m in shown if m not in real),
            sorted(f"{name}.{m}" for m in surface if m not in shown))

_real = drawn["AsciiArt"]
check("the box check passes the box as drawn", box_faults("AsciiArt", _real),
      ([], []))
check("and fails one drawing a member the class does not have",
      box_faults("AsciiArt", _real + ["invented"])[0], ["AsciiArt.invented"])
check("and fails one that leaves a method out",
      box_faults("AsciiArt", [m for m in _real if m != "posterise"])[1],
      ["AsciiArt.posterise"])

# --- the split into three diagrams -------------------------------------------
#
# The page opens with three diagrams instead of one, and the claim it makes
# about them is that the split costs nothing: every relationship in the app
# has both ends inside one diagram. That is true today and would stop being
# true the moment somebody adds a reference across two of them - silently, in
# the source, with nothing on the page to show a relationship had gone
# missing. So it is checked rather than claimed.

placed = [c for _, _, members in DIAGRAMS for c in members]
check("every class is in a diagram",
      sorted(set(by_name) - set(placed)), [])
check("and no diagram names a class that does not exist",
      sorted(set(placed) - set(by_name)), [])

spanning = []
for name, c in by_name.items():
    others = ((c["stored"] | c["named"]) & set(by_name)) - {name}
    for other in sorted(others):
        together = any(name in members and other in members
                       for _, _, members in DIAGRAMS)
        if not together:
            spanning.append(f"{name} -> {other}")
check("and no relationship spans two of them", sorted(spanning), [])

# and prove that last one can fail, on a split deliberately cut in the wrong place
_BAD = [("a", "", ["MainRenderLooper"]), ("b", "", ["CameraCapture"])]
_span = [f"{n} -> {o}" for n, c in by_name.items()
         for o in sorted(((c["stored"] | c["named"]) & set(by_name)) - {n})
         if not any(n in m and o in m for _, _, m in _BAD)]
check("the spanning check notices a split that cuts an edge",
      "MainRenderLooper -> CameraCapture" in _span, True)

wrong_inherit = sorted(f"{child} --|> {base}" for child, base in edges["inherit"]
                       if base not in by_name.get(child, {}).get("bases", []))
check("every inheritance edge is in the class statement", wrong_inherit, [])

wrong_holds = sorted(f"{owner} o-- {other}" for owner, other in edges["holds"]
                     if other not in by_name.get(owner, {}).get("stored", set()))
check("every diamond is a name assigned to self", wrong_holds, [])

# A filled diamond claims the owner builds the part. That is checkable: the
# name has to be *called* in the expression assigned to self, not merely
# mentioned in it.
filled = {(a, b) for a, b in edges["holds"]
          if f"    {a} *-- {b}" in page}
wrong_built = sorted(f"{a} *-- {b}" for a, b in filled
                     if b not in by_name.get(a, {}).get("built", set()))
check("and every filled diamond is a part the owner constructs", wrong_built, [])
check("no hollow diamond claims a part the owner builds",
      sorted(f"{a} o-- {b}" for a, b in edges["holds"] - filled
             if b in by_name.get(a, {}).get("built", set())), [])

both = sorted(f"{a} -> {b}" for a, b in edges["holds"] & edges["uses"])
check("and no pair is drawn as both holding and merely using", both, [])

check("every edge joins classes the diagram actually draws",
      sorted({n for pair in
              (edges["holds"] | edges["uses"]) for n in pair}
             - set(by_name)), [])

# and prove the holds check can fail
check("the holds check would notice an invented edge",
      sorted(f"{o} --> {t}" for o, t in {("AskLog", "ILI9341")}
             if t not in by_name.get(o, {}).get("stored", set())),
      ["AskLog --> ILI9341"])

# A synopsis is one or two ideas, not a tour of the method list directly above
# it. Length is the only part of that a test can hold: the rest is editorial.
overlong = sorted(name for name, text in SYNOPSES.items()
                  if len(" ".join(text.split())) > 420)
check("and none has grown into an essay", overlong, [])
check("nor been left as a stub",
      sorted(n for n, t in SYNOPSES.items()
             if len(" ".join(t.split())) < 80), [])

# Length alone did not stop them being written as one dense sentence held
# together by colons and dashes, which is how the first draft read. Three
# sentences is the floor: it is not a measure of quality, but it does rule out
# the compression that made several of them unreadable.
terse = sorted(n for n, t in SYNOPSES.items()
               if " ".join(t.split()).count(".") < 3)
check("and reads as prose rather than one compressed sentence", terse, [])

# Every class carries its own summary, so no page entry can be invented here.
no_docstring = []
for path in sorted(list((ROOT / "src").rglob("*.py")) + [ROOT / "ascii_camera.py"]):
    if path.name.startswith(".") or path.name == "__init__.py":
        continue
    for found_class in class_map.classes_in(path):
        if found_class["summary"] == "(no docstring)":
            no_docstring.append(f"{path.name}:{found_class['name']}")
check("every class says what it is for", no_docstring, [])

too_long = []
for path in sorted(list((ROOT / "src").rglob("*.py")) + [ROOT / "ascii_camera.py"]):
    if path.name.startswith(".") or path.name == "__init__.py":
        continue
    too_long += [f"{path.name}:{c['name']}" for c in class_map.classes_in(path)
                 if len(c["summary"]) > 100]
check("and says it on one line", too_long, [])

# The page is organised by the three diagrams, not by the package tree - each
# class is described beneath the diagram it appears in. The module map still
# owns the package grouping; this page deliberately does not repeat it.
check("every diagram is a heading on the page",
      [t for t, _, _ in DIAGRAMS if f"## {t}" not in page], [])
check("and the package names are not headings here",
      [t for t, _, _ in module_map.packages() if f"## {t}" in page], [])

# Each class is described once, under the first diagram that contains it, and
# the descriptions under a diagram run in alphabetical order - which is the
# only order a reader can predict when the grouping is no longer the code's.
described, out_of_order, twice = [], [], []
for title, _, _ in DIAGRAMS:
    after = page.split(f"## {title}", 1)[1]
    block = after.split("\n## ", 1)[0]
    names = [l[6:].split("`")[0] for l in block.splitlines()
             if l.startswith("#### `")]
    if names != sorted(names):
        out_of_order.append(f"{title}: {names}")
    twice += [n for n in names if n in described]
    described += names
check("the descriptions under each diagram are in alphabetical order",
      out_of_order, [])
check("and no class is described twice", sorted(twice), [])
check("and every class is described somewhere",
      sorted(set(by_name) - set(described)), [])

# and prove the staleness check can fail
result = subprocess.run(
    [sys.executable, str(ROOT / "tools" / "docs" / "class_map.py"), "--check"],
    capture_output=True, text=True)
check("--check passes when the page is current", result.returncode, 0)

original = class_map.OUTPUT.read_text(encoding="utf-8")
try:
    class_map.OUTPUT.write_text(original + "\nstale\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "docs" / "class_map.py"), "--check"],
        capture_output=True, text=True)
    check("and fails when it is not", result.returncode, 1)
    check("saying how to fix it", "--write" in result.stderr, True)
finally:
    class_map.OUTPUT.write_text(original, encoding="utf-8")

print(f"\n{'-' * 60}\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
