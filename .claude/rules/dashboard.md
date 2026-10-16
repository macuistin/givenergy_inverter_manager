---
description: "The generated dashboard: registry ids, device visibility, HACS cards and golden files"
paths:
  - "custom_components/givenergy_inverter_manager/dashboard/**"
  - "custom_components/givenergy_inverter_manager/strategy.py"
  - "custom_components/givenergy_inverter_manager/stored_dashboard_repair.py"
  - "custom_components/givenergy_inverter_manager/core/stored_dashboard.py"
  - "tests/test_dashboard*.py"
  - "tests/dashboard_*.py"
---

# Dashboard

- The primary route is a stored dashboard. The user makes a blank storage dashboard and runs
  `update_dashboard`, which writes the admin build of the `dashboard/` package into it with
  `LovelaceStorage.async_save`, backs up the old config and remembers the URL path
  (`stored_dashboard_url_path`). The repair `dashboard_out_of_date` (`stored_dashboard_repair.py`,
  decision in `core/stored_dashboard.py`) offers the same write when they differ. Nothing is
  written without the action or the fix. The integration never creates a dashboard (see
  `docs/design/spikes/SP1.md`). The strategy (`strategy.py`,
  `frontend/givenergy-manager-strategy.js`) is the secondary route: it builds the same dashboard
  each time it opens and can time out on some devices. A notification at first setup says both.
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
- Every card works with core cards alone. HACS cards are used only when the Lovelace resource list
  names them, also when the list cannot be read (`hacs.py`): `power-flow-card-plus` (else an
  entities card), `apexcharts-card` (the immersion chart and Tomorrow's curve) and `card-mod`
  (styles the markdown tables through `ha-markdown $`, and chart titles). Test with and without
  each. Never add a custom card that is on by default.
- The power flow battery node reads the **Battery Power** sensor with `invert_state: true`. Never
  the state of charge sensor, which would feed a percentage to the card as watts.
- Sensors that reset at midnight are plotted with `statistics-graph`, not `history-graph`, which
  draws a sawtooth.
- One tab, Home energy (path `power-flow`), tells the story of now: banners, the power flow,
  Right now (chips and a sentence) and More (a shortcut card per sub-view). Detail lives on
  sub-views with `back_path` `power-flow`: Today, Tonight (`plan`), Tomorrow, Bill & tariff,
  Hot water, EV charger and Settings. A sub-view never links to another sub-view.
- Each section leads with a sentence (a markdown template in `templates.py`), then small figures
  as heading chips or a glance row. Tiles are for controls in Settings. Every view has
  `max_columns: 3` and `dense_section_placement`. `WIDE` is two columns, `WHOLE_WIDTH` a banner.
- A chart series carries a colour (`SOLAR_HEX` and the rest in `cards.py`) only when
  `HostFacts.series_colours` is true, from Home Assistant 2026.6 (`render.py`).
- Numbers are set with the `STEPPER` feature (− and + buttons), never a slider.
- The banners (dry run, charge target conflict, setup, this integration's repairs) open Home
  energy in that order, each a section with a condition on its sensor. At the 2026.5 floor use
  only `state`, `numeric_state`, `user` and `or` conditions.
- `tests/golden_dashboard_matrix.json` pins the output for a grid of installs and for an
  administrator and another user. Regenerate it with `/regenerate-goldens` after a deliberate
  change, and compare the dashboards before and after, section by section.
