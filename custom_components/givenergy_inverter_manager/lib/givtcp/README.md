# lib/givtcp

Everything needed to talk to a GivTCP inverter through Home Assistant states and service calls:
finding the inverter, reading it, writing it with a read-back, and the order a charge write goes
in. A backend reads an inverter into `InverterValues` and is told what to write as a
`ChargePlan`. The system model tells a hybrid from an AC-coupled, All-In-One, three-phase,
Gateway or EMS system from the entity names GivTCP publishes, and picks which inverter to manage.

## Public names

- `adapter`: `GivTCPBackend`, `GivTCPPorts`, `make_backend`, `read_rate_defaults`
- `discovery`: `discover_givtcp_inverters`, `device_prefix`, `GivTCPInverter` and the helpers that
  name the entities of one inverter
- `reader`: `GivTCPReader`. It negates grid and battery power: GivTCP publishes grid positive for
  export and battery positive for discharging, and `InverterValues` has grid positive for import
  and battery positive for charging.
- `writer`: `GivTCPWriter`. It reads before it writes, holds a cooldown on a repeated value, reads
  back, retries a mismatch and counts register writes.
- `sequence`: the order of a charge write
- `values`: `InverterValues`, `ChargePlan`, `RateDefaults`, `WriteResult`, `FeedStatus`, `WriteRecord`
- `system`: `SystemKind`, `classify`, `select_controller`, `identity_of`, `what_changed`
- `pause`, `pause_modes`: the battery pause window and GivTCP's pause mode text
- `freshness`: `newest_report`, `frozen_age_s`, the check for a feed that stopped reporting
- `defaults`: the write limits and `GIVTCP_FROZEN_AFTER_S`
- `errors`: `ServiceCallError`
- `keys`: the names of the settings the adapter reads

## How a host uses it

The adapter holds no Home Assistant objects. The host gives it three callables: read a state,
call a service, hear the register count. An optional `verbose` callable turns on the per-step
read-back lines.

- **Settings** are a mapping with the entity ids the inverter is wired to and its serial, under
  the names in `keys.py`.
- **A failed service call** is reported by raising `ServiceCallError` from the call-service
  callable. Any other exception is logged with its traceback and treated as a failed write.
- **Logging** uses one standard `logging` logger per module.

## Allowed dependencies

The standard library and `lib/timeutil`.

## Not here

`packages/givtcp_mock/` (the fake GivTCP and the system fixtures) is test support and stay outside the integration.
The `InverterBackend` interface stays in `inverter/backend.py`, because it describes what the
coordinator needs, not what GivTCP offers.
