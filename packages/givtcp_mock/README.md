# givtcp_mock

A fake GivTCP, and recorded GivTCP systems, for testing Home Assistant code that reads and
writes a GivEnergy inverter through GivTCP.

> **Never point the mock at a real Home Assistant instance.** `MockGivTCP.install()` replaces the
> `number.set_value`, `switch.turn_on`, `switch.turn_off` and `select.select_option` services of
> the instance it is installed on. Use it in tests only.

It has no runtime dependencies. `homeassistant` is imported for type checking only, so the
package imports without it.

## The mock

```python
from givtcp_mock import MockGivTCP, Readings

mock = MockGivTCP(hass, serial="ab1234g567")
mock.publish(Readings(battery_soc=55, grid_w=-600))
mock.install()
# ... run the code under test ...
assert mock.sequence() == [("number.set_value", "number.givtcp_ab1234g567_target_soc", 100)]
```

It publishes the entity states GivTCP publishes, in GivTCP's own sign convention. It registers the
four write services and records each call in order. By default it moves the written entity to the
new value, so a read-back sees what a real device would show. `docs/design/mock_givtcp.md` in the
integration repository has the full design.

`python -m givtcp_mock [serial]` prints the entity map and the write services as JSON.

## System fixtures

```python
from givtcp_mock import systems

systems.names()          # every fixture name
systems.states("ems_3_6_3")   # {entity_id: object with .state and .attributes}
systems.raw("ems_3_6_3")      # the JSON as a dict
```

Only `hybrid_gen3_two_batteries_3_6_3` was taken from real hardware. `build.py` writes the other
single-system fixtures from it and from GivTCP's datapoint reference. `from_harness.py` writes the
`harness_*` fixtures from GivTCP's own test results.

Regenerate them from the repository root:

```bash
python -m givtcp_mock.systems.build
python -m givtcp_mock.systems.from_harness /path/to/giv_tcp/tests/golden
```

Do not edit a JSON file by hand. The integration's tests compare the committed files with what
`build.py` makes.

## Tests

```bash
python -m pytest packages/givtcp_mock/tests -q
```
