"""
config_flow.py - registers the handlers of GivEnergy Inverter Manager.

The setup wizard (a checklist of what to set up, then only those pages, then a confirm step),
Configure (a menu of pages, saved once at the end) and reconfigure (the inverter connection)
share their page functions. The steps are in the wizard package and the page logic in
core/wizard_*.py. Nothing is stored until a confirm step.
"""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN
from .wizard.options_flow import OptionsSteps
from .wizard.reconfigure_flow import ReconfigureSteps
from .wizard.setup_flow import SetupSteps


class GivEnergyInverterManagerConfigFlow(
    ReconfigureSteps, SetupSteps, config_entries.ConfigFlow, domain=DOMAIN
):
    """Setup wizard and reconfigure of the inverter connection."""

    VERSION = 1

    def __init__(self) -> None:
        self._init_setup()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> GivEnergyOptionsFlow:
        """The options wizard. It reads the entry's options when it saves, not when it opens."""
        return GivEnergyOptionsFlow()


class GivEnergyOptionsFlow(OptionsSteps, config_entries.OptionsFlow):
    """Options wizard."""

    def __init__(self) -> None:
        self._init_options()
