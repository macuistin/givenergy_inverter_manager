"""inverter: the inverter backend interface and its adapters.

The coordinator talks to an InverterBackend (see backend.py). Everything that knows how a
particular inverter integration names its entities or orders its writes lives in a package
below this one. GivTCP is the only adapter today.
"""
