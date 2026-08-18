#!/usr/bin/env python3
"""
Number the figures and tables in docs/display-selection-guide.html.

Numbers are written literally into the markup rather than generated with CSS
counters, so they survive copy-paste and plain-text extraction. That means they
must be regenerated whenever the document is reordered - which this script does.

It is idempotent: any labels already present are stripped before renumbering,
including accumulated ones, so it is safe to run repeatedly.

    python3 tools/docs/number_figures.py [path]
"""

import pathlib
import re
import sys

# Matches one leading label. The separator is written as &nbsp;&mdash; but an
# earlier revision used a plain space, so accept either.
LABEL = re.compile(
    r'^\s*<span class="num">(?:Figure|Table)\s+\d+</span>(?:&nbsp;|\s)*&mdash;\s*'
)


def strip_labels(body):
    """Remove every label already at the start of a caption, not just the first."""
    while True:
        stripped = LABEL.sub("", body, count=1)
        if stripped == body:
            return body
        body = stripped


def renumber(html, tag, word):
    counter = [0]

    def label(match):
        counter[0] += 1
        lead, body = match.group(1), strip_labels(match.group(2))
        return (f'<{tag}>{lead}<span class="num">{word} {counter[0]}</span>'
                f'&nbsp;&mdash; {body}')

    html = re.sub(rf'<{tag}>(\s*)(.*?)(?=</{tag}>)', label, html, flags=re.S)
    return html, counter[0]


def main():
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                        else "docs/display-selection-guide.html")
    html = path.read_text()
    html, figures = renumber(html, "figcaption", "Figure")
    html, tables = renumber(html, "caption", "Table")
    path.write_text(html)
    print(f"numbered {figures} figures and {tables} tables in {path}")


if __name__ == "__main__":
    main()
