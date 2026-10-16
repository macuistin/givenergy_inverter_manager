"""
dashboard - builds the Lovelace dashboard for GivEnergy Inverter Manager.

The dashboard is built as a plain dict each time a strategy dashboard opens (strategy.py), and
when the update_dashboard action or the out-of-date repair writes it into a storage dashboard
the user picked (services.py). Nothing is written without that action or the repair's fix.

The generated dashboard has one tab, Home energy, of the "sections" view type at most three
columns wide. It tells the story of now: the banners while they apply, the live power flow two
columns wide, Right now (chips for the battery, the price and the cheap rate, a sentence on what
the house runs on, today so far, and the hot water and the EV charger), and More, a button for
each sub-view. The detail sits on sub-views whose back arrow returns to Home energy:
  Today          - the day in a sentence, the last 24 hours, where it came from, what it cost
  Tonight        - whether tonight charges and why, the battery, the weather, battery health
  Tomorrow       - tomorrow's solar and what the day should cost
  Bill & tariff  - the bill period and its charts, the tariff, and the bill's tables
  Hot water      - the water now, the plan, and the last 7 days
  EV charger     - the charger now, the last 7 days, and recent charges
  Settings       - every switch and number, for administrators only

The main dashboard only shows state. The switches and numbers that change settings sit in the
Settings sub-view, opened by a button in the power flow heading and one under More. Only
administrators see the buttons and the view. Home Assistant has no admin flag for a dashboard.
The server decides from the websocket connection's user (strategy.py) and builds the Settings
view and its buttons for an administrator only. It also writes the administrators' user IDs
into the view's `visible` list and the buttons' user condition, so a copy kept with Take control
still hides them from other users. This hides the controls. It does not stop anyone changing
an entity another way.

The EV charger, the immersion switch and the immersion temperature sensor are optional. Every
card that needs one is hidden by a visibility condition until the device exists (devices.py),
so a stored copy of the dashboard follows a device that comes or goes.

HACS cards are used only when the Lovelace resources list them (hacs.py): power-flow-card-plus
for the flow (an entities card otherwise), apexcharts-card for the immersion chart and
Tomorrow's solar curve, and card-mod to style the tables. Every other card is built in.

The package is split by what changes together:
  registry.py   finds our entities in the entity registry
  devices.py    which optional devices exist, and the conditions that hide their cards
  cards.py      colours, layout and card primitives
  hacs.py       the optional HACS cards and whether each is installed
  charts.py     the immersion chart, the solar forecast curve and the power flow card
  templates.py  the sentences and the text of the longer markdown cards
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
