"""
system_text.py: what the setup screen says about the GivTCP system it found, in plain words.

It covers which device is managed and why, what is read-only, and which system types have only
been tested against entity lists. Roadmap and card ids never appear in these lines.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from .system_types import KIND_LABELS, TESTED_ON_REAL_HARDWARE, InverterFacts, Selection, SystemKind


def describe(selection: Selection) -> list[str]:
    """The lines for the system step, the first being the inverter that will be managed."""
    controller = selection.controller
    if controller is None:
        return ["No GivTCP inverter was found. You will choose its entities next."]
    lines = [_controller_line(controller)]
    if selection.note:
        lines.append(selection.note)
    if selection.units:
        lines.append(f"Read-only units behind it: {_names(selection.units)}.")
    if selection.others and not selection.ask:
        lines.append(f"Also found, not managed: {_names(selection.others)}.")
    lines.extend(_cautions(controller))
    return lines


def _controller_line(device: InverterFacts) -> str:
    named = f"Inverter: GivTCP {device.serial} ({KIND_LABELS[device.kind]})"
    if not device.complete:
        return f"{named}, but some sensors are missing. You will choose them next."
    return f"{named}, all sensors found and used."


def _cautions(device: InverterFacts) -> list[str]:
    lines = []
    if device.kind not in TESTED_ON_REAL_HARDWARE:
        lines.append(
            f"A {KIND_LABELS[device.kind]} has not been tested on real hardware. "
            "Leave dry run on and check what it plans."
        )
    if device.kind is SystemKind.EMS:
        lines.append("An EMS runs the plant itself, so no charge settings will be written.")
    elif device.complete and not device.can_schedule:
        lines.append("Its charge controls were not found, so no charge settings will be written.")
    return lines


def _names(devices: tuple[InverterFacts, ...]) -> str:
    return ", ".join(f"{d.serial} ({KIND_LABELS[d.kind]})" for d in devices)
