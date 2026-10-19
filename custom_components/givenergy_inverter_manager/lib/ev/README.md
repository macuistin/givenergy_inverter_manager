# lib/ev

The multi-brand EV charger model: what a charger is, how to find one from a mapping of entity
states, how to refresh it, how a charging session is tracked and when a car charging at the base
rate is worth an alert. It needs no Home Assistant objects.

## Public names

- `model`: `EVCharger`, `EVChargerBrand`, `EVChargerState`, `pick_surplus_mode`, `SURPLUS_MODE_DEFAULTS`
- `discover`: `discover_ev_chargers` (Zappi, Wallbox, OCPP, Ohme, Easee, GivEnergy charger)
- `state`: `update_charger_state`
- `session`: `EVSession`, `EVSessionLog`, `EVSessionStep`, `track_session`, `recent_table`
- `base_rate`: `AlertAction` (defined in `lib/guards`), `BaseRateReading`, `WatchState`, `watch_step`
- `defaults`: `EV_CHARGER_MIN_POWER_W`, `EV_BASE_RATE_ALERT_DELAY_S`, `EV_RECENT_SESSIONS_MAX`

## Allowed dependencies

The standard library, `lib/timeutil` and `lib/guards` (for `AlertAction`).

## Not here

The surplus arbitration between the EV and the immersion (`decide_ev_charger_action`,
`SurplusInputs`) stays in `core/rules.py`. So do the coordinator and dashboard wiring for EVs.
