"""
dashboard - builds the Lovelace dashboard for GivEnergy Inverter Manager.

The dashboard is built as a plain dict each time a strategy dashboard opens (strategy.py).
Nothing is written to a file.

The generated dashboard has three tabs, all of the "sections" view type, at most three
columns wide. Each section starts with a heading card and holds native cards:
  1. Now          - charge, rate, cost, whether the battery lasts the night, cheap rate and
                    the repairs; the banners; the live energy flow (power-flow-card-plus from
                    HACS) two columns wide; today so far and the devices
  2. Today        - the day hour by hour, energy, cost and solar, with the cost and forecast
                    detail lower on the tab
  3. Plan & bill  - tonight's charge, the battery and why the night is covered, the bill
                    period, the tariff and the battery's health

The sections are placed densely, so on a laptop the power flow sits beside Now. On a phone
every section is one column.

The main dashboard only shows state. The switches and numbers that change settings sit in a
Settings sub-view, opened by a small button on Now. Only administrators see the button
and the view. Home Assistant has no admin flag for a dashboard. The server decides from the
websocket connection's user (strategy.py) and builds the Settings view and its button for an
administrator only. It also writes the administrators' user IDs into the view's `visible` list
and the button's user condition, so a copy kept with Take control still hides them from other
users. This hides the controls. It does not stop anyone changing an entity another way.

The detail of a tab sits lower on the tab, so only the devices and Settings have a sub-view,
which has no tab. A tile or button on Now opens each one and the sub-view's back arrow returns
to Now: Immersion, EV charger and Settings.

The EV charger, the immersion switch and the immersion temperature sensor are optional. Every
card that needs one is hidden by a visibility condition until the device exists (devices.py),
so a copy of the dashboard kept with Take control follows a device that comes or goes.

The Now tab uses power-flow-card-plus from HACS when the Lovelace resources list it, and
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
