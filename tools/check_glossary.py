#!/usr/bin/env python3
"""
Check that every abbreviation used in the display selection guide is glossed.

Written after a hand-maintained checklist missed "BCM": verifying against a
list you typed yourself only proves you can retype it. This extracts candidates
from the document's own prose instead, so anything newly introduced shows up.

Exits non-zero if something is unglossed, so it can gate a commit.

    python3 tools/check_glossary.py [path]
"""

import html as htmlmod
import pathlib
import re
import sys

# Ordinary English and units that happen to be capitalised, plus abbreviations
# whose meaning is not in question in this context.
IGNORE = {
    "A", "I", "AND", "THE", "OR", "IT", "IS", "IN", "ON", "AT", "TO", "OF", "IF",
    "AC", "DC",                      # DC is glossed as a signal; AC needs no gloss
    "AUD", "USD", "US", "NSW", "VIC",
    "PC", "TV", "OK", "NO",
    "CPU", "KB", "MB",               # universally understood
    "FX",                            # "FX basis" in the colophon
    "VT",                            # only ever appears inside VT220 etc.
    "RESET", "GND", "VCC",           # pin names, glossed as a pair
    "GU", "CU",                      # fragments of part numbers
}

# Part numbers are matched loosely: if the glossary mentions the family, a
# specific variant does not need its own entry.
FAMILIES = ("GU256", "GU-3000", "CU-Y", "RS232", "RS-232", "WY-", "LK", "VT")


def visible_text(html):
    body = re.sub(r'<(style|script)\b.*?</\1>', ' ', html, flags=re.S)
    body = re.sub(r'<[^>]+>', ' ', body)
    return htmlmod.unescape(body)


def main():
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                        else "docs/display-selection-guide.html")
    html = path.read_text()
    glossary = re.search(r'<section id="glossary">.*?</section>', html, re.S)
    if not glossary:
        sys.exit("no glossary section found")
    glossary = visible_text(glossary.group(0))
    body = visible_text(html)

    cands = set(re.findall(r'\b[A-Z][A-Z0-9]{1,}(?:[A-Z0-9-]*[A-Z0-9])?\b', body))
    cands |= {w for w in re.findall(r'\b[a-z]{2,4}\b', body) if w in {"ppi", "fps", "dpi"}}

    missing = []
    for c in sorted(cands - IGNORE):
        if c in glossary or any(c.startswith(f) for f in FAMILIES):
            continue
        missing.append((c, len(re.findall(r'\b%s\b' % re.escape(c), body))))

    if missing:
        print(f"{len(missing)} abbreviation(s) used but not glossed:")
        for term, n in missing:
            print(f"    {term:<18} used {n}x")
        sys.exit(1)

    print(f"all abbreviations glossed ({len(cands - IGNORE)} candidates checked)")


if __name__ == "__main__":
    main()
