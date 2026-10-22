"""
wizard_pages.py - the battery, forecast, hot water and EV pages, and the inverter wiring.

Each page works on the flat values the form submits (sections already merged in), and gives:

  validate(values, ctx)  errors that stop the page, and warnings that only ask the user to look
  clean(values)          the values to store, under the flat config keys the page owns
  summary(values)        one line for the checklist and the confirm step

A page works with every field empty. An entity the user cleared is stored as an empty string,
so it hides the setup value, and the same string reads as unset everywhere else.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..const import (
    ALT_HEAT_LABEL_MAX_LENGTH,
    CONF_ALT_HEAT_COST,
    CONF_ALT_HEAT_COST_ENTITY,
    CONF_ALT_HEAT_COST_UNIT,
    CONF_ALT_HEAT_ENABLED,
    CONF_ALT_HEAT_LABEL,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_COST,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_THROUGHPUT_BUDGET,
    CONF_CAR_EFFICIENCY_KWH_PER_100KM,
    CONF_CARBON_INTENSITY_ENTITY,
    CONF_CHARGE_SHOULDER_MONTHS,
    CONF_CHARGE_WINTER_MONTHS,
    CONF_CHARGE_WINTER_USES_FORECAST,
    CONF_CHEAP_RATE_FLOOR_SOC,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_D2,
    CONF_FORECAST_ENTITY_P10,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_IMMERSION_MAX_RUN_MINUTES,
    CONF_IMMERSION_READY_TIMES,
    CONF_IMMERSION_RUN_LIMIT_WARNING,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_IMMERSION_WATTAGE,
    CONF_INVERTER_MAX_OUTPUT,
    CONF_INVERTER_MAX_OUTPUT_ENTITY,
    CONF_OVERNIGHT_CHARGE_TARGET,
    CONF_SOLAR_POWER,
    DEFAULT_ALT_HEAT_UNIT,
    DEFAULT_BATTERY_MIN_SOC,
    DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM,
    DEFAULT_CHEAP_RATE_FLOOR_SOC,
    DEFAULT_OVERNIGHT_CHARGE_TARGET,
)
from .alt_heat_label import clean_label
from .immersion_ready import parse_ready_times
from .seasons import overlapping_months
from .wizard_model import PageContext, Validation

# Ready-by times: up to four a day is what the planning is built for. More is allowed.
EXPECTED_READY_TIMES = 4
_ENERGY_UNITS = ("kwh", "wh")
_SECTION_NAMES = ("bill_details", "alt_heat")

WIRING_REQUIRED = (
    CONF_SOLAR_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_POWER,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
)


def flatten_sections(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """The submission with the section dicts merged into it, one level deep."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if key in _SECTION_NAMES and isinstance(value, Mapping):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def _entity(values: Mapping[str, Any], key: str) -> str:
    """The entity chosen for *key*, or an empty string when the user cleared it."""
    return str(values.get(key) or "")


# ── Wiring (the inverter entities) ────────────────────────────────────────────


def missing_wiring(values: Mapping[str, Any]) -> dict[str, str]:
    """A form error when one of the five required inverter entities is not chosen."""
    if any(not values.get(key) for key in WIRING_REQUIRED):
        return {"base": "missing_entities"}
    return {}


def unavailable_wiring(values: Mapping[str, Any], states: Mapping[str, Any]) -> dict[str, str]:
    """A form error when a required entity does not exist or reads unavailable."""
    for key in WIRING_REQUIRED:
        state = states.get(values.get(key))
        if state is None or state.state in ("unavailable", "unknown"):
            return {"base": "missing_entities"}
    return {}


# ── Battery ───────────────────────────────────────────────────────────────────


def validate_charge_planning(values: Mapping[str, Any], ctx: PageContext) -> Validation:
    """A month in both season lists is an error. Warn when the floor sits below the minimum."""
    if overlapping_months(
        values.get(CONF_CHARGE_WINTER_MONTHS), values.get(CONF_CHARGE_SHOULDER_MONTHS)
    ):
        return Validation(errors={"base": "season_months_overlap"})
    floor = ctx.current.get(CONF_CHEAP_RATE_FLOOR_SOC, DEFAULT_CHEAP_RATE_FLOOR_SOC)
    minimum = values.get(CONF_BATTERY_MIN_SOC)
    if minimum is not None and floor and float(floor) < float(minimum):
        return Validation(
            warnings=(
                f"The Cheap rate floor SoC control ({float(floor):g}%) is below the battery "
                f"minimum charge you set ({float(minimum):g}%). Raise the floor or set it to 0.",
            )
        )
    return Validation()


def validate_battery(values: Mapping[str, Any], ctx: PageContext) -> Validation:  # noqa: ARG001
    """The battery limits have nothing to cross-check: each is a range the form enforces."""
    return Validation()


def clean_battery(values: Mapping[str, Any]) -> dict[str, Any]:
    """The battery limits the form sends, as numbers. A field not sent is left out."""
    cleaned: dict[str, Any] = {}
    for key in (CONF_BATTERY_CAPACITY, CONF_INVERTER_MAX_OUTPUT, CONF_BATTERY_COST):
        if key in values:
            cleaned[key] = float(values[key])
    if CONF_BATTERY_CAPACITY in values or CONF_INVERTER_MAX_OUTPUT in values:
        # The form sends the numbers always. A cleared sensor field is left out of the
        # submission, so it is stored as empty here.
        for key in (CONF_BATTERY_CAPACITY_ENTITY, CONF_INVERTER_MAX_OUTPUT_ENTITY):
            cleaned[key] = _entity(values, key)
    if CONF_BATTERY_THROUGHPUT_BUDGET in values:
        cleaned[CONF_BATTERY_THROUGHPUT_BUDGET] = float(values[CONF_BATTERY_THROUGHPUT_BUDGET])
    return cleaned


def clean_charge_planning(values: Mapping[str, Any]) -> dict[str, Any]:
    """The charge planning settings the form sends. A field not sent is left out."""
    cleaned: dict[str, Any] = {}
    for key in (CONF_BATTERY_MIN_SOC, CONF_OVERNIGHT_CHARGE_TARGET):
        if key in values:
            cleaned[key] = int(values[key])
    return {**cleaned, **_clean_seasons(values)}


def _clean_seasons(values: Mapping[str, Any]) -> dict[str, Any]:
    """The season month lists as sorted month numbers, and the winter behaviour as a bool."""
    cleaned: dict[str, Any] = {}
    for key in (CONF_CHARGE_WINTER_MONTHS, CONF_CHARGE_SHOULDER_MONTHS):
        if key in values:
            cleaned[key] = sorted({int(month) for month in values[key]})
    if CONF_CHARGE_WINTER_USES_FORECAST in values:
        cleaned[CONF_CHARGE_WINTER_USES_FORECAST] = bool(values[CONF_CHARGE_WINTER_USES_FORECAST])
    return cleaned


def charge_planning_summary(cfg: Mapping[str, Any]) -> str:
    """The charge planning limits on one line."""
    minimum = int(cfg.get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC))
    cap = int(cfg.get(CONF_OVERNIGHT_CHARGE_TARGET, DEFAULT_OVERNIGHT_CHARGE_TARGET))
    return f"minimum charge {minimum}%, overnight cap {cap}%"


def battery_summary(cfg: Mapping[str, Any]) -> str:
    """The battery on one line."""
    return (
        f"battery {float(cfg.get(CONF_BATTERY_CAPACITY, 0)):g} kWh, "
        f"inverter {float(cfg.get(CONF_INVERTER_MAX_OUTPUT, 0)):g} kW"
    )


# ── Forecast ──────────────────────────────────────────────────────────────────

_FORECAST_KEYS = (
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_P10,
    CONF_FORECAST_ENTITY_D2,
    CONF_CARBON_INTENSITY_ENTITY,
)
_FORECAST_ENERGY_KEYS = (CONF_FORECAST_ENTITY, CONF_FORECAST_ENTITY_P10, CONF_FORECAST_ENTITY_D2)


def _reads_a_number(state: Any) -> bool:
    try:
        float(state.state)
    except (TypeError, ValueError):
        return False
    return True


def sensor_check(entity_id: str, states: Mapping[str, Any]) -> str:
    """What one sensor reads now, in a sentence. Read only."""
    state = states.get(entity_id)
    if state is None:
        return f"{entity_id} does not exist."
    if state.state in ("unavailable", "unknown"):
        return f"{entity_id} is {state.state} at the moment."
    unit = (getattr(state, "attributes", None) or {}).get("unit_of_measurement") or ""
    return f"{entity_id} reads {state.state} {unit}".rstrip() + "."


def validate_forecast(values: Mapping[str, Any], ctx: PageContext) -> Validation:
    """Warn when a forecast sensor does not read a number in kWh or Wh."""
    odd = []
    for key in _FORECAST_ENERGY_KEYS:
        entity_id = _entity(values, key)
        state = ctx.states.get(entity_id) if entity_id else None
        if state is None or state.state in ("unavailable", "unknown"):
            continue
        unit = str((getattr(state, "attributes", None) or {}).get("unit_of_measurement") or "")
        if not _reads_a_number(state) or unit.lower() not in _ENERGY_UNITS:
            odd.append(entity_id)
    if not odd:
        return Validation()
    return Validation(
        warnings=(
            f"{', '.join(odd)} does not read a number in kWh or Wh. "
            "A forecast sensor normally does.",
        )
    )


def clean_forecast(values: Mapping[str, Any]) -> dict[str, Any]:
    """The four sensors. One the user left out was cleared, so it is stored empty."""
    return {key: _entity(values, key) for key in _FORECAST_KEYS}


def forecast_summary(cfg: Mapping[str, Any]) -> str:
    """The forecast on one line."""
    sensor = cfg.get(CONF_FORECAST_ENTITY)
    return f"forecast sensor: {sensor}" if sensor else "forecast: none, a seasonal estimate is used"


# ── Hot water and alternative heating ─────────────────────────────────────────


def alt_heat_label_errors(values: Mapping[str, Any]) -> dict[str, str]:
    """The label has to hold something and fit the sentences, while the setting is on.

    A label left empty or too long is refused rather than cut, so what the user typed is what
    the sentences say. Only a submission that carries a label is checked.
    """
    if not values.get(CONF_ALT_HEAT_ENABLED) or CONF_ALT_HEAT_LABEL not in values:
        return {}
    label = " ".join(str(values[CONF_ALT_HEAT_LABEL] or "").split())
    if not label:
        return {"base": "alt_heat_label_empty"}
    if len(label) > ALT_HEAT_LABEL_MAX_LENGTH:
        return {"base": "alt_heat_label_too_long"}
    return {}


def _ready_time_errors(values: Mapping[str, Any]) -> dict[str, str]:
    """Every ready time has to read as HH:MM, so a typo is not silently dropped."""
    submitted = values.get(CONF_IMMERSION_READY_TIMES) or []
    if not all(parse_ready_times([item]) for item in submitted):
        return {"base": "immersion_ready_time_invalid"}
    return {}


def _hot_water_warnings(values: Mapping[str, Any]) -> tuple[str, ...]:
    warnings = []
    ready = values.get(CONF_IMMERSION_READY_TIMES) or []
    if ready and not _entity(values, CONF_IMMERSION_TEMP_SENSOR):
        warnings.append(
            "Ready-by times need a hot water temperature sensor. Until one is set, no heating "
            "is planned for them."
        )
    if len(ready) > EXPECTED_READY_TIMES:
        warnings.append(
            f"You entered {len(ready)} ready-by times. Up to {EXPECTED_READY_TIMES} a day is "
            "what the planning is built for."
        )
    if values.get(CONF_ALT_HEAT_ENABLED) and not _entity(values, CONF_IMMERSION_SWITCH):
        warnings.append("Alternative heating gives no advice until an immersion switch is set.")
    has_cost = values.get(CONF_ALT_HEAT_COST) or _entity(values, CONF_ALT_HEAT_COST_ENTITY)
    if values.get(CONF_ALT_HEAT_ENABLED) and not has_cost:
        warnings.append("Alternative heating gives no advice until a cost or a cost sensor is set.")
    return tuple(warnings)


def validate_hot_water(values: Mapping[str, Any], _ctx: PageContext) -> Validation:
    """Errors for a bad ready time or label, warnings for what is missing."""
    errors = _ready_time_errors(values) or alt_heat_label_errors(values)
    return Validation(errors=errors, warnings=_hot_water_warnings(values))


_ALT_HEAT_KEYS = (
    CONF_ALT_HEAT_ENABLED,
    CONF_ALT_HEAT_LABEL,
    CONF_ALT_HEAT_COST_UNIT,
    CONF_ALT_HEAT_COST,
    CONF_ALT_HEAT_COST_ENTITY,
)


def _clean_alt_heat(values: Mapping[str, Any]) -> dict[str, Any]:
    """The alternative heating values, or none when the submission carries no such section."""
    if not any(key in values for key in _ALT_HEAT_KEYS):
        return {}
    cleaned: dict[str, Any] = {}
    if CONF_ALT_HEAT_ENABLED in values:
        cleaned[CONF_ALT_HEAT_ENABLED] = bool(values[CONF_ALT_HEAT_ENABLED])
    if CONF_ALT_HEAT_LABEL in values:
        cleaned[CONF_ALT_HEAT_LABEL] = clean_label(values[CONF_ALT_HEAT_LABEL])
    unit = values.get(CONF_ALT_HEAT_COST_UNIT, DEFAULT_ALT_HEAT_UNIT)
    cleaned[CONF_ALT_HEAT_COST_UNIT] = str(unit)
    cost = values.get(CONF_ALT_HEAT_COST)
    cleaned[CONF_ALT_HEAT_COST] = float(cost) if cost not in (None, "") else ""
    cleaned[CONF_ALT_HEAT_COST_ENTITY] = _entity(values, CONF_ALT_HEAT_COST_ENTITY)
    return cleaned


def clean_hot_water(values: Mapping[str, Any]) -> dict[str, Any]:
    """The immersion devices, element power, ready times and alternative heating."""
    times = parse_ready_times(values.get(CONF_IMMERSION_READY_TIMES) or [])
    cleaned: dict[str, Any] = {
        CONF_IMMERSION_SWITCH: _entity(values, CONF_IMMERSION_SWITCH),
        CONF_IMMERSION_TEMP_SENSOR: _entity(values, CONF_IMMERSION_TEMP_SENSOR),
        CONF_IMMERSION_READY_TIMES: [f"{at:%H:%M}" for at in times],
    }
    if CONF_IMMERSION_WATTAGE in values:
        cleaned[CONF_IMMERSION_WATTAGE] = float(values[CONF_IMMERSION_WATTAGE])
    if CONF_IMMERSION_MAX_RUN_MINUTES in values:
        cleaned[CONF_IMMERSION_MAX_RUN_MINUTES] = int(values[CONF_IMMERSION_MAX_RUN_MINUTES])
    if CONF_IMMERSION_RUN_LIMIT_WARNING in values:
        cleaned[CONF_IMMERSION_RUN_LIMIT_WARNING] = bool(values[CONF_IMMERSION_RUN_LIMIT_WARNING])
    cleaned.update(_clean_alt_heat(values))
    return cleaned


def hot_water_summary(cfg: Mapping[str, Any]) -> str:
    """The hot water set-up on one line."""
    switch = cfg.get(CONF_IMMERSION_SWITCH)
    parts = [f"immersion switch {switch}" if switch else "no immersion switch"]
    if cfg.get(CONF_ALT_HEAT_ENABLED):
        parts.append(f"alternative heating: {clean_label(cfg.get(CONF_ALT_HEAT_LABEL))}")
    return ", ".join(parts)


# ── EV ────────────────────────────────────────────────────────────────────────


def clean_ev(values: Mapping[str, Any]) -> dict[str, Any]:
    """The car efficiency, when the form sends it."""
    if CONF_CAR_EFFICIENCY_KWH_PER_100KM in values:
        return {CONF_CAR_EFFICIENCY_KWH_PER_100KM: float(values[CONF_CAR_EFFICIENCY_KWH_PER_100KM])}
    return {}


def ev_summary(cfg: Mapping[str, Any]) -> str:
    """The car efficiency on one line."""
    efficiency = cfg.get(CONF_CAR_EFFICIENCY_KWH_PER_100KM, DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM)
    return f"car efficiency {float(efficiency):g} kWh per 100 km"
