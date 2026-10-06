"""
dashboard - builds the Lovelace dashboard for GivEnergy Inverter Manager.

The dashboard is built as a plain dict, then serialised with PyYAML. The
get_dashboard_yaml service writes the YAML to a file.

The generated dashboard has four tabs, all of the "sections" view type. Each section starts
with a heading card and holds native tile cards:
  1. Power Flow   - a Now section (charge, night survival, rate, cost, cheap rate), the live
                    energy flow (power-flow-card-plus from HACS), today's totals and devices
  2. Today        - energy, cost and self-sufficiency
  3. Bill         - the month so far and the bill period
  4. Battery      - charge, power, charge history and tonight's plan

The main dashboard only shows state. The switches and sliders that change settings sit in a
Settings sub-view, opened by a small button on Power Flow. Only administrators see the button
and the view. Home Assistant has no admin flag for a dashboard, so the generator is given the
administrators' user IDs and writes them into the view's `visible` list and the button's
user condition. With no ID, the Settings view and its button are left out. This hides the
controls. It does not stop anyone changing an entity another way.

Detail lives in sub-views, which have no tab. A tile or heading on the tab opens each one and
the sub-view's back arrow returns to it: Immersion, EV charger and Settings (from Power Flow),
Cost breakdown and Solar and forecast (from Today), Tariff (from Bill), Battery detail (from
Battery).

Power flow view requires power-flow-card-plus from HACS:
  https://github.com/flixlix/power-flow-card-plus

The immersion charts need apexcharts-card from HACS:
  https://github.com/RomRider/apexcharts-card

All other views use only built-in HA Lovelace cards.

The package is split by what changes together:
  registry.py   finds our entities in the entity registry
  cards.py      colours, layout and card primitives
  hacs.py       the optional HACS cards and their fallbacks
  charts.py     the immersion charts and the power flow card
  templates.py  the text of the longer markdown cards
  views.py      the tabs and sub-views, and the Builder that fills them
  render.py     turns the views into the YAML file text or a dict
"""

from __future__ import annotations

from .hacs import async_lovelace_resource_urls
from .registry import HostFacts
from .render import async_host_facts, build_dashboard, render_dashboard

__all__ = [
    "HostFacts",
    "async_host_facts",
    "async_lovelace_resource_urls",
    "build_dashboard",
    "render_dashboard",
]
