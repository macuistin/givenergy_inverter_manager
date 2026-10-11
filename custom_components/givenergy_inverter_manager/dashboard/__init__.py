"""
dashboard - builds the Lovelace dashboard for GivEnergy Inverter Manager.

The dashboard is built as a plain dict each time a strategy dashboard opens (strategy.py).
Nothing is written to a file.

The generated dashboard has four tabs, all of the "sections" view type. Each section starts
with a heading card and holds native tile cards:
  1. Power Flow   - a Now section (charge, rate, cost, whether the battery lasts the night,
                    cheap rate), the live energy flow (power-flow-card-plus from HACS),
                    today's totals and devices
  2. Today        - energy, cost and self-sufficiency
  3. Bill         - the month so far and the bill period
  4. Battery      - charge, power, charge history and tonight's plan

The main dashboard only shows state. The switches and sliders that change settings sit in a
Settings sub-view, opened by a small button on Power Flow. Only administrators see the button
and the view. Home Assistant has no admin flag for a dashboard. The server decides from the
websocket connection's user (strategy.py) and builds the Settings view and its button for an
administrator only. It also writes the administrators' user IDs into the view's `visible` list
and the button's user condition, so a copy kept with Take control still hides them from other
users. This hides the controls. It does not stop anyone changing an entity another way.

Detail lives in sub-views, which have no tab. A tile or heading on the tab opens each one and
the sub-view's back arrow returns to it: Immersion, EV charger and Settings (from Power Flow),
Cost breakdown and Solar and forecast (from Today), Tariff (from Bill), Battery detail (from
Battery).

The EV charger, the immersion switch and the immersion temperature sensor are optional. Every
card that needs one is hidden by a visibility condition until the device exists (devices.py),
so a copy of the dashboard kept with Take control follows a device that comes or goes.

The Power Flow tab uses power-flow-card-plus from HACS when the Lovelace resources list it, and
an entities card when they do not:
  https://github.com/flixlix/power-flow-card-plus

The immersion chart is a built-in history graph, and every other view uses built-in cards too.

The package is split by what changes together:
  registry.py   finds our entities in the entity registry
  devices.py    which optional devices exist, and the conditions that hide their cards
  cards.py      colours, layout and card primitives
  hacs.py       the optional HACS card and whether it is installed
  charts.py     the immersion chart and the power flow card
  templates.py  the text of the longer markdown cards
  views.py      the tabs and sub-views, and the Builder that fills them
  render.py     builds the dict and reads the host facts
"""

from __future__ import annotations

from .hacs import async_lovelace_resource_urls
from .registry import HostFacts
from .render import async_host_facts, build_dashboard

__all__ = [
    "HostFacts",
    "async_host_facts",
    "async_lovelace_resource_urls",
    "build_dashboard",
]
