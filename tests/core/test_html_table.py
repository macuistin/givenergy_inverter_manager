"""The table a markdown card draws at the full width of the card."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.core.html_table import (
    bold,
    html_table,
    unbroken,
    with_note,
)


def test_the_exact_markup_carries_its_layout_in_attributes_alone():
    table = html_table(["Band", "kWh"], [["Day", "1.0"], [bold("Total"), bold("1.0")]])

    assert table == (
        '<table width="100%">'
        '<thead><tr><td><b>Band</b></td><td align="right"><b>kWh</b></td></tr></thead>'
        '<tbody><tr><td>Day</td><td align="right">1.0</td></tr>'
        '<tr><td><b>Total</b></td><td align="right"><b>1.0</b></td></tr></tbody>'
        "</table>"
    )
    assert "style=" not in table


def test_the_text_columns_read_left_and_the_rest_are_numbers():
    table = html_table(["Period", "Window", "Rate"], [["Day", "all day", "0.30"]], text_columns=2)

    assert "<td>Day</td><td>all day</td>" in table
    assert '<td align="right">0.30</td>' in table


def test_a_header_with_no_text_is_left_out():
    table = html_table(["", ""], [["You paid", "€1.00"]])

    assert "<thead>" not in table
    assert table.startswith('<table width="100%"><tbody><tr><td>You paid</td>')


def test_an_empty_header_cell_among_others_is_not_bold():
    assert "<td></td>" in html_table(["", "Saved"], [])


def test_a_note_is_a_paragraph_of_its_own_so_markdown_reads_it():
    assert with_note("<table></table>", "*A note.*") == "<table></table>\n\n*A note.*"


def test_unbroken_text_never_wraps_between_a_figure_and_its_unit():
    assert unbroken("8.2 kWh") == "8.2 kWh"
