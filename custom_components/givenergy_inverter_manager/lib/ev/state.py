"""state.py: refresh a discovered charger from the current entity states."""

from __future__ import annotations

from .model import ACTIVE_STATES, EVCharger, EVChargerState


def _options_of(state: object) -> tuple[str, ...] | None:
    """The options a select reports in its `options` attribute, None when it reports none."""
    options = getattr(state, "attributes", {}).get("options")
    if not isinstance(options, (list, tuple)) or not options:
        return None
    return tuple(str(option) for option in options)


def update_charger_state(  # noqa: C901
    get_state,
    charger: EVCharger,
    battery_power_w: float,
) -> EVCharger:
    """
    Refresh a charger's runtime state from current HA entity values.

    Accepts a get_state callable (entity_id → state_object | None) rather than
    the HA hass object, keeping this function HA-free and testable. The
    coordinator passes its _get_state() proxy method here.

    Sets is_draining_battery = True when:
      - Charger is actively delivering energy (charging or boosting)
      - Battery is discharging (battery_power_w < -200W, 200W noise floor)

    Mutates and returns the charger object.
    """

    def _read_state(eid: str | None) -> str | None:
        if not eid:
            return None
        s = get_state(eid)
        return s.state if s and s.state not in ("unavailable", "unknown") else None

    def _read_float(eid: str | None) -> float:
        raw = _read_state(eid)
        if raw is None:
            return 0.0
        try:
            return float(raw)
        except (ValueError, TypeError):
            return 0.0

    raw = _read_state(charger.status_entity)
    if raw is not None:
        charger.state = charger.normalise_state(raw)

    charger.power_w = _read_float(charger.power_entity)
    charger.session_kwh = _read_float(charger.session_energy_entity)

    activity = _read_state(charger.activity_entity)
    if activity is not None and charger.is_plugged_in:
        activity_state = charger.normalise_state(activity)
        if activity_state is not EVChargerState.UNKNOWN and not (
            activity_state in ACTIVE_STATES and not charger.is_drawing_power
        ):
            charger.state = activity_state

    raw_mode = _read_state(charger.charge_mode_entity)
    if raw_mode is not None:
        charger.charge_mode = raw_mode
        charger.charge_mode_options = _options_of(get_state(charger.charge_mode_entity))

    charger.is_draining_battery = charger.is_active and battery_power_w < -200

    return charger
