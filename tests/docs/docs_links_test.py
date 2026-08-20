#!/usr/bin/env python3
"""
Check every relative link between the documents still goes somewhere.

    python3 tests/docs/docs_links_test.py

The README used to be one 2,369-line file, so a cross-reference could not
break: everything was in the same document. Splitting it into a front page and
nine topic files traded that for something readable, and this is the price -
now a heading can be renamed in one file and silently orphan a link in another.

Checks relative links only. External URLs are somebody else's uptime and would
make this need a network, which a test that runs on the Pi should not.

The second half checks docs/scenarios/, where a sequence diagram, a table of
its steps and a set of links into the source all have to agree with each
other and with the code. None of those disagreements are visible on the page.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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


def prose(body):
    """
    `body` with code removed, so examples are not mistaken for links.

    A document that teaches a link format contains link *samples* - in fenced
    blocks and in inline code - and GitHub renders none of them as links. The
    check below would otherwise chase `[`take`](...#L258)` out of a table of
    rules and report the placeholder as a broken path.
    """
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    body = re.sub(r"``[^`]*``", "", body)
    return re.sub(r"`[^`]*`", "", body)


def documents():
    """
    Every markdown file, skipping the mount's AppleDouble sidecars.

    rglob rather than glob: docs/ has subdirectories now, and a check that
    silently stopped at the top level would have passed while every link in
    docs/subsystems/ rotted.
    """
    found = [ROOT / "README.md"]
    found += sorted(p for p in (ROOT / "docs").rglob("*.md")
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
    for _, target in re.findall(r"\[([^\]]*)\]\(([^)]+)\)", prose(text[d])):
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

# GitHub Pages serves main:/docs, so docs/index.html IS the site root -
# https://replicant1.github.io/AsciiArt-Pi/ is that file and nothing else.
# Moving it would 404 the front door, which is why it is the one HTML file
# that cannot live in guides/ with the others.
check("index.html is still the site root",
      (ROOT / "docs" / "index.html").exists(), True)
check("and it is the only HTML at the top of docs/",
      sorted(p.name for p in (ROOT / "docs").glob("*.html")
             if not p.name.startswith(".")), ["index.html"])
check("the four guides are together in docs/guides/",
      sorted(p.name for p in (ROOT / "docs" / "guides").glob("*.html")
             if not p.name.startswith(".")),
      ["display-selection-guide.html", "enclosure-build-guide.html",
       "enclosure-renders.html", "panel-connectors-guide.html"])

published = sorted(p for p in (ROOT / "docs").rglob("*.html")
                   if not p.name.startswith("."))

broken_assets = []
for page in published:
    body = page.read_text(encoding="utf-8")
    for attr, target in re.findall(r'(src|href)="([^"]+)"', body):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        if not (page.parent / target.split("#")[0]).exists():
            broken_assets.append(f"{page.name} -> {target}")
check("and every asset they point at is where they say", broken_assets, [])

# Absolute URLs are skipped by the link check above, on purpose: resolving them
# would need a network. But the *published* ones are this repository's own, and
# their shape is checkable as a string. Moving the guides into guides/ changed
# them, and six markdown links were left pointing at the old form - which the
# link check could not see, because it does not follow http.
STALE = [f"AsciiArt-Pi/{name}" for name in
         ("display-selection-guide.html", "enclosure-build-guide.html",
          "panel-connectors-guide.html", "enclosure-renders.html")]
old_urls = []
for d in docs:
    for pattern in STALE:
        if pattern in text[d]:
            old_urls.append(f"{d.name} -> .../{pattern}")
check("no document links to a guide's pre-move URL", old_urls, [])

# The same mistake one directory over: tooling that opens a guide by path.
#
# Dotfiles are skipped for the same reason documents() skips them: on the Pi,
# tools/ is full of the mount's AppleDouble sidecars - ._piinput.py and the
# rest - which are not UTF-8 and are not source. Reading one raises, so this
# check could only ever pass on the Mac, where they are not there. That is the
# worst shape for a test: green on the machine nobody deploys from.
tooling = []
for tool in sorted(p for p in (ROOT / "tools").rglob("*.py")
                   if not p.name.startswith(".")) + \
        sorted(p for p in (ROOT / "tools").rglob("*.js")
               if not p.name.startswith(".")):
    body = tool.read_text(encoding="utf-8")
    for name in ("display-selection-guide.html", "enclosure-build-guide.html",
                 "panel-connectors-guide.html", "enclosure-renders.html"):
        if f"docs/{name}" in body:
            tooling.append(f"{tool.name} -> docs/{name}")
check("and no tool opens one by its pre-move path", tooling, [])


# --- scenario documents -----------------------------------------------------
#
# docs/scenarios/ pairs every mermaid sequence diagram with a table holding one
# row per message, and links names in those rows to the line that defines them.
# Three things can rot there without being visible to anyone reading the page:
# a message added to a diagram with no row to match, a message reworded in one
# of the two places and not the other, and a line anchor left pointing at
# whatever moved into its line number.

SCENARIOS = sorted(p for p in (ROOT / "docs" / "scenarios").glob("*.md")
                   if not p.name.startswith("."))
DEFINITION = re.compile(r"\s*(?:def|class)\s+(\w+)|^([A-Z_][A-Z0-9_]*)\s*=")


def plain(text_):
    """A cell or a diagram message reduced to comparable text."""
    text_ = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text_)   # links -> their text
    text_ = text_.replace("<br/>", "<br>").replace("`", "").replace("**", "")
    return re.sub(r"\s+", " ", text_).strip()


def step_table_faults(body):
    """Every way a step table and the diagram above it disagree."""
    faults = []
    blocks = re.findall(r"```mermaid\n(.*?)```", body, re.S)
    tails = re.split(r"```mermaid.*?```", body, flags=re.S)[1:]
    for block, tail in zip(blocks, tails):
        messages = [plain(line.split(":", 1)[1]) for line in block.splitlines()
                    if re.search(r"-(-)?>>", line)]
        rows = []
        for line in tail.splitlines():
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) == 3 and cells[0].isdigit():
                rows.append((int(cells[0]), plain(cells[1])))
        numbering = [n for n, _ in rows]
        if numbering != list(range(1, len(messages) + 1)):
            faults.append(f"{len(messages)} messages, rows {numbering}")
            continue
        for (n, cell), message in zip(rows, messages):
            if cell != message:
                faults.append(f"step {n}: {cell!r} != {message!r}")
    return faults


print("\nscenarios: diagrams, their step tables, and the source they link to")
print("-" * 66)
check("there are scenarios to check", bool(SCENARIOS), True)

drift = []
for d in SCENARIOS:
    drift += [f"{d.name} -> {fault}" for fault in step_table_faults(text[d])]
check("every diagram message has a row saying the same thing", drift, [])

# Link text in backticks claims to *be* the identifier, so it has to be the one
# defined on the line linked to. Prose link text - "four KB", "the knob" - only
# has to land on a definition, since there is no name in it to compare.
not_a_definition, wrong_definition = [], []
for d in SCENARIOS:
    for label, target in re.findall(r"\[([^\]]+)\]\(([^)]+#L\d+)\)", text[d]):
        path, _, number = target.partition("#L")
        source = (d.parent / path).resolve()
        lines = source.read_text(encoding="utf-8").splitlines() if source.is_file() else []
        n = int(number)
        found = DEFINITION.match(lines[n - 1] if 1 <= n <= len(lines) else "")
        name = (found.group(1) or found.group(2)) if found else None
        if name is None:
            not_a_definition.append(f"{d.name} -> {target}")
            continue
        coded = re.fullmatch(r"`([\w.]+)`(?:\(\))?", label.strip())
        if coded and coded.group(1).split(".")[-1] != name:
            wrong_definition.append(f"{d.name} -> {label} lands on {name}")
check("every source line anchor lands on a definition", not_a_definition, [])
check("and a backticked label names the definition it lands on", wrong_definition, [])

# --- priority, which is written down twice -----------------------------------
#
# Every scenario states its priority under its own headline, and the index
# states it again beside the link. Two copies, and a disagreement is invisible:
# both pages render perfectly while telling a reader different things.
#
# The index is the authority, because it is the one page that can be read as a
# ranking. This checks the documents against it, and that none of them forgot.

PRIORITY_IN_DOC = re.compile(r"^\*\*Priority: `(HIGH|MEDIUM|LOW)`\*\*", re.M)
PRIORITY_IN_INDEX = re.compile(r"^- `(HIGH|MEDIUM|LOW)` \u00b7 \[[^\]]+\]\(([^)]+\.md)\)", re.M)

INDEX = ROOT / "docs" / "scenarios" / "SCENARIO_INDEX.md"


def priority_faults():
    """Where a scenario's stated priority and the index's disagree."""
    faults = []
    if not INDEX.is_file():
        return ["no SCENARIO_INDEX.md"]
    ranked = {name: pri for pri, name in PRIORITY_IN_INDEX.findall(
        INDEX.read_text(encoding="utf-8"))}
    for d in SCENARIOS:
        if d.name == INDEX.name:
            continue
        found = PRIORITY_IN_DOC.search(text[d])
        if found is None:
            faults.append(f"{d.name} states no priority")
        elif d.name not in ranked:
            faults.append(f"{d.name} is not ranked in the index")
        elif found.group(1) != ranked[d.name]:
            faults.append(f"{d.name} says {found.group(1)}, "
                          f"the index says {ranked[d.name]}")
    return faults


check("every scenario's priority matches the index", priority_faults(), [])
check("and the index ranks every written scenario",
      sorted(n for _, n in PRIORITY_IN_INDEX.findall(
          INDEX.read_text(encoding="utf-8"))),
      sorted(d.name for d in SCENARIOS if d.name != INDEX.name))

# and prove the step table check can fail, on a sample rather than on a real
# document - a mutation of a real one stops mutating the moment it is edited.
SAMPLE = """```mermaid
sequenceDiagram
    A->>B: do the thing
```

| Step | Message | What is going on |
|---:|---|---|
| 1 | do the thing | why |
"""
check("the step table check passes a table that agrees",
      step_table_faults(SAMPLE), [])
check("and fails one whose message was reworded",
      bool(step_table_faults(SAMPLE.replace("do the thing", "do it", 1))), True)
check("and fails one with a message that has no row",
      bool(step_table_faults(
          SAMPLE.replace("    A->>B: do the thing",
                         "    A->>B: do the thing\n    B->>A: and reply", 1))), True)

print(f"\n{'-' * 60}\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
