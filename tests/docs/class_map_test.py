#!/usr/bin/env python3
"""
Check docs/class-map.md still describes the classes that are actually there.

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
rows = {line.split("|")[1].strip().strip("`")
        for line in page.splitlines()
        if line.startswith("| `")}
missing = sorted(name for name in found if name not in rows)
check("every class in the app has its own row", missing, [])
check("and no row is for something that no longer exists",
      sorted(rows - found), [])
check("and there are enough of them to be worth a page", len(found) > 10, True)

check("the committed page exists", class_map.OUTPUT.exists(), True)
check("and is what the tool produces right now",
      class_map.OUTPUT.read_text(encoding="utf-8") == page, True)

# The bases column is the reason this page says more than the module map, so
# it has to be right about the ones that matter most: what runs on its own
# thread is a fact about how the program behaves.
check("the threads are shown as threads",
      all(f"| `{name}` |" in page for name in ("LcdWorker", "CommandServer")),
      True)
check("and their base is named", page.count("`threading.Thread`"), 2)

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

# The grouping is module_map's, read from the package tree. Sharing it is the
# point: two pages disagreeing about what the subsystems are would be worse
# than either page not existing.
check("it groups by the same packages the module map uses",
      [title for title, _, _ in module_map.packages()],
      [title for title in ("Capture", "Art", "HDMI", "LCD", "Control",
                           "Language")])
check("and every one of those appears as a heading",
      [t for t, _, _ in module_map.packages() if f"## {t}" not in page], [])

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
