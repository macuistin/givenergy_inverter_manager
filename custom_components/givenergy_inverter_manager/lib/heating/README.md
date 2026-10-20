# lib/heating

The hot-water heating planner. It works out how long a heater must run to bring water to a target
temperature by a ready time, places that run in the cheapest rate bands, learns the heating rate
from the heater's own runs and describes the plan. It needs no Home Assistant objects and nothing
in it is specific to one inverter.

## Public names

- `ready`: `ReadyInputs`, `ReadyPlan`, `plan_ready`, `parse_ready_times`, `next_ready_at`, `hours_to_heat`, `place_hours`
- `window`: `open_cheapest_window`, `next_window_opening`, `WindowOpening`
- `rate`: `RunTracker`, `resolve_rate`, `keep_day_rate` (the learned heating rate)
- `planned`: `PlanQuery`, `describe_planned_heating`
- `water`: `WaterReading`
- `defaults`: the heating thresholds, which `const.py` re-imports

## Allowed dependencies

The standard library, `lib/timeutil` and `lib/tariff`.

## Not here

The immersion actuator, the switch and number entities, the dashboard and the cost split stay in
the integration. So do the `alt_heat_*` modules, which compare another heat source.
