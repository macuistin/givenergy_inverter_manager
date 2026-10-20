"""keys.py: the settings keys the GivTCP adapter reads from the mapping it is given.

The mapping holds the entity ids the inverter is wired to and the serial. The names are the
integration's stored option keys, so a host can pass its stored options straight in. A test in
the integration checks that each name here matches the integration's own constant.
"""

KEY_INVERTER_SERIAL = "inverter_serial"
KEY_SOLAR_POWER = "solar_power_entity"
KEY_BATTERY_SOC = "battery_soc_entity"
KEY_BATTERY_POWER = "battery_power_entity"
KEY_GRID_POWER = "grid_power_entity"
KEY_HOUSE_LOAD = "house_load_entity"
KEY_INVERTER_TEMP_ENTITY = "inverter_temp_entity"
KEY_TARGET_SOC_ENTITY = "target_soc_entity"
KEY_ENABLE_CHARGE_TARGET = "enable_charge_target_entity"
KEY_ENABLE_CHARGE_SCHEDULE = "enable_charge_schedule_entity"
KEY_CHARGE_START_TIME_ENTITY = "charge_start_time_entity"
KEY_CHARGE_END_TIME_ENTITY = "charge_end_time_entity"
