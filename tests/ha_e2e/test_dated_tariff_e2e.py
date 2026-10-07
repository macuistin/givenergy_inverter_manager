"""Dated rate changes and the stale-tariff repair against a real Home Assistant.

The frozen clock reads 2026-06-15 (Europe/Dublin), so "tomorrow" is 2026-06-16.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import MIDDAY, SERIAL, full_config_data
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.givenergy_inverter_manager as integration
from custom_components.givenergy_inverter_manager import repairs
from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_EXPORT_RATE,
    CONF_RATE_PERIODS,
    CONF_TARIFF_CHANGES,
    CONF_TARIFF_REVIEWED_ON,
    CONF_VAT_RATE,
    DEFAULT_RATE_PERIODS,
    DOMAIN,
    TARIFF_REVIEW_STALE_DAYS,
)

TODAY = "2026-06-15"
TOMORROW = "2026-06-16"
LATER = "2026-09-01"
NEW_BASE = 0.4
NEW_EXPORT = 0.21


@pytest.fixture
def scenario():
    return MIDDAY


def _serialise(result) -> list[dict]:
    return cv.to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)


def _initial_data(fields: list[dict]) -> dict:
    data: dict = {}
    for field in fields:
        if field.get("type") == "expandable":
            data[field["name"]] = _initial_data(field["schema"])
        elif "default" in field:
            data[field["name"]] = field["default"]
    return data


def payload(result, **sections: dict) -> dict:
    """What the frontend submits: every default pre-filled, then the given section values."""
    data = _initial_data(_serialise(result))
    for name, values in sections.items():
        data[name] = {**data.get(name, {}), **values}
    return data


def _change(day: str, base: float = NEW_BASE) -> dict:
    return {
        "effective": day,
        CONF_BASE_RATE: base,
        CONF_BASE_RATE_NAME: "Standard",
        CONF_EXPORT_RATE: NEW_EXPORT,
        CONF_RATE_PERIODS: [dict(p) for p in DEFAULT_RATE_PERIODS],
    }


async def _save(hass, entry, user_input_fn):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=user_input_fn(result)
    )
    await hass.async_block_till_done()
    return result


async def _set_options(hass, entry, **options) -> None:
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


class TestRecordingAChange:
    async def test_a_dated_save_records_the_rates_and_keeps_the_current_ones(
        self, hass, loaded_entry
    ):
        result = await _save(
            hass,
            loaded_entry,
            lambda r: payload(
                r,
                tariff_settings={CONF_BASE_RATE: NEW_BASE, CONF_EXPORT_RATE: NEW_EXPORT},
                tariff_change={"effective_from": LATER},
            ),
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        (change,) = loaded_entry.options[CONF_TARIFF_CHANGES]
        assert change["effective"] == LATER
        assert change[CONF_BASE_RATE] == pytest.approx(NEW_BASE)
        assert change[CONF_EXPORT_RATE] == pytest.approx(NEW_EXPORT)
        assert [p["name"] for p in change[CONF_RATE_PERIODS]] == ["Night", "Nightboost"]
        assert CONF_BASE_RATE not in loaded_entry.options
        assert loaded_entry.runtime_data._effective_cfg()[CONF_BASE_RATE] == pytest.approx(0.3334)
        assert loaded_entry.runtime_data.export_rate == pytest.approx(0.195)
        assert loaded_entry.state is ConfigEntryState.LOADED

    async def test_the_charges_in_the_same_submission_apply_now(self, hass, loaded_entry):
        await _save(
            hass,
            loaded_entry,
            lambda r: payload(
                r,
                tariff_settings={CONF_BASE_RATE: NEW_BASE, CONF_VAT_RATE: 13.5},
                tariff_change={"effective_from": LATER},
            ),
        )

        assert loaded_entry.options[CONF_VAT_RATE] == pytest.approx(13.5)

    async def test_the_form_lists_the_scheduled_change_on_reopening(self, hass, loaded_entry):
        await _save(
            hass,
            loaded_entry,
            lambda r: payload(
                r, tariff_settings={CONF_BASE_RATE: NEW_BASE}, tariff_change={"effective_from": LATER}
            ),
        )

        result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
        summary = result["description_placeholders"]["tariff_summary"]
        assert "Scheduled rate changes:" in summary
        assert f"From {LATER}: Day 0.4000" in summary
        hass.config_entries.options.async_abort(result["flow_id"])

    async def test_a_date_in_the_past_is_rejected_and_nothing_is_saved(self, hass, loaded_entry):
        result = await _save(
            hass,
            loaded_entry,
            lambda r: payload(
                r,
                tariff_settings={CONF_BASE_RATE: NEW_BASE},
                tariff_change={"effective_from": "2026-06-14"},
            ),
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "tariff_change_date_in_past"}
        assert CONF_TARIFF_CHANGES not in loaded_entry.options
        assert CONF_BASE_RATE not in loaded_entry.options

    async def test_a_date_of_today_applies_the_rates_now(self, hass, loaded_entry):
        await _save(
            hass,
            loaded_entry,
            lambda r: payload(
                r, tariff_settings={CONF_BASE_RATE: NEW_BASE}, tariff_change={"effective_from": TODAY}
            ),
        )

        assert loaded_entry.options[CONF_BASE_RATE] == pytest.approx(NEW_BASE)
        assert CONF_TARIFF_CHANGES not in loaded_entry.options

    async def test_a_client_that_omits_the_rate_sections_dates_the_periods_in_force(
        self, hass, loaded_entry
    ):
        def sparse(result):
            data = payload(
                result,
                tariff_settings={CONF_BASE_RATE: NEW_BASE},
                tariff_change={"effective_from": LATER},
            )
            return {k: v for k, v in data.items() if not k.startswith("rate_period_")}

        await _save(hass, loaded_entry, sparse)

        (change,) = loaded_entry.options[CONF_TARIFF_CHANGES]
        assert [p["name"] for p in change[CONF_RATE_PERIODS]] == ["Night", "Nightboost"]
        in_force = loaded_entry.runtime_data._effective_cfg()[CONF_RATE_PERIODS]
        assert [p["name"] for p in in_force] == ["Night", "Nightboost"]

    async def test_a_client_that_omits_the_change_section_keeps_what_is_scheduled(
        self, hass, loaded_entry
    ):
        await _set_options(hass, loaded_entry, **{CONF_TARIFF_CHANGES: [_change(LATER)]})

        def sparse(result):
            data = payload(result, tariff_settings={CONF_VAT_RATE: 13.5})
            data.pop("tariff_change", None)
            return {k: v for k, v in data.items() if not k.startswith("rate_period_")}

        await _save(hass, loaded_entry, sparse)

        assert [c["effective"] for c in loaded_entry.options[CONF_TARIFF_CHANGES]] == [LATER]
        assert loaded_entry.options[CONF_VAT_RATE] == pytest.approx(13.5)

    async def test_a_second_change_for_the_same_date_replaces_the_first(self, hass, loaded_entry):
        for base in (0.38, 0.41):
            await _save(
                hass,
                loaded_entry,
                lambda r, base=base: payload(
                    r,
                    tariff_settings={CONF_BASE_RATE: base},
                    tariff_change={"effective_from": LATER},
                ),
            )

        (change,) = loaded_entry.options[CONF_TARIFF_CHANGES]
        assert change[CONF_BASE_RATE] == pytest.approx(0.41)


class TestCancellingAChange:
    async def test_the_cancel_switch_is_offered_only_while_a_change_is_scheduled(
        self, hass, loaded_entry
    ):
        result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
        section = next(f for f in _serialise(result) if f["name"] == "tariff_change")
        assert [f["name"] for f in section["schema"]] == ["effective_from"]
        hass.config_entries.options.async_abort(result["flow_id"])

        await _set_options(hass, loaded_entry, **{CONF_TARIFF_CHANGES: [_change(LATER)]})
        result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
        section = next(f for f in _serialise(result) if f["name"] == "tariff_change")
        assert [f["name"] for f in section["schema"]] == ["effective_from", "cancel_scheduled"]
        hass.config_entries.options.async_abort(result["flow_id"])

    async def test_cancelling_removes_the_scheduled_change(self, hass, loaded_entry):
        await _set_options(hass, loaded_entry, **{CONF_TARIFF_CHANGES: [_change(LATER)]})

        await _save(
            hass, loaded_entry, lambda r: payload(r, tariff_change={"cancel_scheduled": True})
        )

        assert CONF_TARIFF_CHANGES not in loaded_entry.options


class TestAChangeTakingEffect:
    async def test_the_coordinator_prices_with_the_new_rates_from_the_date(
        self, hass, loaded_entry, freezer
    ):
        await _set_options(hass, loaded_entry, **{CONF_TARIFF_CHANGES: [_change(TOMORROW)]})
        coordinator = loaded_entry.runtime_data
        await coordinator.async_refresh()
        assert coordinator.data.current_rate == pytest.approx(0.3334)
        assert coordinator.data.current_rate_name == "Day"

        freezer.tick(timedelta(days=1))
        await coordinator.async_refresh()

        assert coordinator.data.current_rate == pytest.approx(NEW_BASE)
        assert coordinator.data.current_rate_name == "Standard"
        assert coordinator.export_rate == pytest.approx(NEW_EXPORT)
        assert loaded_entry.state is ConfigEntryState.LOADED

    async def test_the_form_shows_the_rates_in_force_once_a_change_started(
        self, hass, loaded_entry
    ):
        await _set_options(hass, loaded_entry, **{CONF_TARIFF_CHANGES: [_change(TODAY)]})

        result = await hass.config_entries.options.async_init(loaded_entry.entry_id)

        defaults = _initial_data(_serialise(result))["tariff_settings"]
        assert defaults[CONF_BASE_RATE] == pytest.approx(NEW_BASE)
        assert defaults[CONF_EXPORT_RATE] == pytest.approx(NEW_EXPORT)
        assert defaults[CONF_BASE_RATE_NAME] == "Standard"
        hass.config_entries.options.async_abort(result["flow_id"])

    async def test_saving_without_a_date_sets_the_rates_from_now_over_a_started_change(
        self, hass, loaded_entry
    ):
        await _set_options(hass, loaded_entry, **{CONF_TARIFF_CHANGES: [_change(TODAY)]})

        await _save(hass, loaded_entry, lambda r: payload(r, tariff_settings={CONF_BASE_RATE: 0.37}))

        assert loaded_entry.options[CONF_BASE_RATE] == pytest.approx(0.37)
        assert CONF_TARIFF_CHANGES not in loaded_entry.options
        assert loaded_entry.runtime_data._effective_cfg()[CONF_BASE_RATE] == pytest.approx(0.37)

    async def test_reconfigure_ends_a_started_change_and_keeps_a_scheduled_one(
        self, hass, loaded_entry
    ):
        await _set_options(
            hass, loaded_entry, **{CONF_TARIFF_CHANGES: [_change(TODAY), _change(LATER, 0.5)]}
        )

        result = await loaded_entry.start_reconfigure_flow(hass)
        form = {f["name"]: f.get("default") for f in _serialise(result) if "default" in f}
        assert form[CONF_BASE_RATE] == pytest.approx(NEW_BASE)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={**_initial_data(_serialise(result)), CONF_BASE_RATE: 0.37},
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.ABORT
        assert loaded_entry.data[CONF_BASE_RATE] == pytest.approx(0.37)
        assert [c["effective"] for c in loaded_entry.options[CONF_TARIFF_CHANGES]] == [LATER]
        assert loaded_entry.options[CONF_TARIFF_REVIEWED_ON] == TODAY


class TestNoChangeRecorded:
    async def test_saving_the_form_unchanged_adds_no_dated_keys(self, hass, loaded_entry):
        await _save(hass, loaded_entry, payload)

        assert CONF_TARIFF_CHANGES not in loaded_entry.options
        assert CONF_TARIFF_REVIEWED_ON not in loaded_entry.options

    async def test_saving_a_different_rate_without_a_date_moves_the_review_date(
        self, hass, loaded_entry
    ):
        await _save(hass, loaded_entry, lambda r: payload(r, tariff_settings={CONF_BASE_RATE: 0.37}))

        assert loaded_entry.options[CONF_BASE_RATE] == pytest.approx(0.37)
        assert loaded_entry.options[CONF_TARIFF_REVIEWED_ON] == TODAY


ISSUE = repairs.ISSUE_TARIFF_REVIEW_DUE


def _entry_aged(days: int, **options) -> MockConfigEntry:
    """An entry created *days* before the frozen clock (2026-06-15)."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=full_config_data(), options=options, unique_id=SERIAL, version=1
    )
    entry.created_at = datetime(2026, 6, 15, 12, tzinfo=timezone.utc) - timedelta(days=days)
    return entry


async def _load(hass, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE)


class TestStaleTariffRepair:
    async def test_an_entry_unreviewed_for_the_limit_raises_a_fixable_issue(
        self, hass, hass_in_scenario
    ):
        entry = _entry_aged(TARIFF_REVIEW_STALE_DAYS + 1)
        await _load(hass, entry)

        issue = _issue(hass)
        assert issue is not None
        assert issue.is_fixable is True
        assert issue.learn_more_url == repairs.LEARN_MORE_URLS[ISSUE]
        assert issue.translation_placeholders == {
            "last_reviewed": "2025-06-14",
            "days": str(TARIFF_REVIEW_STALE_DAYS + 1),
        }
        await hass.config_entries.async_unload(entry.entry_id)

    async def test_a_new_entry_raises_nothing(self, hass, hass_in_scenario):
        entry = _entry_aged(3)
        await _load(hass, entry)

        assert _issue(hass) is None
        await hass.config_entries.async_unload(entry.entry_id)

    async def test_a_recent_review_keeps_an_old_entry_clear(self, hass, hass_in_scenario):
        entry = _entry_aged(3 * TARIFF_REVIEW_STALE_DAYS, **{CONF_TARIFF_REVIEWED_ON: "2026-05-01"})
        await _load(hass, entry)

        assert _issue(hass) is None
        await hass.config_entries.async_unload(entry.entry_id)

    async def test_confirming_the_fix_records_the_review_without_a_reload(
        self, hass, hass_in_scenario, monkeypatch
    ):
        setups: list[str] = []
        real = integration.async_setup_entry

        async def counting(hass_, entry_):
            setups.append(entry_.entry_id)
            return await real(hass_, entry_)

        monkeypatch.setattr(integration, "async_setup_entry", counting)
        entry = _entry_aged(TARIFF_REVIEW_STALE_DAYS + 40)
        await _load(hass, entry)
        coordinator = entry.runtime_data
        assert _issue(hass) is not None

        assert await async_setup_component(hass, "repairs", {})
        form = await repairs_flow_manager(hass).async_init(DOMAIN, data={"issue_id": ISSUE})
        assert form["type"] is FlowResultType.FORM
        assert form["step_id"] == "confirm"
        assert form["description_placeholders"]["days"] == str(TARIFF_REVIEW_STALE_DAYS + 40)
        done = await repairs_flow_manager(hass).async_configure(form["flow_id"], {})
        await hass.async_block_till_done()

        assert done["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_TARIFF_REVIEWED_ON] == TODAY
        assert setups == [entry.entry_id]
        assert entry.runtime_data is coordinator
        await coordinator.async_refresh()
        assert _issue(hass) is None
        await hass.config_entries.async_unload(entry.entry_id)

    async def test_saving_a_new_rate_clears_the_issue(self, hass, hass_in_scenario):
        entry = _entry_aged(TARIFF_REVIEW_STALE_DAYS + 40)
        await _load(hass, entry)
        assert _issue(hass) is not None

        await _save(hass, entry, lambda r: payload(r, tariff_settings={CONF_BASE_RATE: 0.37}))
        await entry.runtime_data.async_refresh()

        assert _issue(hass) is None
        await hass.config_entries.async_unload(entry.entry_id)
