"""The lines the system step shows about what was found."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.core.system_text import describe
from custom_components.givenergy_inverter_manager.core.system_types import (
    InverterFacts,
    Selection,
    SystemKind,
)


def _facts(serial: str, kind: SystemKind, **kw) -> InverterFacts:
    return InverterFacts(
        serial=serial,
        prefix=f"givtcp_{serial}",
        kind=kind,
        complete=kw.pop("complete", True),
        can_schedule=kw.pop("can_schedule", True),
        **kw,
    )


def test_nothing_found_says_the_entities_come_next():
    assert describe(Selection(controller=None, ask=False)) == [
        "No GivTCP inverter was found. You will choose its entities next."
    ]


def test_the_units_behind_a_gateway_are_listed_as_read_only():
    gateway = _facts("gw1", SystemKind.GATEWAY)
    unit = _facts("aio1", SystemKind.ALL_IN_ONE)

    lines = describe(Selection(controller=gateway, ask=False, units=(unit,)))

    assert any(line.startswith("Read-only units behind it:") and "aio1" in line for line in lines)


def test_a_device_found_and_not_managed_is_mentioned_once_the_choice_is_made():
    chosen = _facts("hy1", SystemKind.HYBRID)
    other = _facts("hy2", SystemKind.HYBRID)

    lines = describe(Selection(controller=chosen, ask=False, others=(other,)))

    assert any(line.startswith("Also found, not managed:") and "hy2" in line for line in lines)


def test_an_ems_says_no_charge_settings_will_be_written():
    ems = _facts("em1", SystemKind.EMS)

    assert any("EMS runs the plant itself" in line for line in describe(Selection(ems, False)))


def test_a_complete_device_without_charge_controls_says_nothing_will_be_written():
    hybrid = _facts("hy1", SystemKind.HYBRID, can_schedule=False)

    assert any("charge controls were not found" in line for line in describe(Selection(hybrid, False)))


def test_missing_sensors_send_the_user_to_choose_them():
    hybrid = _facts("hy1", SystemKind.HYBRID, complete=False)

    assert "some sensors are missing" in describe(Selection(hybrid, False))[0]
