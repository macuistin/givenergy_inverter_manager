"""The repair for charge slots other than the one the integration manages."""

from __future__ import annotations

import homeassistant.helpers.issue_registry as ir
import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.givenergy_inverter_manager.const import (
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_DRY_RUN,
)
from custom_components.givenergy_inverter_manager.givtcp_writer import GivTCPWriter
from custom_components.givenergy_inverter_manager.repairs import (
    ISSUE_OTHER_CHARGE_SLOTS_ACTIVE,
    LEARN_MORE_URLS,
    ClearOutcome,
)
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

PREFIX = "select.givtcp_ab1234g567_charge"
START_1, END_1 = f"{PREFIX}_start_time_slot_1", f"{PREFIX}_end_time_slot_1"
START_2, END_2 = f"{PREFIX}_start_time_slot_2", f"{PREFIX}_end_time_slot_2"
START_3, END_3 = f"{PREFIX}_start_time_slot_3", f"{PREFIX}_end_time_slot_3"
UNUSED = "00:00:00"
TWO_TO_EIGHT = ("02:00:00", "08:00:00")  # start is not already 00:00, so both writes happen


@pytest.fixture(autouse=True)
def _no_write_retry_sleep(monkeypatch):
    monkeypatch.setitem(GivTCPWriter.write_verified.__globals__, "GIVTCP_WRITE_RETRY_SLEEP_S", 0)


@pytest.fixture(autouse=True)
def _fresh_issue_mocks():
    ir.async_create_issue.reset_mock()
    ir.async_delete_issue.reset_mock()


def _coord(slot_2=("00:00:00", "08:00:00"), **cfg_overrides) -> FakeCoordinator:
    """A coordinator set up like the owner's: slot 1 managed, a leftover slot 2."""
    cfg = _cfg(
        **{
            CONF_CHARGE_START_TIME_ENTITY: START_1,
            CONF_CHARGE_END_TIME_ENTITY: END_1,
            **cfg_overrides,
        }
    )
    coord = FakeCoordinator(cfg=cfg)
    coord.set_states(_default_states())
    coord.set_states({START_1: "01:59:00", END_1: "04:00:00"})
    coord.set_states({START_2: slot_2[0], END_2: slot_2[1]})
    return coord


def _raised() -> list[dict]:
    return [
        c.kwargs for c in ir.async_create_issue.call_args_list
        if c.args[2] == ISSUE_OTHER_CHARGE_SLOTS_ACTIVE
    ]


def _cleared() -> int:
    return sum(
        1 for c in ir.async_delete_issue.call_args_list
        if c.args[2] == ISSUE_OTHER_CHARGE_SLOTS_ACTIVE
    )


def _fail_writes_to(coord: FakeCoordinator, *entity_ids: str) -> None:
    original = coord._call_service

    async def call(domain, service, data):
        if data.get("entity_id") in entity_ids:
            raise HomeAssistantError("write rejected")
        await original(domain, service, data)

    coord._call_service = call


class TestDetection:
    @pytest.mark.asyncio
    async def test_a_cycle_raises_a_fixable_issue_naming_the_slot(self):
        coord = _coord()

        await coord._async_update_data()

        (issue,) = _raised()
        assert issue["is_fixable"] is True
        assert issue["severity"] == "warning"
        assert issue["translation_key"] == ISSUE_OTHER_CHARGE_SLOTS_ACTIVE
        assert issue["translation_placeholders"] == {"slots": "Slot 2 (00:00 to 08:00)"}
        assert issue["learn_more_url"] == LEARN_MORE_URLS[ISSUE_OTHER_CHARGE_SLOTS_ACTIVE]
        assert _cleared() == 0

    @pytest.mark.asyncio
    async def test_detecting_a_slot_writes_nothing(self):
        coord = _coord()

        await coord._async_update_data()

        assert coord.service_calls_for("select", "select_option") == []
        assert coord._writer.write_count == 0

    @pytest.mark.asyncio
    async def test_a_slot_set_to_zero_to_zero_raises_nothing_and_clears_the_issue(self):
        coord = _coord(slot_2=(UNUSED, UNUSED))

        await coord._async_update_data()

        assert _raised() == []
        assert _cleared() == 1

    @pytest.mark.asyncio
    async def test_the_issue_clears_once_the_slot_is_cleared_by_hand(self):
        coord = _coord()
        await coord._async_update_data()
        coord.set_states({START_2: UNUSED, END_2: UNUSED})

        await coord._async_update_data()

        assert len(_raised()) == 1
        assert _cleared() == 1

    @pytest.mark.asyncio
    async def test_several_active_slots_are_listed_in_one_issue(self):
        coord = _coord()
        coord.set_states({START_3: "12:00:00", END_3: "13:30:00"})

        await coord._async_update_data()

        (issue,) = _raised()
        assert issue["translation_placeholders"] == {
            "slots": "Slot 2 (00:00 to 08:00), Slot 3 (12:00 to 13:30)"
        }

    @pytest.mark.asyncio
    async def test_entities_without_a_slot_number_never_raise_it(self):
        coord = _coord(
            **{CONF_CHARGE_START_TIME_ENTITY: "select.charge_start",
               CONF_CHARGE_END_TIME_ENTITY: "select.charge_end"}
        )

        await coord._async_update_data()

        assert _raised() == []

    @pytest.mark.asyncio
    async def test_no_configured_charge_entities_never_raise_it(self):
        coord = _coord(**{CONF_CHARGE_START_TIME_ENTITY: None, CONF_CHARGE_END_TIME_ENTITY: None})

        await coord._async_update_data()

        assert _raised() == []


class TestClearing:
    @pytest.mark.asyncio
    async def test_start_then_end_are_set_to_zero_and_the_issue_clears(self):
        coord = _coord(slot_2=TWO_TO_EIGHT)

        outcome = await coord.async_clear_other_charge_slots()

        assert outcome is ClearOutcome.CLEARED
        assert coord.service_calls_for("select", "select_option") == [
            {"entity_id": START_2, "option": UNUSED},
            {"entity_id": END_2, "option": UNUSED},
        ]
        assert _raised() == []
        assert _cleared() == 1

    @pytest.mark.asyncio
    async def test_a_start_already_at_zero_is_not_written_again(self):
        coord = _coord()

        await coord.async_clear_other_charge_slots()

        assert coord.service_calls_for("select", "select_option") == [
            {"entity_id": END_2, "option": UNUSED}
        ]

    @pytest.mark.asyncio
    async def test_the_managed_slot_is_left_alone(self):
        coord = _coord(slot_2=TWO_TO_EIGHT)

        await coord.async_clear_other_charge_slots()

        assert coord._states[START_1].state == "01:59:00"
        assert coord._states[END_1].state == "04:00:00"

    @pytest.mark.asyncio
    async def test_every_active_slot_is_cleared(self):
        coord = _coord(slot_2=TWO_TO_EIGHT)
        coord.set_states({START_3: "12:00:00", END_3: "13:30:00"})

        await coord.async_clear_other_charge_slots()

        written = {c["entity_id"] for c in coord.service_calls_for("select", "select_option")}
        assert written == {START_2, END_2, START_3, END_3}

    @pytest.mark.asyncio
    async def test_writes_are_counted_like_other_inverter_writes(self):
        coord = _coord(slot_2=TWO_TO_EIGHT)

        await coord.async_clear_other_charge_slots()

        assert coord._writer.write_count == 2
        assert coord._acc.state.register_write_count == 2

    @pytest.mark.asyncio
    async def test_nothing_to_clear_writes_nothing_and_succeeds(self):
        coord = _coord(slot_2=(UNUSED, UNUSED))

        outcome = await coord.async_clear_other_charge_slots()

        assert outcome is ClearOutcome.CLEARED
        assert coord.service_calls == []
        assert _cleared() == 1


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_changes_nothing_and_keeps_the_issue(self):
        coord = _coord(**{CONF_DRY_RUN: True})

        outcome = await coord.async_clear_other_charge_slots()

        assert outcome is ClearOutcome.DRY_RUN
        assert coord.service_calls == []
        assert coord._writer.write_count == 0
        assert _cleared() == 0

    @pytest.mark.asyncio
    async def test_dry_run_records_what_it_skipped(self):
        coord = _coord(**{CONF_DRY_RUN: True})

        await coord.async_clear_other_charge_slots()

        assert coord._dry_run_last_skipped == (
            "Would clear other charge slots: Slot 2 (00:00 to 08:00)"
        )

    @pytest.mark.asyncio
    async def test_dry_run_still_raises_the_issue(self):
        coord = _coord(**{CONF_DRY_RUN: True})

        await coord._async_update_data()

        assert len(_raised()) == 1


class TestFailedWrites:
    @pytest.mark.asyncio
    async def test_a_rejected_write_fails_and_the_issue_stays(self):
        coord = _coord(slot_2=TWO_TO_EIGHT)
        _fail_writes_to(coord, START_2)

        outcome = await coord.async_clear_other_charge_slots()

        assert outcome is ClearOutcome.FAILED
        assert len(_raised()) == 1
        assert _cleared() == 0

    @pytest.mark.asyncio
    async def test_the_end_is_not_written_when_the_start_failed(self):
        coord = _coord(slot_2=TWO_TO_EIGHT)
        _fail_writes_to(coord, START_2)

        await coord.async_clear_other_charge_slots()

        assert coord.service_calls == []

    @pytest.mark.asyncio
    async def test_a_failed_end_write_fails_the_clear(self):
        coord = _coord(slot_2=TWO_TO_EIGHT)
        _fail_writes_to(coord, END_2)

        outcome = await coord.async_clear_other_charge_slots()

        assert outcome is ClearOutcome.FAILED
        assert coord._writer.write_count == 1

    @pytest.mark.asyncio
    async def test_an_entity_that_vanishes_after_the_write_fails_the_clear(self):
        coord = _coord(slot_2=TWO_TO_EIGHT)

        async def vanish(domain, service, data):
            coord.service_calls.append((domain, service, data))
            coord._states.pop(data["entity_id"], None)

        coord._call_service = vanish

        outcome = await coord.async_clear_other_charge_slots()

        assert outcome is ClearOutcome.FAILED

    @pytest.mark.asyncio
    async def test_a_write_that_never_reads_back_leaves_the_issue_raised(self):
        coord = _coord(slot_2=TWO_TO_EIGHT)

        async def stuck(domain, service, data):
            coord.service_calls.append((domain, service, data))

        coord._call_service = stuck

        await coord.async_clear_other_charge_slots()

        assert len(_raised()) == 1
        assert _cleared() == 0
