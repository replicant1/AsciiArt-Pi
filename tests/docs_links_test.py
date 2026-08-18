#!/usr/bin/env python3
"""
Check every relative link between the documents still goes somewhere.

    python3 tests/docs_links_test.py

The README used to be one 2,369-line file, so a cross-reference could not
break: everything was in the same document. Splitting it into a front page and
nine topic files traded that for something readable, and this is the price -
now a heading can be renamed in one file and silently orphan a link in another.

Checks relative links only. External URLs are somebody else's uptime and would
make this need a network, which a test that runs on the Pi should not.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASSED = FAILED = 0


def check(name, got, want):
    global PASSED, FAILED
    if got == want:
        PASSED += 1
        print(f"  ok    {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}\n          got  {got!r}\n          want {want!r}")


def anchor(heading):
    """GitHub's own rule: lower case, punctuation dropped, spaces to hyphens."""
    text = heading.strip().lstrip("#").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text)


def documents():
    """Every markdown file, skipping the mount's AppleDouble sidecars."""
    found = [ROOT / "README.md"]
    found += sorted(p for p in (ROOT / "docs").glob("*.md")
                    if not p.name.startswith("."))
    return found


docs = documents()
text = {d: d.read_text(encoding="utf-8") for d in docs}
anchors = {d.name: {anchor(l) for l in text[d].splitlines() if l.startswith("#")}
           for d in docs}

print("documents and the links between them")
print("------------------------------------")
check("there are documents to check", len(docs) > 1, True)

missing_files, missing_anchors = [], []
for d in docs:
    for _, target in re.findall(r"\[([^\]]*)\]\(([^)]+)\)", text[d]):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, frag = target.partition("#")
        if path:
            if not (d.parent / path).exists():
                missing_files.append(f"{d.name} -> {target}")
                continue
            name = Path(path).name
        else:
            name = d.name
        if frag and name.endswith(".md") and frag not in anchors.get(name, set()):
            missing_anchors.append(f"{d.name} -> {target}")

check("every linked file exists", missing_files, [])
check("every linked heading exists", missing_anchors, [])

# The front page is the front page. If it grows back into the thing it
# replaced, this is where that gets noticed.
readme = len(text[ROOT / "README.md"].splitlines())
check("the README is still a front page, not a book", readme < 400, True)
print(f"        (README.md is {readme} lines; it was 2,369)")

# and prove the anchor check can fail
docs_with_anchor_links = [d for d in docs
                          if re.search(r"\]\([^)]*\.md#", text[d])]
check("some document does link to another's heading",
      bool(docs_with_anchor_links), True)

print(f"\n{'-' * 60}\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
