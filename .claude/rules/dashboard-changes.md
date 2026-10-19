---
description: "Changing the dashboard: where views are built, how sections lay out, apexcharts limits and the checklist"
paths:
  - "custom_components/givenergy_inverter_manager/dashboard/**"
  - "tests/test_dashboard*.py"
  - "tests/dashboard_*.py"
  - "docs/dashboard.md"
---

# Changing the dashboard

Read `.claude/rules/dashboard.md` too. It holds the standing rules. This file holds what to know
before a change and the steps to finish one.

## Know before you change

- Every view is a `Builder` method in `dashboard/views.py` (`now_sections`, `today_sections`,
  `plan_sections`, `tomorrow_sections`). Card helpers are in `dashboard/cards.py`, charts in
  `dashboard/charts.py`. A section that is `None` or holds no cards is dropped.
- A view has three columns. A section is one column unless it sets `WIDE` or `WHOLE_WIDTH`. Two
  things that should sit side by side on a tablet are two sections: one section holding both
  stacks them. A phone has one column and stacks either way.
- apexcharts-card sets the x-axis from `graph_span` and `span` on every update, so `apex_config`
  cannot size or move it. A chart that shows only some hours bakes them in when the dashboard is
  built, so a stored dashboard changes as the days change and the out-of-date repair appears. Say
  so in the docs and the PR. `data_generator` and `transform` can read `hass`, the axis cannot.
- The configured forecast sensor is tomorrow's. Solcast's today sensor holds today's periods, and
  `todays_forecast_sensor` in `discovery/forecast.py` finds it. Periods are average kW and the
  Solar Power sensor is W, so a chart that overlays them divides by 1000.
- `tests/golden_dashboard_matrix.json` holds one hash per install, so its diff reads as nothing.
  Prove a layout change with a test that names the sections, then regenerate it.

## Steps

1. Search `dashboard/cards.py`, `dashboard/charts.py` and `const.py` for a helper to reuse. Add no
   config option.
2. Get an entity with `self.entity("<unique id suffix>")`, a key from `sensor_descriptions/`.
   Absent or disabled gives `None`, and the card then leaves itself out.
3. Put logic that reads forecast or other data in `core/` or `discovery/` as a pure function with
   its own test. `dashboard/` may read `hass`, `core/` may not.
4. A card that needs a HACS card checks `self.cards.installed(...)` and falls back or leaves
   itself out. A card for an optional device follows `.claude/rules/dashboard.md`.
5. Test it in `tests/test_dashboard_story.py` or the file for that view. `dashboard_dict` in
   `tests/dashboard_support.py` takes `resources`, `states` and `attributes`. Cover it present and
   left out for each thing it needs. A test that lists a view's section headings needs updating.
6. Regenerate the matrix with `/regenerate-goldens` and run it again without the variable.
7. Update `docs/dashboard.md` and add to `## Unreleased` in `CHANGELOG.md`. Under **Upgrading**
   say a stored dashboard keeps its old layout until the out-of-date repair is submitted.
8. Run lint, the unit suite and the end-to-end suite. Say in the PR what you could not see, since
   no test renders a chart.
