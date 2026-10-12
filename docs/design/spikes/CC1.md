# CC1: can the integration read whether SmartTarget is on?

## Question

Does GivTCP publish an entity that says whether SmartTarget (or PALM, the plant and load manager) is on, so a warning about a second controller could name it exactly?

## Method

- Read the datapoint list GivTCP 3.6 publishes (release of 11 October 2026).
- Search the entities of a running GivTCP 3.6.3 install in Home Assistant for `smart`, `smart_target` and `palm`, in every domain.
- GivTCP's REST interface was not called. It would need an address setting, which this integration does not have.

## Result: no entity

GivTCP has no SmartTarget or PALM entity. `Smart_Target` is a setting in GivTCP's own configuration, default off, and it is not published as a sensor, switch or select. On the running install the searches find no entity whose id or name contains `smart_target` or `palm` under GivTCP. The `smart` matches are unrelated devices.

## Decision

The warning works from behaviour, not from a setting. The integration counts changes to the charge target that it did not send and that no Home Assistant user made, and says "something else", never "SmartTarget is on". This is the rule in `core/controller_conflict.py`: at least 2 such changes in 3 days.

If a later GivTCP release publishes an entity, the sensor can read it and the banner can say so exactly. Nothing else needs to change.

## Known false positives

- A change made in the GivEnergy app reaches GivTCP with no Home Assistant user, so it counts.
- An energy management system that reasserts settings itself looks the same.
- GivTCP 3.6.0 beta 1 fixed a bug where the Smart Target setting was ignored and followed the Dynamic Tariff setting instead. Older versions may behave oddly.
