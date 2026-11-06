---
description: "Shadow tariffs only re-price measured usage and can never write to the inverter, the immersion or the EV charger"
paths:
  - "custom_components/**/shadow*.py"
  - "tests/**"
---

# Shadow tariffs

Epic #569. A shadow tariff runs next to the active one to show what the same measured usage would
have cost. The active tariff stays the one the planner and every write work against.

- A shadow tariff only re-prices measured usage. It never writes to the inverter, the immersion
  switch or the EV charger.
- Name every shadow module `shadow*.py`. `tests/test_shadow_cannot_write.py` finds them by that name.
- A pure shadow module (under `core/` or `lib/`) must not reach a write module through any chain
  of imports. A shadow module on the Home Assistant side (a sensor, the options form) must not
  import a write module or name a write method (`apply_*`, `clear_*`, `async_call`).
- The write modules are `inverter/`, `lib/givtcp/`, `coordinator`, `services`,
  `immersion_actuator` and `optional_devices`. Add a new one to `WRITE_MODULES` in the test.
- Label every shadow figure as a re-pricing, and say from which date it has data.
- The number of shadow tariffs allowed is one named constant, so it can change later.
