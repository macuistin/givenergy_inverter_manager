"""The charging plan for the car, as a sentence.

It says what the charger will do and when, from the same facts the mode decision reads:
whether a car is plugged in, the owner's Charge Now and Pause switches, and the rate period.
Pure Python, no Home Assistant objects.
"""

from __future__ import annotations

from dataclasses import dataclass

from .overnight_phase import clock_text


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
    minute_of_day: float
    cheap_run_remaining_minutes: float | None
    next_cheap_start: str | None
    next_cheap_name: str
    next_cheap_rate: float
    surplus_min_w: int


def _price(symbol: str, rate: float) -> str:
    return f"{symbol}{rate:.2f}/kWh"


def ev_plan_text(facts: EVPlanFacts) -> str:
    """What the car will do, in a sentence a person can follow."""
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
    return _waiting_text(facts)


def _cheap_now_text(facts: EVPlanFacts) -> str:
    price = _price(facts.currency_symbol, facts.rate)
    until = ""
    if facts.cheap_run_remaining_minutes is not None:
        end = clock_text(facts.minute_of_day + facts.cheap_run_remaining_minutes)
        until = f" until {end}"
    return (
        f"Charging at the {facts.rate_name} rate ({price}){until}. "
        "After that it charges from solar surplus only."
    )


def _waiting_text(facts: EVPlanFacts) -> str:
    solar = f"or from solar surplus of {facts.surplus_min_w} W or more"
    if facts.next_cheap_start is None:
        return f"Waiting for solar surplus of {facts.surplus_min_w} W or more."
    price = _price(facts.currency_symbol, facts.next_cheap_rate)
    return (
        f"Plugged in. It will charge from {facts.next_cheap_start} at the "
        f"{facts.next_cheap_name} rate ({price}), {solar}."
    )


def _unplugged_text(facts: EVPlanFacts) -> str:
    if not facts.can_charge_from_grid or facts.next_cheap_start is None:
        return "Plug the car in and it charges from solar surplus."
    price = _price(facts.currency_symbol, facts.next_cheap_rate)
    return (
        f"Plug the car in. It will charge from {facts.next_cheap_start} at the "
        f"{facts.next_cheap_name} rate ({price}), or from solar surplus."
    )
