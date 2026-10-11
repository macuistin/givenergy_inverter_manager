"""The setup checklist: what is left to set up, and when the required part is done.

Each item is worked out from the saved config and one cycle's readings. The state is complete
once every required item is done. The two optional items, hot water and an EV charger, never
hold it open. A test instance holds dry run on for good, so turning it off is not required there.
"""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.core.setup_progress import (
    STATE_COMPLETE,
    STATE_INCOMPLETE,
    SetupFacts,
    SetupItem,
    setup_items,
    setup_state,
)

TIMED = [{"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"}]
DONE_CONFIG = {
    "base_rate": 0.33,
    "export_rate": 0.19,
    "rate_periods": TIMED,
    "forecast_entity": "sensor.forecast_tomorrow",
}
DONE_FACTS = SetupFacts(
    inverter_found=True,
    forecast_readable=True,
    ev_charger_found=False,
    dry_run=False,
    test_instance=False,
)


def _by_key(config=None, facts=None) -> dict[str, SetupItem]:
    items = setup_items(DONE_CONFIG if config is None else config, facts or DONE_FACTS)
    return {item.key: item for item in items}


def _with(facts: SetupFacts = DONE_FACTS, **changes) -> SetupFacts:
    return SetupFacts(**{**facts.__dict__, **changes})


class TestEachItem:
    def test_the_inverter_is_found_when_no_required_input_is_unavailable(self):
        assert _by_key()["inverter"].done is True
        assert _by_key(facts=_with(inverter_found=False))["inverter"].done is False

    @pytest.mark.parametrize(
        ("config", "done"),
        [
            ({"base_rate": 0.3, "export_rate": 0.1}, True),
            ({"base_rate": 0.3, "export_rate": 0.0}, True),
            ({"base_rate": 0.3}, False),
            ({"export_rate": 0.1}, False),
            ({"base_rate": None, "export_rate": 0.1}, False),
            ({"base_rate": "", "export_rate": 0.1}, False),
            ({}, False),
        ],
    )
    def test_the_tariff_is_set_when_both_rates_are_saved(self, config, done):
        assert _by_key(config)["tariff"].done is done

    @pytest.mark.parametrize(
        ("periods", "done"),
        [
            (TIMED, True),
            ([], False),
            (None, False),
            ([{"name": "Bad", "rate": "x", "start": "1", "end": "2"}], False),
            ([{"name": "Flat", "rate": 0.1, "start": "08:00", "end": "08:00"}], False),
        ],
        ids=["timed", "empty", "absent", "malformed", "never applies"],
    )
    def test_the_cheap_window_needs_a_valid_timed_period(self, periods, done):
        config = {k: v for k, v in DONE_CONFIG.items() if k != "rate_periods"}
        if periods is not None:
            config["rate_periods"] = periods
        assert _by_key(config)["cheap_window"].done is done

    def test_the_built_in_default_periods_do_not_count_as_a_cheap_window(self):
        config = {k: v for k, v in DONE_CONFIG.items() if k != "rate_periods"}
        assert _by_key(config)["cheap_window"].done is False

    def test_the_forecast_needs_an_entity_and_a_reading(self):
        assert _by_key()["forecast"].done is True
        assert _by_key(facts=_with(forecast_readable=False))["forecast"].done is False
        no_entity = {k: v for k, v in DONE_CONFIG.items() if k != "forecast_entity"}
        assert _by_key(no_entity)["forecast"].done is False

    def test_dry_run_off_is_done_only_when_dry_run_is_off(self):
        assert _by_key()["dry_run"].done is True
        assert _by_key(facts=_with(dry_run=True))["dry_run"].done is False

    def test_hot_water_follows_the_immersion_switch(self):
        assert _by_key()["hot_water"].done is False
        config = {**DONE_CONFIG, "immersion_switch_entity": "switch.heater"}
        assert _by_key(config)["hot_water"].done is True

    def test_the_ev_charger_follows_discovery(self):
        assert _by_key()["ev_charger"].done is False
        assert _by_key(facts=_with(ev_charger_found=True))["ev_charger"].done is True


class TestWhatIsRequired:
    def test_five_items_are_required_and_two_are_optional(self):
        required = {k for k, item in _by_key().items() if item.required}
        assert required == {"inverter", "tariff", "cheap_window", "forecast", "dry_run"}
        assert {k for k, item in _by_key().items() if not item.required} == {
            "hot_water",
            "ev_charger",
        }

    def test_required_items_come_first_then_the_optional_ones(self):
        flags = [item.required for item in setup_items(DONE_CONFIG, DONE_FACTS)]
        assert flags == sorted(flags, reverse=True)

    def test_dry_run_is_not_required_on_a_test_instance(self):
        item = _by_key(facts=_with(dry_run=True, test_instance=True))["dry_run"]
        assert item.done is False
        assert item.required is False


class TestState:
    def test_complete_when_every_required_item_is_done(self):
        assert setup_state(setup_items(DONE_CONFIG, DONE_FACTS)) == STATE_COMPLETE

    def test_optional_items_never_hold_it_open(self):
        items = setup_items(DONE_CONFIG, _with(ev_charger_found=False))
        assert not _by_key()["hot_water"].done
        assert setup_state(items) == STATE_COMPLETE

    @pytest.mark.parametrize(
        "facts",
        [
            _with(inverter_found=False),
            _with(forecast_readable=False),
            _with(dry_run=True),
        ],
        ids=["no inverter", "forecast unreadable", "dry run on"],
    )
    def test_incomplete_while_a_required_item_is_not_done(self, facts):
        assert setup_state(setup_items(DONE_CONFIG, facts)) == STATE_INCOMPLETE

    @pytest.mark.parametrize("missing", ["base_rate", "export_rate", "rate_periods", "forecast_entity"])
    def test_incomplete_while_a_required_setting_is_missing(self, missing):
        config = {k: v for k, v in DONE_CONFIG.items() if k != missing}
        assert setup_state(setup_items(config, DONE_FACTS)) == STATE_INCOMPLETE

    def test_a_test_instance_with_dry_run_on_can_still_be_complete(self):
        facts = _with(dry_run=True, test_instance=True)
        assert setup_state(setup_items(DONE_CONFIG, facts)) == STATE_COMPLETE

    def test_with_no_items_yet_it_is_incomplete(self):
        assert setup_state(()) == STATE_INCOMPLETE

    def test_the_states_are_the_words_the_dashboard_reads(self):
        assert (STATE_COMPLETE, STATE_INCOMPLETE) == ("complete", "incomplete")


def test_an_item_serialises_to_the_attribute_the_card_reads():
    item = SetupItem("tariff", "Tariff set", True, True)
    assert item.as_dict() == {"key": "tariff", "label": "Tariff set", "done": True, "required": True}
