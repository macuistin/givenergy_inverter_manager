# lib/givtcp

The values and system model for talking to a GivTCP inverter. A backend reads an inverter into
`InverterValues` and is told what to write as a `ChargePlan`. The system model tells a hybrid from
an AC-coupled, All-In-One, three-phase, Gateway or EMS system from the entity names GivTCP
publishes, and picks which inverter to manage. The battery pause window is the discharge hold
that sits beside the charge window.

## Public names

- `values`: `InverterValues`, `InverterIdentity`, `ChargePlan`, `RateDefaults`, `WriteResult`,
  `FeedState`, `FeedStatus`. Grid power is positive for import and battery power is positive for
  charging, whatever the inverter publishes.
- `system`: `SystemKind`, `classify`, `select_controller`, `identity_of`, `what_changed`,
  `entities_changed`, `InverterFacts`, `SystemIdentity`
- `pause`: `PauseWindow`, `with_note`

## Allowed dependencies

The standard library only.

## Not here yet

The GivTCP adapter (discovery, reader, verified writer, write order) moves in the next change.
