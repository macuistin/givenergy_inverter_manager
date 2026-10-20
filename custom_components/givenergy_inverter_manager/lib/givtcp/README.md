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

- `get_state(entity_id)` returns an `EntityState` (`_entity.py`): an object with a `.state`
  string and an `.attributes` mapping, which carries `options` for a select and `min` and `max`
  for a number. It returns None for a missing entity. Only `GivTCPReader.feed_status` also reads
  `.last_reported`. A state without it has no report time, so a frozen feed cannot be seen, and
  every other call works. A dict of `SimpleNamespace(state=..., attributes=...)` is enough.
- `call_service(domain, service, data)` makes the Home Assistant service call. Raise
  `ServiceCallError` when it fails. Any other exception is logged with its traceback and treated
  as a failed write.
- `cfg` is a mapping with the inverter's serial and, for the charge write, the entity ids it is
  wired to, under the names in `keys.py`. The controls find their own entities from the device
  prefix, so they need only the serial in the lower case GivTCP uses in entity ids (or a wired entity that carries the prefix).
- The charge write, the reads and the controls the integration uses are on the backend itself.
  The rest of the client is on three attributes: `backend.controls`, `backend.schedules`
  (discharge schedule and extra slots) and `backend.force`. The integration's interface,
  `InverterBackend` with `InverterControls`, reaches none of the last two.
- Every `apply_*`, `start_*` and `cancel_*` call returns a `WriteStatus` (`status.py`):
  `ALREADY_SET`, `WRITTEN`, `UNCONFIRMED`, `COOLDOWN`, `REFUSED` or `FAILED`. It is truthy unless
  the write was refused or failed. Check `status.confirmed` to know the inverter holds the value,
  and `status.sent` to know a service call went out.

## How a write is made

Every write goes through `GivTCPWriter`, because a GivEnergy inverter has about a million
lifetime register writes:

1. Read the entity first. Refuse the write when it is missing, unavailable or unknown, and skip it when it
   already holds the value.
2. Skip the value last sent to that entity if that was less than five minutes ago. A different
   value is never held back by an older one, so on, off, on sends all three.
3. Call the service once, then read the state back after 2, 4 and 8 seconds. Send again only
   when none of those reads showed the value, and at most twice in all.
4. Count each accepted call and warn at 500,000. `GivTCPWriter.seed_count` restores a count the
   host kept, and `GivTCPWriter.tuning` (`WriteTuning`) sets the sends, reads and delay.

A read-back that never matches returns `UNCONFIRMED` (GivTCP can be slow to publish). The
cooldown is cut to a minute (`GIVTCP_UNCONFIRMED_COOLDOWN_S`), so the next call can try again soon and a host that writes every cycle still sends only once a minute, and a confirmation listener hears about it,
so a host can raise a repair. Writes are serialised.

Beyond the writer, the client follows these rules in every write:

- **Options come from the entity.** A select is written with the option the entity lists,
  matched without case, spaces, underscores or hyphens, so `PauseDischarge`, `Pause Discharge`
  and `Not Paused` all work. An option the entity does not offer is refused, not sent.
- **Limits come from the entity.** Reserve, rates and targets are kept inside the entity's
  published `min` and `max` by one helper, `clamp_to_entity`. A limit that is not a number is
  ignored, and a `max` of 0 is a limit. The reserve and targets never go below 4%. A rate with no
  `max` is not capped.
- **Order matters.** A charge write turns the schedule on first, so the inverter is told to
  charge before the window and target are settled, and turns the target switch on last, because
  without it the inverter ignores the target. A discharge plan is the other way round: it
  writes the target and window first and turns the schedule on last, so a half-set discharge
  never runs, and it stops at the first failed write. A pause writes its window before its mode.
- **A window never opens a gap.** A window is two writes, so the inverter briefly holds a mix of
  old and new times. Moving a window later, the end is written first, and moving it earlier, the
  start. The mix then holds the old window and the new one. A window that wraps midnight is
  compared round the clock. If either end cannot be written (the select does not list the time,
  or lists no options), nothing is sent. The one gap left is the short wait between the two
  writes, which `windows.py` explains.
- **A live discharge schedule is switched off around a slot change.** The mixed window can be
  wider than the old and the new one, and a discharge slot may be exporting. So `apply_slot` and
  `clear_slot` on a discharge slot switch a schedule that is on off first and back on once the
  slot reads back. If the slot is not confirmed the schedule stays off. If the switch cannot be
  read (`unknown` or `unavailable`) nothing is written. A slot that already holds the window is
  not touched. A device with no schedule switch is written as it is.
- **A discharge plan does not change the battery mode.** GivTCP follows the discharge slots in
  a timed mode, and which mode that is has not been checked against GivTCP. After a plan, the
  host sets the mode itself with
  `backend.schedules.apply_battery_mode(cfg, BatteryMode.TIMED_EXPORT)`, and sets it back
  afterwards. This integration's interface takes `SelfUseMode`, which has no export mode.
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
`InverterControls` only. `InverterControls.apply_battery_mode` takes `SelfUseMode`, and text that does not spell one
("Timed Export" among it) raises `ValueError` before anything is read or written. The
discharge schedule, the extra slots and the timed force are reached through
`backend.schedules` and `backend.force`, which no interface in `inverter/backend.py` has. The
rule is held at the integration's call sites: every coordinator test runs behind a wrapper
(`tests/fakes/export_guard.py`) that fails when the backend's export surface is touched. Dry
run and the frozen-feed check are the host's job: a host checks them before it calls a write.

## What has been checked

| Area | Checked against |
| --- | --- |
| Discovery, reads, the charge write and the read-back | Unit tests, the end-to-end suite over `givtcp_mock`, GivTCP's own captured results, and a single-phase hybrid install |
| Pause, mode, reserve, rates, clock | Unit tests over plain states, and the end-to-end suite over `givtcp_mock`, which rejects an option or a value the entity does not allow |
| Discharge schedule, charge slots 2 and up, force | The same two |

The entity names for the second and third rows come from other projects' public configuration
and documentation (Predbat, a force-charge script package), not from GivTCP's source. The clock
formats and the force option names are guesses that the code does not rely on: it reads the
options an entity lists. None of it has run against a real inverter, and the mock publishes
the shapes those projects describe, so passing it shows the client is consistent with them, not
with GivTCP.

## Public names

`__init__.py` exports the names a host needs and nothing else: `make_backend`, `GivTCPBackend`,
`GivTCPPorts`, `GivTCPReader`, `GivTCPWriter`, `WriteTuning`, `WriteStatus`, `GivTCPControls`,
`GivTCPSchedules`, `GivTCPForce`, `BatteryMode`, `SelfUseMode`, `BatteryPause`, `SlotKind`,
`Force`, `Window`, the value types, `EntityState`, `GetState`, `ServiceCallError` and
discovery's `discover_givtcp_inverters`. Reach anything else through its module. Those modules
are the guide to the rest and may change between releases:

- `discovery`: `device_prefix` and the helpers that name the entities of one inverter
- `sequence`: the order of a charge write
- `system`: `classify`, `select_controller`, `identity_of`, `what_changed`
- `pause`, `pause_modes`: the battery pause window and GivTCP's pause mode text
- `freshness`: `newest_report`, `frozen_age_s`
- `windows`: which end of a window to write first
- `defaults`: the write limits and `GIVTCP_FROZEN_AFTER_S`
- `keys`: the names of the settings the adapter reads

## Allowed dependencies

The standard library and `lib/timeutil`.

## Not here

`packages/givtcp_mock/` (the fake GivTCP and the system fixtures) is test support and stays
outside the integration. The `InverterBackend` interface stays in `inverter/backend.py`, because
it describes what the coordinator needs, not what GivTCP offers.
