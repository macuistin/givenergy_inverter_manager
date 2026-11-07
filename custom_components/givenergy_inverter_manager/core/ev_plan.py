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
    on_cheap_rate: bool
    rate_name: str
    rate: float
    currency_symbol: str
    in_extra_hours: bool
    charge_until: str | None
    next_charge_start: str | None
    next_cheap_start: str | None
    next_cheap_name: str
    next_cheap_rate: float
    surplus_min_w: int
    # The car's own reading. None when no car is set up, its reading is stale, or the charger
    # is holding a visitor's car. The missing energy needs the battery size from the options.
    car_level_pct: float | None = None
    car_missing_kwh: float | None = None


def _price(symbol: str, rate: float) -> str:
    return f"{symbol}{rate:.2f}/kWh"


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


def _plan_text(facts: EVPlanFacts) -> str:
    if facts.pause:
        return "Paused by you. Turn Pause off and the charge carries on as planned."
    if not facts.plugged_in:
        return _unplugged_text(facts)
    if facts.charge_now:
        price = _price(facts.currency_symbol, facts.rate)
        return (
            f"Charging now at your request, at the {facts.rate_name} rate ({price}). "
            "It carries on until you turn Charge now off or unplug the car."
        )
    if not facts.can_charge_from_grid:
        return (
            "Charging from solar surplus only, from "
            f"{facts.surplus_min_w} W of spare power. This charger has no grid charge mode."
        )
    if facts.on_cheap_rate:
        return _cheap_now_text(facts)
    if facts.in_extra_hours:
        return _extra_hours_text(facts)
    return _waiting_text(facts)


def _cheap_now_text(facts: EVPlanFacts) -> str:
    price = _price(facts.currency_symbol, facts.rate)
    until = f" until {facts.charge_until}" if facts.charge_until else ""
    return (
        f"Charging at the {facts.rate_name} rate ({price}){until}. "
        "After that it charges from solar surplus only."
    )


def _extra_hours_text(facts: EVPlanFacts) -> str:
    price = _price(facts.currency_symbol, facts.rate)
    return (
        f"Charging in the extra hours you allowed around the cheap rate, at the "
        f"{facts.rate_name} rate ({price}). After them it charges from solar surplus only."
    )


def _when(facts: EVPlanFacts) -> str:
    """When the grid charge starts and the cheaper rate it is named for."""
    price = _price(facts.currency_symbol, facts.next_cheap_rate)
    rate = f"the {facts.next_cheap_name} rate ({price})"
    if facts.next_charge_start == facts.next_cheap_start:
        return f"It will charge from {facts.next_cheap_start} at {rate}"
    return (
        f"It will charge from {facts.next_charge_start}, with {rate} "
        f"from {facts.next_cheap_start}"
    )


def _waiting_text(facts: EVPlanFacts) -> str:
    solar = f"or from solar surplus of {facts.surplus_min_w} W or more"
    if facts.next_cheap_start is None:
        return f"Waiting for solar surplus of {facts.surplus_min_w} W or more."
    return f"Plugged in. {_when(facts)}, {solar}."


def _unplugged_text(facts: EVPlanFacts) -> str:
    if not facts.can_charge_from_grid or facts.next_cheap_start is None:
        return "Plug the car in and it charges from solar surplus."
    return f"Plug the car in. {_when(facts)}, or from solar surplus."
