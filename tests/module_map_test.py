#!/usr/bin/env python3
"""
Check docs/module-map.md still describes the code that is actually there.

    python3 tests/module_map_test.py

The map's whole claim is that it cannot drift, because every summary is read
from the module's own docstring. That claim is only true if the committed page
is regenerated when the code changes - so this fails when it is not, which is
the difference between a generated file and a file that was generated once.

It also fails when a module is added without being placed in a subsystem.
Deciding where a new file belongs is an architectural statement and no tool can
make it; what a tool can do is refuse to let it go unmade.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

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


print("the module map")
print("--------------")

page = module_map.render()

check("every module in the app is in a group",
      module_map.every_module() - {n for _, _, names in module_map.GROUPS
                                   for n in names}, set())
check("and every grouped module still exists",
      {n for _, _, names in module_map.GROUPS for n in names}
      - module_map.every_module(), set())

check("the committed page exists", module_map.OUTPUT.exists(), True)
check("and is what the tool produces right now",
      module_map.OUTPUT.read_text(encoding="utf-8") == page, True)

# The summaries are the module's own words, not a copy kept in step by hand.
sample = module_map.ROOT / "src" / "shortcuts.py"
first_line = module_map.summary(sample)
check("a summary is read from the source",
      first_line in page and first_line
      in sample.read_text(encoding="utf-8"), True)

# One line each: an index entry that wraps is not an index entry. 100 leaves
# room for the longest module path in the table without folding.
too_long = [name for _, _, names in module_map.GROUPS for name in names
            if len(module_map.summary(module_map.ROOT / name)) > 100]
check("every summary fits on one line", too_long, [])

# and prove the staleness check can actually fail
result = subprocess.run(
    [sys.executable, str(ROOT / "tools" / "module_map.py"), "--check"],
    capture_output=True, text=True)
check("--check passes when the page is current", result.returncode, 0)

original = module_map.OUTPUT.read_text(encoding="utf-8")
try:
    module_map.OUTPUT.write_text(original + "\nstale\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "module_map.py"), "--check"],
        capture_output=True, text=True)
    check("and fails when it is not", result.returncode, 1)
    check("saying how to fix it", "--write" in result.stderr, True)
finally:
    module_map.OUTPUT.write_text(original, encoding="utf-8")

print(f"\n{'-' * 60}\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
