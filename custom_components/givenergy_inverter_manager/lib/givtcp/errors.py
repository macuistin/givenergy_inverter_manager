"""errors.py: the failure a host reports when a service call to the inverter did not go through."""


class ServiceCallError(Exception):
    """A service call was refused or failed. The writer logs it, releases the cooldown and stops.

    A host raises this from the call-service callable it hands to the writer. Any other exception
    is logged with its traceback and treated the same way.
    """
