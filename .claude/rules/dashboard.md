---
description: "The generated dashboard: registry ids, device visibility, HACS cards and golden files"
paths:
  - "custom_components/givenergy_inverter_manager/dashboard/**"
  - "custom_components/givenergy_inverter_manager/strategy.py"
  - "tests/test_dashboard*.py"
  - "tests/dashboard_*.py"
  - "docs/dashboard-example.yaml"
---

# Dashboard

- `get_dashboard_yaml` writes `givenergy_dashboard.yaml`. The builder is the `dashboard/` package.
  It builds a dict and serialises it with PyYAML (`render.py`). Never hand-indent YAML in an f-string.
- Entity ids come from the entity registry (`Registry.get` in `registry.py`), so the file holds the
  ids the install really has. A row or card is included only when its entity is registered and enabled.
- Optional devices come and go, so a stored dashboard must outlive a change. A card that needs one
  carries a visibility condition on a sentinel entity of that device (`SENTINELS` in `devices.py`).
  While the device is absent, the card points at the id the entity will get (`expected_entity_id`).
  A card that lists entities is built once per combination of devices (`Devices.variants`).
  Use `Devices.show_with` for a card and `Builder._when` for a section.
- `tests/dashboard_visibility.py` plays the frontend: it drops what the conditions hide. Use it to
  test a card in both device states, and with the device added later.
- The power flow card needs `power-flow-card-plus` and the charts use `apexcharts-card`, both from
  HACS. When the Lovelace resource list is readable and lacks one, `hacs.py` falls back to built-in
  cards. Test both.
- The power flow battery node reads the **Battery Power** sensor with `invert_state: true`. Never
  the state of charge sensor, which would feed a percentage to the card as watts.
- Sensors that reset at midnight are plotted with `statistics-graph`, not `history-graph`, which
  draws a sawtooth.
- Two golden files pin the output: `docs/dashboard-example.yaml` and
  `tests/golden_dashboard_matrix.json`. Regenerate both with `/regenerate-goldens` after a
  deliberate change, and review the YAML diff as a user would see it.
