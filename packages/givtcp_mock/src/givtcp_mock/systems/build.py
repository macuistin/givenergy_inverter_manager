"""Builds the synthetic GivTCP system fixtures from the one real one.

Run `python -m givtcp_mock.systems.build` to rewrite the JSON files. A test compares the
committed files with what this builds, so the two cannot drift apart.

Only `hybrid_gen3_two_batteries_3_6_3.json` was taken from real hardware. Every other fixture is
built here from GivTCP's published datapoint reference and release notes, by changing the real
one: the entity names that datapoint reference gives for a kind are added, and the ones it says
that kind lacks are removed. The exact entity names for kinds other than the single-phase hybrid
are therefore a best reading of the documentation, and each file says so. A fixture from a real
system of that kind replaces its synthetic one.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
REAL = "hybrid_gen3_two_batteries_3_6_3"
BASE = "givtcp_ab1234g567"
SYNTHETIC_SOURCE = (
    "Built from the real single-phase hybrid fixture and GivTCP's datapoint reference and "
    "release notes (3.6). Not taken from hardware of this kind: the entity names are a reading "
    "of the documentation."
)


def load_real() -> dict[str, Any]:
    real: dict[str, Any] = json.loads((HERE / f"{REAL}.json").read_text())
    return real


def _rename(states: dict[str, Any], old: str, new: str) -> dict[str, Any]:
    return {k.replace(f".{old}_", f".{new}_"): v for k, v in states.items()}


def _device(states: dict[str, Any], prefix: str) -> dict[str, Any]:
    """The entities of the inverter device only, with the battery and meter devices left out."""
    return {k: v for k, v in states.items() if k.partition(".")[2].startswith(f"{BASE}_")}


def _set(states: dict[str, Any], prefix: str, suffix: str, state: str, domain: str = "sensor") -> None:
    states[f"{domain}.{prefix}_{suffix}"] = {"state": state}


def _drop(states: dict[str, Any], prefix: str, *suffixes: str) -> None:
    for suffix in suffixes:
        for domain in ("sensor", "number", "switch", "select", "time", "button"):
            states.pop(f"{domain}.{prefix}_{suffix}", None)


def _strings(prefix: str) -> list[str]:
    return [f"pv_{kind}_string_{n}" for kind in ("power", "voltage", "current") for n in (1, 2)]


def _fixture(name: str, description: str, states: dict[str, Any], **expected: Any) -> dict[str, Any]:
    return {
        "description": description,
        "provenance": "synthetic",
        "givtcp_version": expected.pop("version", "3.6.3"),
        "source": SYNTHETIC_SOURCE,
        "expected": expected,
        "states": dict(sorted(states.items())),
    }


def _extra_device(
    real: dict[str, Any], prefix: str, serial: str, invertor_type: str, version: str = "3.6.3"
) -> dict[str, Any]:
    """A second inverter-like device, copied from the real one under another prefix."""
    device = _rename(_device(real["states"], BASE), BASE, prefix)
    device = copy.deepcopy(device)
    device[f"sensor.{prefix}_invertor_serial_number"] = {"state": serial}
    device[f"sensor.{prefix}_invertor_type"] = {"state": invertor_type}
    device[f"sensor.{prefix}_givtcp_version"] = {"state": version}
    return device


def _base(real: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(real["states"])


def _charger(prefix: str, serial: str, connection: str, state: str, mode: str) -> dict[str, Any]:
    """The entities GivTCP publishes for a GivEnergy charger (GivEVC)."""
    out = {
        f"sensor.{prefix}_serial_number": {"state": serial},
        f"sensor.{prefix}_charging_state": {"state": state},
        f"sensor.{prefix}_connection_status": {"state": connection},
        f"sensor.{prefix}_error_code": {"state": "0"},
        f"sensor.{prefix}_active_power": {"state": "0" if state != "Charging" else "1380"},
        f"sensor.{prefix}_charge_session_energy": {"state": "2.4"},
        f"sensor.{prefix}_charge_session_duration": {"state": "1800"},
        f"sensor.{prefix}_meter_energy": {"state": "812.5"},
        f"switch.{prefix}_plug_and_go": {"state": "on"},
        f"select.{prefix}_charge_control": {
            "state": "Start",
            "attributes": {"options": ["Start", "Stop"]},
        },
        f"select.{prefix}_charging_mode": {
            "state": mode,
            "attributes": {"options": ["Grid", "Solar", "Hybrid"]},
        },
        f"number.{prefix}_charge_limit": {"state": "32"},
        f"number.{prefix}_import_cap": {"state": "0"},
        f"number.{prefix}_max_session_energy": {"state": "0"},
    }
    return out


def build() -> dict[str, dict[str, Any]]:  # noqa: PLR0915
    real = load_real()
    out: dict[str, dict[str, Any]] = {}

    # SYS-14: the prefix is a setting per inverter in GivTCP.
    states = _rename(_base(real), BASE, "house_ab1234g567")
    out["hybrid_custom_prefix_3_6_3"] = _fixture(
        "hybrid_custom_prefix_3_6_3",
        "The real hybrid with the device prefix changed from givtcp to house.",
        states,
        kind="hybrid", controller="AB1234G567", ask=False, modules=2, prefix="house_ab1234g567",
    )

    # SYS-06: AC-coupled has no PV string values.
    states = _base(real)
    _drop(states, BASE, *_strings(BASE))
    _set(states, BASE, "invertor_type", "AC")
    out["ac_coupled_3_6_3"] = _fixture(
        "ac_coupled_3_6_3",
        "AC-coupled: no PV string values, type AC.",
        states,
        kind="ac_coupled", controller="AB1234G567", ask=False, modules=2,
    )

    # SYS-08: a single All-In-One.
    states = _base(real)
    _drop(states, BASE, *_strings(BASE))
    _set(states, BASE, "invertor_type", "All_in_one")
    out["all_in_one_3_6_3"] = _fixture(
        "all_in_one_3_6_3",
        "A single All-In-One with no Gateway.",
        states,
        kind="all_in_one", controller="AB1234G567", ask=False, modules=2,
    )

    # SYS-11: three-phase publishes per-phase values.
    states = _base(real)
    _set(states, BASE, "invertor_type", "Three_phase")
    for suffix in ("grid_phase_1_voltage", "load_phase_1_power", "export_phase_1_power",
                   "meter_import_power", "meter_export_power"):
        _set(states, BASE, suffix, "0")
    for suffix in ("force_charge_enable", "force_discharge_enable"):
        _set(states, BASE, suffix, "off", "switch")
    out["three_phase_3_6_3"] = _fixture(
        "three_phase_3_6_3",
        "Three-phase: per-phase voltage and power, meter import and export, force enables.",
        states,
        kind="three_phase", controller="AB1234G567", ask=False, modules=2,
    )

    # SYS-10: parallel All-In-Ones behind a Gateway. The units are entries of the Gateway device.
    gw = "givtcp_gw5678k901"
    states = _rename(_device(real["states"], BASE), BASE, gw)
    states = copy.deepcopy(states)
    _drop(states, gw, *_strings(gw), "invertor_serial_number")
    _set(states, gw, "invertor_type", "Gateway")
    for suffix, value in (("gateway_state", "Normal"), ("gateway_mode", "Auto"),
                          ("parallel_total_aio_number", "2"),
                          ("parallel_total_aio_online_number", "2"),
                          ("liberty_power", "0"), ("grid_relay_voltage", "238.1"),
                          ("aio_1_soc", "55"), ("aio_2_soc", "52"),
                          ("aio_1_invertor_power", "300"), ("aio_2_invertor_power", "310")):
        _set(states, gw, suffix, value)
    out["gateway_parallel_two_aio_3_6_3"] = _fixture(
        "gateway_parallel_two_aio_3_6_3",
        "A Gateway over two parallel All-In-Ones. The units are entries of the Gateway device and "
        "it publishes no serial sensor, so it is found by its version sensor and its Gateway values.",
        states,
        kind="gateway", controller="GW5678K901", ask=False, modules=None,
        controller_serial_from="prefix",
    )

    # SYS-09: an All-In-One and a Gateway that is not parallel. Manage the All-In-One.
    states = _base(real)
    _drop(states, BASE, *_strings(BASE))
    _set(states, BASE, "invertor_type", "All_in_one")
    gateway = _rename(_device(real["states"], BASE), BASE, gw)
    gateway = copy.deepcopy(gateway)
    _drop(gateway, gw, *_strings(gw), "invertor_serial_number")
    for suffix, value in (("gateway_state", "Normal"), ("gateway_mode", "Auto"),
                          ("parallel_total_aio_number", "1")):
        _set(gateway, gw, suffix, value)
    states.update(gateway)
    out["all_in_one_and_gateway_3_6_3"] = _fixture(
        "all_in_one_and_gateway_3_6_3",
        "One All-In-One and a Gateway that is not in parallel. The All-In-One is managed.",
        states,
        kind="all_in_one", controller="AB1234G567", ask=False, modules=None,
    )

    # SYS-12: two separate inverters.
    states = _base(real)
    states.update(_extra_device(real, "givtcp_cd5678h901", "CD5678H901", "Hybrid_gen3"))
    out["two_hybrids_3_6_3"] = _fixture(
        "two_hybrids_3_6_3",
        "Two separate hybrid inverters. The user is asked which to manage.",
        states,
        kind="hybrid", controller="AB1234G567", ask=True, modules=None, devices=2,
    )

    # SYS-17: an EMS publishes plant values and no state of charge of its own.
    ems = "givtcp_em9012m345"
    states = {
        f"sensor.{ems}_givtcp_version": {"state": "3.6.3"},
        f"sensor.{ems}_status": {"state": "online"},
        f"sensor.{ems}_data_age": {"state": "1.0"},
        f"sensor.{ems}_plant_status": {"state": "Normal"},
        f"sensor.{ems}_inverter_count": {"state": "2"},
        f"sensor.{ems}_calculated_load_power": {"state": "900"},
        f"sensor.{ems}_measured_load_power": {"state": "900"},
        f"select.{ems}_plant_control": {"state": "Auto"},
    }
    out["ems_3_6_3"] = _fixture(
        "ems_3_6_3",
        "An EMS plant: plant values only, no state of charge or PV power, no serial sensor.",
        states,
        kind="ems", controller="EM9012M345", ask=False, modules=None,
        controller_serial_from="prefix",
    )

    # SYS-05 and SYS-31: an HV Gen 3 hybrid before and after GivTCP 3.6.
    states = _base(real)
    for suffix in ("pv_power", "soc", "soc_kwh"):
        _set(states, BASE, suffix, "0")
    _set(states, BASE, "invertor_type", "AIO")
    _set(states, BASE, "givtcp_version", "3.5.68")
    for suffix in ("grid_phase_1_voltage", "load_phase_1_power", "export_phase_1_power",
                   "meter_import_power"):
        _set(states, BASE, suffix, "0")
    out["hv_gen3_before_3_6"] = _fixture(
        "hv_gen3_before_3_6",
        "An HV Gen 3 hybrid on GivTCP 3.5: read with the three-phase layout, labelled All-In-One, "
        "state of charge and PV power 0.",
        states,
        version="3.5.68",
        kind="three_phase", controller="AB1234G567", ask=False, modules=2,
    )
    out["hv_gen3_after_3_6"] = _fixture(
        "hv_gen3_after_3_6",
        "The same HV Gen 3 hybrid on GivTCP 3.6: the single-phase entity set.",
        _base(real),
        kind="hybrid", controller="AB1234G567", ask=False, modules=2,
    )

    # SYS-29: a battery slot that answers with zeros is not a module.
    states = _base(real)
    for suffix, value in (("battery_serial_number", "0000000000"), ("battery_soc", "0"),
                          ("battery_capacity", "0.0")):
        states[f"sensor.givtcp_gh0000h000_{suffix}"] = {"state": value}
    out["hybrid_with_ghost_battery_3_6_3"] = _fixture(
        "hybrid_with_ghost_battery_3_6_3",
        "The real hybrid and a third battery slot that reads all zeros.",
        states,
        kind="hybrid", controller="AB1234G567", ask=False, modules=2,
    )

    # SYS-16: a GivEnergy EV charger beside the inverter is not an inverter. The datapoint names
    # and the state strings are GivTCP's own (DATAPOINTS.md and evc.py). The prefix is a guess.
    states = _base(real)
    states.update(_charger("givtcp_evc_ev1234a567", "EV1234A567", "Connected", "Charging", "Solar"))
    out["hybrid_with_ev_charger_3_6_3"] = _fixture(
        "hybrid_with_ev_charger_3_6_3",
        "The real hybrid with a GivTCP EV charger device (GivEVC) beside it, charging in Solar mode.",
        states,
        kind="hybrid", controller="AB1234G567", ask=False, modules=2, devices=1,
    )

    # A charger on its own, as the charger tests use it.
    out["givenergy_charger_only"] = _fixture(
        "givenergy_charger_only",
        "A GivEnergy charger (GivEVC) with a car plugged in and not charging, in Grid mode.",
        _charger("givtcp_evc_ev1234a567", "EV1234A567", "Connected", "Connected", "Grid"),
    )
    return out


def write() -> None:
    for name, fixture in build().items():
        (HERE / f"{name}.json").write_text(json.dumps(fixture, indent=1) + "\n")


if __name__ == "__main__":
    write()
