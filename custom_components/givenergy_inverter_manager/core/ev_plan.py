"""The charging plan for the car, as a sentence.

It says what the charger will do and when, from the same facts the mode decision reads:
whether a car is plugged in, the owner's Charge Now and Pause switches, and the rate period.
Pure Python, no Home Assistant objects.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EVPlanFacts:
    """What the plan sentence needs."""

    plugged_in: bool
    can_charge_from_grid: bool
    charge_now: bool
    pause: bool
    in_window: bool
    window_start: str
    window_end: str
    surplus_min_w: int
    # The car's own reading. None when no car is set up, its reading is stale, or the charger
    # is holding a visitor's car. The missing energy needs the battery size from the options.
    car_level_pct: float | None = None
    car_missing_kwh: float | None = None


def ev_plan_text(facts: EVPlanFacts) -> str:
    """What the car will do, in a sentence a person can follow, with the car's level if known."""
    car = _car_text(facts)
    plan = _plan_text(facts)
    return f"{plan} {car}" if car else plan


def _car_text(facts: EVPlanFacts) -> str:
    """The car's charge and what it needs, empty when the car is not known."""
    level = facts.car_level_pct
    if level is None:
        return ""
    if level >= 99.5:
        return "The car is full."
    if facts.car_missing_kwh is None:
        return f"The car is at {level:.0f}%."
    return f"The car is at {level:.0f}%, about {facts.car_missing_kwh:.0f} kWh to reach 100%."


def _hours(facts: EVPlanFacts) -> str:
    return f"{facts.window_start} to {facts.window_end}"


def _plan_text(facts: EVPlanFacts) -> str:
    if not facts.can_charge_from_grid:
        return (
            "Charging from solar surplus only, from "
            f"{facts.surplus_min_w} W of spare power. This charger has no grid charge mode."
        )
    if facts.in_window:
        return _window_text(facts)
    if facts.pause:
        return "Paused by you. Turn Pause off and the charge carries on as planned."
    if not facts.plugged_in:
        return f"Plug the car in. It charges from {_hours(facts)}, or from solar surplus."
    if facts.charge_now:
        return (
            "Charging now at your request. "
            "It carries on until you turn Charge now off or unplug the car."
        )
    return (
        f"Plugged in. It charges from {_hours(facts)}, "
        f"or from solar surplus of {facts.surplus_min_w} W or more."
    )


def _window_text(facts: EVPlanFacts) -> str:
    """Inside the window the schedule wins, so Pause and Charge now change nothing."""
    if not facts.plugged_in:
        return f"Plug the car in and it charges until {facts.window_end}."
    note = " Pause is ignored in this window." if facts.pause else ""
    return (
        f"Charging on your schedule until {facts.window_end}. "
        f"After that it charges from solar surplus only.{note}"
    )
