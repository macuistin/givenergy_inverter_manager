# lib/givtcp

A client for [GivTCP](https://github.com/britkat1980/giv_tcp), the add-on that talks to a
GivEnergy inverter and publishes it to Home Assistant. This package finds the inverter, reads it,
and writes its settings with a read-back. It does not talk to the inverter or to MQTT itself. It
reads and writes the Home Assistant entities GivTCP creates, through two callables the host gives
it. It imports no Home Assistant code, so a test or another host can drive it with a dict.

[`docs/givtcp.md`](../../../../docs/givtcp.md) is what we know about GivTCP itself (its entities,
what each kind of system publishes, its quirks). This page is about the client.

## What it does

| Job | Where | Notes |
| --- | --- | --- |
| Find inverters and their entities | `discovery` | Works by entity suffix, so a changed `HADEVICEPREFIX` and several inverters are handled |
| Tell the system kind | `system` | Hybrid (Gen 1 to 3, HV), AC-coupled, All-In-One, three-phase, Gateway, EMS. Picks which device to manage |
| Read power, charge and counters | `reader` | Negates grid and battery power, so grid is positive for import and battery positive for charging |
| Judge whether the feed is live | `freshness`, `reader` | GivTCP never publishes `offline`, so the client works it out: silent, frozen, paused, stale, publishing |
| Write the overnight charge | `sequence` | Schedule on, window, target, then the target switch last |
| Pause, mode, reserve, rates | `controls` | `GivTCPControls` |
| Discharge (export) schedule, charge slots 2 to 10 | `schedules` | `GivTCPSchedules` |
| Timed force charge and force export | `force` | `GivTCPForce` |
| Read the inverter's clock | `controls` | `clock_skew_s` |
| Make every write safe | `writer` | `GivTCPWriter`, see below |

## Using it

```python
from custom_components.givenergy_inverter_manager.lib.givtcp import (
    GivTCPPorts, make_backend, BatteryPause,
)

ports = GivTCPPorts(
    get_state=lambda entity_id: states.get(entity_id),   # an object with .state, or None
    call_service=call_service,                            # async (domain, service, data) -> None
    on_count_change=lambda count: None,                   # hears the register write count
)
backend = make_backend({"inverter_serial": "ab1234g567"}, ports)

values = backend.read(cfg)                       # InverterValues, in our sign convention
await backend.apply_battery_pause(cfg, BatteryPause.DISCHARGE, time(23, 30), time(5, 30))
```

- `get_state(entity_id)` returns an object with a `.state` string and, for a select or number, an
  `.attributes` mapping with `options` or `min` and `max`. It returns None for a missing entity.
- `call_service(domain, service, data)` makes the Home Assistant service call. Raise
  `ServiceCallError` when it fails. Any other exception is logged with its traceback and treated
  as a failed write.
- `cfg` is a mapping with the inverter's serial and, for the charge write, the entity ids it is
  wired to, under the names in `keys.py`. The controls find their own entities from the device
  prefix, so they need only the serial in the lower case GivTCP uses in entity ids (or a wired entity that carries the prefix).
- Every `apply_*` and `start_*` call returns True when the value is on the inverter or was sent,
  and False when it was refused or a write failed.

## How a write is made

Every write goes through `GivTCPWriter`, because a GivEnergy inverter has about a million
lifetime register writes:

1. Read the entity first and skip the write when it is already at the value.
2. Skip the same value written in the last five minutes.
3. Call the service, read the state back, and try again up to three times, two seconds apart.
4. Count each accepted call and warn at 500,000.

A read-back that never matches still returns True (GivTCP can be slow to publish), but is
reported to a confirmation listener, so a host can raise a repair. Writes are serialised.

Beyond the writer, the client follows these rules in every write:

- **Options come from the entity.** A select is written with the option the entity lists,
  matched without case, spaces, underscores or hyphens, so `PauseDischarge`, `Pause Discharge`
  and `Not Paused` all work. An option the entity does not offer is refused, not sent.
- **Limits come from the entity.** Reserve, rates and targets are kept inside the entity's
  published `min` and `max`. The reserve and targets never go below 4%.
- **Order matters.** A charge write enables the target last. A pause writes its window before its
  mode. A discharge plan writes its target and window before it switches the schedule on, and
  stops at the first failed write, so a half-set schedule is never switched on.
- **Never longer than asked.** A force that no preset or minutes entity can hold at that length
  is refused.

## What each class offers

`GivTCPControls` (`controls.py`): `apply_battery_pause(pause, start, end)`, `apply_battery_mode`,
`apply_reserve`, `apply_charge_rate`, `apply_discharge_rate`. Reads: `read_battery_mode`,
`read_reserve`, `read_charge_rate`, `read_discharge_rate`, `read_inverter_clock`, `clock_skew_s`.
`BatteryPause` is `OFF`, `CHARGE`, `DISCHARGE` or `BOTH`. Ending a pause writes the mode only.

`GivTCPSchedules` (`schedules.py`): `apply_discharge_plan(window, target, slot)`,
`stop_discharge`, `set_discharge_schedule`, `apply_discharge_target`, `apply_slot(kind, slot,
window)`, `clear_slot`. Reads: `read_slot`, `read_discharge_target`,
`discharge_schedule_enabled` (None when GivTCP does not publish the switch, never a guess of off).
`SlotKind` is `CHARGE` or `DISCHARGE`. Slots run from 1 to 10.

`GivTCPForce` (`force.py`): `start(force, minutes)` and `cancel(force)` for `Force.CHARGE` and
`Force.EXPORT`. GivTCP puts the old schedule, rates and target back when a force ends.

## No policy in the client

The client writes what it is asked to. Whether to export is the host's decision. This
integration never exports, so its coordinator is typed against `InverterBackend` and
`InverterControls` only, and `InverterExport` (the discharge schedule and force) is a separate
interface in `inverter/backend.py` that nothing in the integration calls. Dry run and the
frozen-feed check are also the host's job: a host checks them before it calls a write.

## What has been checked

| Area | Checked against |
| --- | --- |
| Discovery, reads, the charge write and the read-back | Unit tests, the end-to-end suite over `givtcp_mock`, GivTCP's own captured results, and a single-phase hybrid install |
| Pause, mode, reserve, rates, clock | Unit tests over plain states only |
| Discharge schedule, charge slots 2 and up, force | Unit tests over plain states only |

The entity names for the second and third rows come from other projects' public configuration
and documentation (Predbat, a force-charge script package), not from GivTCP's source. The clock
formats and the force option names are guesses that the code does not rely on: it reads the
options an entity lists. None of it has run against a real inverter. `packages/givtcp_mock/`
does not publish these entities yet.

## Public names

- `adapter`: `GivTCPBackend`, `GivTCPPorts`, `make_backend`, `read_rate_defaults`
- `discovery`: `discover_givtcp_inverters`, `device_prefix`, `GivTCPInverter` and the helpers that
  name the entities of one inverter
- `reader`: `GivTCPReader`
- `writer`: `GivTCPWriter`, `SwitchState`, `VerifiedWrite`
- `sequence`: the order of a charge write
- `controls`, `schedules`, `force`: see above
- `values`: `InverterValues`, `ChargePlan`, `RateDefaults`, `WriteResult`, `FeedStatus`,
  `WriteRecord`
- `system`: `SystemKind`, `classify`, `select_controller`, `identity_of`, `what_changed`
- `pause`, `pause_modes`: the battery pause window and GivTCP's pause mode text
- `freshness`: `newest_report`, `frozen_age_s`
- `defaults`: the write limits and `GIVTCP_FROZEN_AFTER_S`
- `errors`: `ServiceCallError`
- `keys`: the names of the settings the adapter reads

## Allowed dependencies

The standard library and `lib/timeutil`.

## Not here

`packages/givtcp_mock/` (the fake GivTCP and the system fixtures) is test support and stays
outside the integration. The `InverterBackend` interface stays in `inverter/backend.py`, because
it describes what the coordinator needs, not what GivTCP offers.
