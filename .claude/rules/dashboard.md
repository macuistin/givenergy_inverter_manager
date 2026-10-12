---
description: "The generated dashboard: registry ids, device visibility, HACS cards and golden files"
paths:
  - "custom_components/givenergy_inverter_manager/dashboard/**"
  - "custom_components/givenergy_inverter_manager/strategy.py"
  - "tests/test_dashboard*.py"
  - "tests/dashboard_*.py"
---

# Dashboard

- The dashboard is a strategy (`strategy.py`, `frontend/givenergy-manager-strategy.js`). The
  websocket command builds it with the `dashboard/` package each time the dashboard opens, and
  nothing is written to a file. The integration does not create the dashboard (no route open to
  an integration does it cleanly, see `docs/design/spikes/SP1.md`). A notification at first
  setup tells the user to add it from Community dashboards.
- The server decides who sees Settings: `ws_dashboard` reads `connection.user.is_admin` and the
  message carries no other field. The Settings view still carries a `visible` list of the
  administrators, so a copy made with Take control hides it from other users.
- Entity ids come from the entity registry (`Registry.get` in `registry.py`), so the dashboard holds
  the ids the install really has. A row or card is included only when its entity is registered and enabled.
- Optional devices come and go, so a stored dashboard must outlive a change. A card that needs one
  carries a visibility condition on a sentinel entity of that device (`SENTINELS` in `devices.py`).
  While the device is absent, the card points at the id the entity will get (`expected_entity_id`).
  A card that lists entities is built once per combination of devices (`Devices.variants`).
  Use `Devices.show_with` for a card and `Builder._when` for a section.
- `tests/dashboard_visibility.py` plays the frontend: it drops what the conditions hide. Use it to
  test a card in both device states, and with the device added later.
- Every card is a core card except the power flow card. It uses `power-flow-card-plus` from HACS
  only when the Lovelace resource list names it, and an entities card otherwise, also when the
  list cannot be read (`hacs.py`). Test both. Never add a custom card that is on by default.
- The power flow battery node reads the **Battery Power** sensor with `invert_state: true`. Never
  the state of charge sensor, which would feed a percentage to the card as watts.
- Sensors that reset at midnight are plotted with `statistics-graph`, not `history-graph`, which
  draws a sawtooth.
- The banners (dry run, charge target conflict) sit together under Now, in that order, each a
  section with a plain `state` condition on its sensor. At the 2026.5 floor use only `state` and
  `numeric_state` conditions, because the wider set of condition types needs 2026.10.
- `tests/golden_dashboard_matrix.json` pins the output for a grid of installs and for an
  administrator and another user. Regenerate it with `/regenerate-goldens` after a deliberate
  change, and compare the dashboards before and after, section by section.
