"""Shared paths for the unit tests, so no test depends on the working directory."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "custom_components" / "givenergy_inverter_manager"


class _Rows(HTMLParser):
    """Collects the text of each cell of each row, across every table in the text."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            self.rows[-1].append("")
            self._in_cell = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._in_cell = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self.rows[-1][-1] += data


def table_rows(text: str) -> list[list[str]]:
    """The rows of the HTML tables in *text*, each a list of cell text with plain spaces.

    A test reads a table the way a person does, without pinning its markup. The markup has
    its own test in tests/core/test_html_table.py.
    """
    parser = _Rows()
    parser.feed(text)
    return [[cell.replace(" ", " ") for cell in row] for row in parser.rows]
