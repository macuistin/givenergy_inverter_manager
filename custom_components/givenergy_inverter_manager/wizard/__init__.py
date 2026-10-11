"""
wizard - the setup and options wizards of GivEnergy Inverter Manager.

The page logic that needs no Home Assistant is in core/wizard_*.py. This package holds what
does: the form schemas and selectors (schemas.py, selectors.py), the detection of what the
system already has (detect.py), and the flow steps (flow_base.py, setup_flow.py,
options_flow.py, reconfigure_flow.py). config_flow.py only registers the handlers.
"""
