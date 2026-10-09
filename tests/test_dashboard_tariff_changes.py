"""
The scheduled rate changes on the Tariff view.

The view lists the dated changes that have not started, with the date the tariff was last
reviewed, under the tariff in use. The list is read from the options when the file is generated,
as the tariff table is, and it is left out when no change is scheduled.
"""

from __future__ import annotations

import itertools
from datetime import date, timedelta

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_CURRENCY,
    CONF_EXPORT_RATE,
    CONF_RATE_PERIODS,
    CONF_TARIFF_CHANGES,
    CONF_TARIFF_REVIEWED_ON,
)
from tests.dashboard_support import (
    FULL_CONFIG,
    dashboard_dict,
    dashboard_text,
    devices_of,
    view_cards,
)
from tests.dashboard_visibility import install, seen, states_with

COMBINATIONS = list(itertools.product([False, True], repeat=3))
HEADING = "Scheduled rate changes"
_TODAY = date.today()
_AHEAD = _TODAY + timedelta(days=30)
_LATER = _TODAY + timedelta(days=120)
_PAST = _TODAY - timedelta(days=30)


def _change(day: date, **rates) -> dict:
    return {
        "effective": day.isoformat(),
        CONF_BASE_RATE: 0.40,
        CONF_BASE_RATE_NAME: "Day",
        CONF_RATE_PERIODS: [
            {"name": "Night", "rate": 0.20, "start": "23:00", "end": "08:00"},
            {"name": "Boost", "rate": 0.11, "start": "02:00", "end": "04:00"},
        ],
        CONF_EXPORT_RATE: 0.21,
        **rates,
    }


def _config(*changes: dict, reviewed: date | None = None, **extra) -> dict:
    config = {**FULL_CONFIG, **extra}
    if changes:
        config[CONF_TARIFF_CHANGES] = list(changes)
    if reviewed:
        config[CONF_TARIFF_REVIEWED_ON] = reviewed.isoformat()
    return config


def _tariff(config: dict) -> list[dict]:
    view = next(v for v in dashboard_dict(config)["views"] if v["path"] == "tariff")
    return view_cards(view)


def _changes_card(config: dict) -> dict | None:
    cards = _tariff(config)
    heads = [c for c in cards if c["type"] == "heading" and c["heading"] == HEADING]
    if not heads:
        return None
    return cards[cards.index(heads[0]) + 1]


def _table(config: dict) -> str:
    card = _changes_card(config)
    assert card is not None
    return card["content"]


# ── what it shows ────────────────────────────────────────────────────────────


def test_a_scheduled_change_shows_its_date_and_the_new_rates():
    table = _table(_config(_change(_AHEAD), reviewed=_TODAY))
    assert "| From | Base rate | Timed rates | Export rate per kWh |" in table
    assert f"| {_AHEAD.day} {_AHEAD:%b %Y} | Day €0.4000 |" in table
    assert "Night 23:00 to 08:00 €0.2000<br>Boost 02:00 to 04:00 €0.1100" in table
    assert "| €0.2100 |" in table


def test_the_last_review_date_is_shown():
    table = _table(_config(_change(_AHEAD), reviewed=date(2026, 3, 9)))
    assert "Tariff last reviewed on 9 Mar 2026." in table


def test_no_review_date_is_shown_when_none_was_recorded():
    assert "reviewed" not in _table(_config(_change(_AHEAD)))


def test_a_malformed_review_date_is_left_out():
    config = _config(_change(_AHEAD))
    config[CONF_TARIFF_REVIEWED_ON] = "not a date"
    assert "reviewed" not in _table(config)


def test_changes_are_listed_soonest_first():
    table = _table(_config(_change(_LATER, **{CONF_BASE_RATE: 0.5}), _change(_AHEAD)))
    assert table.index(f"{_AHEAD.day} {_AHEAD:%b %Y}") < table.index(f"{_LATER.day} {_LATER:%b %Y}")
    assert "Day €0.5000" in table


def test_a_change_with_no_timed_rates_says_none():
    table = _table(_config(_change(_AHEAD, **{CONF_RATE_PERIODS: []})))
    assert "| Day €0.4000 | none | €0.2100 |" in table


def test_the_currency_is_the_one_of_the_tariff():
    table = _table(_config(_change(_AHEAD), **{CONF_CURRENCY: "GBP"}))
    assert "Day £0.4000" in table
    assert "€" not in table


def test_the_table_says_which_charges_a_change_leaves_alone():
    assert "The other charges stay as in the table above." in _table(_config(_change(_AHEAD)))


def test_the_tariff_in_use_is_untouched_by_a_change_ahead():
    cards = _tariff(_config(_change(_AHEAD)))
    in_use = next(c for c in cards if c["type"] == "markdown")["content"]
    assert "| Day | all other times | €0.3334 |" in in_use


def test_the_changes_sit_under_the_tariff_in_use_in_the_same_section():
    config = dashboard_dict(_config(_change(_AHEAD)))
    view = next(v for v in config["views"] if v["path"] == "tariff")
    (section,) = view["sections"]
    kinds = [(c["type"], c.get("heading")) for c in section["cards"]]
    assert kinds == [
        ("heading", "Tariff in use"),
        ("markdown", None),
        ("heading", HEADING),
        ("markdown", None),
    ]


# ── when it shows ────────────────────────────────────────────────────────────


def test_it_is_left_out_when_no_change_is_stored():
    assert _changes_card(_config()) is None
    assert _changes_card(_config(reviewed=_TODAY)) is None


def test_a_change_that_has_started_is_not_scheduled_any_more():
    """It is in force, so the tariff in use already shows it."""
    config = _config(_change(_PAST), reviewed=_TODAY)
    assert _changes_card(config) is None
    in_use = next(c for c in _tariff(config) if c["type"] == "markdown")["content"]
    assert "| Day | all other times | €0.4000 |" in in_use


def test_only_the_changes_ahead_are_listed():
    table = _table(_config(_change(_PAST, **{CONF_BASE_RATE: 0.9}), _change(_AHEAD)))
    assert "€0.9000" not in table
    assert f"{_AHEAD.day} {_AHEAD:%b %Y}" in table


def test_no_lone_heading_is_left_when_there_are_no_changes():
    headings = [c["heading"] for c in _tariff(_config()) if c["type"] == "heading"]
    assert headings == ["Tariff in use"]


def test_a_malformed_stored_change_is_skipped():
    config = _config({"effective": "tomorrow"}, _change(_AHEAD))
    assert f"{_AHEAD.day} {_AHEAD:%b %Y}" in _table(config)
    assert _changes_card(_config({"effective": "tomorrow"})) is None


def test_the_heading_is_a_subheading_under_the_tariff():
    cards = _tariff(_config(_change(_AHEAD)))
    heading = next(c for c in cards if c["type"] == "heading" and c["heading"] == HEADING)
    assert heading["heading_style"] == "subtitle"


# ── the same for every install ───────────────────────────────────────────────


def _tariff_view_seen(ev: bool, switch: bool, sensor: bool) -> dict:
    config, brand = install(ev=ev, switch=switch, sensor=sensor)
    config[CONF_TARIFF_CHANGES] = [_change(_AHEAD)]
    generated = dashboard_dict(config, ev_brand=brand)
    shown = seen(generated, states_with(devices_of(config, brand)))
    return next(v for v in shown["views"] if v["path"] == "tariff")


@pytest.mark.parametrize("combination", COMBINATIONS, ids=lambda c: "-".join(map(str, map(int, c))))
def test_the_tariff_view_is_the_same_for_every_combination_of_devices(combination):
    """The tariff has no device, so the table shows whatever devices the install has."""
    view = _tariff_view_seen(*combination)
    assert [c.get("heading") for c in view_cards(view)] == [
        "Tariff in use",
        None,
        HEADING,
        None,
    ]
    assert view == _tariff_view_seen(False, False, False)


def test_the_generated_file_holds_the_table():
    text = dashboard_text(_config(_change(_AHEAD)))
    assert HEADING in text
    assert f"| {_AHEAD.day} {_AHEAD:%b %Y} | Day €0.4000 |" in text
