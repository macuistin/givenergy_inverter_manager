"""
html_table.py: a table for Home Assistant's markdown card that fills the card.

The markdown card strips inline styles, and it draws a markdown pipe table only as wide as its
text, so a table sits ragged in a card that a chart beside it fills. It keeps the `width` and
`align` attributes, so these tables carry their layout in attributes alone. The heading cells
are bold `td` cells, because the card ignores `align` on a `th`.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Sequence


def bold(text: str) -> str:
    """The text in bold, or nothing for an empty cell."""
    return f"<b>{text}</b>" if text else ""


def unbroken(text: str) -> str:
    """The text with non-breaking spaces, so a narrow table never splits a figure from its unit."""
    return text.replace(" ", "\u00a0")


def _cells(cells: Sequence[str], text_columns: int) -> str:
    return "".join(
        f"<td>{cell}</td>" if index < text_columns else f'<td align="right">{cell}</td>'
        for index, cell in enumerate(cells)
    )


def html_table(header: Sequence[str], rows: Sequence[Sequence[str]], text_columns: int = 1) -> str:
    """A full-width table. The first *text_columns* columns read left, the rest are numbers.

    A header with no text is left out. The caller escapes any text a user typed.
    """
    head = ""
    if any(header):
        head = f"<thead><tr>{_cells([bold(cell) for cell in header], text_columns)}</tr></thead>"
    body = "".join(f"<tr>{_cells(row, text_columns)}</tr>" for row in rows)
    return f'<table width="100%">{head}<tbody>{body}</tbody></table>'


def with_note(table: str, note: str) -> str:
    """The table with a sentence under it, kept apart so markdown reads the sentence."""
    return f"{table}\n\n{note}"


def folded(summary: str, content: str) -> str:
    """The content closed under a line that opens it, for detail most visits do not need."""
    return f"<details><summary>{summary}</summary>\n\n{content}\n\n</details>"
