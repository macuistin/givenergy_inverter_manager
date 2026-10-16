# Building an immersion controller from a smart switch and two temperature sensors

This describes one way to build a controllable, temperature-aware immersion heater setup from
off-the-shelf smart home hardware, with no immersion-specific controller product. Everything on
this page works with Home Assistant alone, whether or not you run this integration. If you do, the
result is what [Configuration](configuration.md#screen-hot-water) asks for: an immersion switch
entity and a water temperature sensor entity.

> **Warning: use this guide at your own risk.** It describes one way of building a setup. It
> involves mains electricity, a heavy electrical load and hot water. The authors take no
> responsibility for any injury, damage or loss that results from following it. It is not
> professional advice, and it does not replace the instructions that come with your equipment or
> the rules that apply where you live.

## What it takes

- **A Wi-Fi switch rated for an immersion heater's load.** An element typically draws 3 kW, well
  above what a general-purpose smart plug is rated for. The switch is wired in place of the
  existing isolator or timer. It is not plugged in (see [Fitting the switch](#fitting-the-switch)).
  Once added, it gives Home Assistant a `switch` entity, which is the immersion switch the setup
  wizard looks for.
- **A temperature sensor with two probes, one near the top of the cylinder and one near the
  bottom.** The probes sit in the cylinder's sensor pockets, not in the water. Each publishes its
  own `sensor` entity in Home Assistant.

## Switches

Choose a switch rated above your element's draw. Two that were used for this build:

| Switch | Rating |
|---|---|
| HBN WiFi Smart Wall Timer Switch | 16 A, 3680 W |
| Nastopee Smart Immersion Heater Timer | 40 A, 8000 W |

These are examples, not recommendations. Any switch with a suitable rating and a way to control it
from Home Assistant will do.

If you are replacing an existing switch, check the depth of the back box before you buy. A new
switch may need a deeper box. Spacers are sold to make up the difference.

Both examples are sold as timers, so each has a schedule of its own. Switch that schedule off once
the switch is in Home Assistant. A schedule left on, or an automation of your own that also
switches the heater, fights the integration.

### Keep an auto-off on the switch as a safety net

Turn the switch's schedule off, but consider keeping its auto-off on. Some apps call it inching. A
setting of one hour works well. The heater then switches itself off an hour after any turn-on,
whether you pressed the button, used the app or Home Assistant sent the command.

This removes the commonest headache with an immersion: leaving it on by mistake. If Home Assistant
stops working, or something leaves the heater on, the element runs for an hour at most.

The price is that no single run lasts longer than an hour. When the heater cuts itself off inside a
heating window with the water still below the target, the integration waits out its 10 minute
switch hold and turns the heater on again. A long heat goes in hour-long runs with short gaps. A
manual turn-on outside a heating window stops after an hour too. See
[Concepts](concepts.md#immersion-divert).

## Fitting the switch

Fitting one of these switches is close to wiring a plug: the supply goes in, the heater comes out,
and the earth is connected. Follow the wiring diagram that comes with the switch.

It is still mains wiring on a heavy load. Only do it if you are confident with electrical work and
it is your own home. Otherwise use a professional. Check what your local rules require, because in
some places this work must be done or certified by a registered electrician.

If you do it yourself:

- Switch the supply off at the consumer unit and check that it is dead before you open anything.
- Tighten every terminal fully. A loose connection on a 3 kW load gets hot.
- Use cable rated for the heater's current.

## Parts for the temperature sensing

Any equivalent parts will do.

| Qty | Part | Job |
|---|---|---|
| 1 | A Wi-Fi sensor board with probe inputs, for example a Shelly Plus Uni | Reads the probes and sends the temperatures to Home Assistant over Wi-Fi |
| 2 | Waterproof DS18B20 temperature probes, for example the Shelly temperature sensor | One for the top pocket, one for the bottom |
| 1 | A USB charger | Powers the board |
| 1 | A USB cable, stripped | Carries the charger's power to the board's supply terminals |

The temperature side is low voltage, so the board runs from a USB charger and nothing in this part
of the build touches the immersion's supply. Strip the cable back to its power wires and connect
them to the board's DC supply terminals, positive to positive and negative to negative. Check the
polarity of the wires with a meter first, because cable colours vary. Check the board's supply
voltage range against the charger's output before you power it up. The immersion switch is the
only part wired into the heater's supply (see [Fitting the switch](#fitting-the-switch)).

## Fitting the probes

A probe reads the water's temperature only if it is in good thermal contact with the cylinder and
shielded from the air around it. A loose probe in a draughty pocket reads somewhere between the
water and the room. The readings look plausible, which makes the fault hard to spot.

1. **Use a dry sensor pocket.** Cylinders usually have a blind pocket or sleeve for a thermostat or
   sensor at each height. The probe goes into the pocket, not into the water. Do not open any
   fitting that has water behind it unless the cylinder is drained. Ask a plumber if you are not
   sure which kind of port you have.
2. **Push the probe in to the end of the pocket.** The sensing tip is at the end of the probe. It
   needs to touch the closed end of the pocket.
3. **Fill the gap with heat-transfer paste.** A small smear of thermal paste on the probe removes
   the air gap between the probe and the pocket wall. Air insulates, and is the commonest cause of
   a slow or low reading.
4. **Plug the mouth of the pocket.** Pack a bit of foam, pipe lagging or mineral wool into the
   opening around the cable. This stops room air flowing past the probe.
5. **Secure the cable.** Clip or tie it so a tug cannot pull the probe out, and leave a little
   slack. Keep it away from the heater's mains wiring and the element's terminals.
6. **Put the top probe high and the bottom probe low,** so the two readings cover the full height of
   the tank.

### Check the reading

1. With the water cold or tepid, the top probe should read close to the water temperature, not the
   room temperature.
2. During a heat, the top reading should climb steadily. If it barely moves while the cylinder is
   clearly hot to the touch, the probe is not in contact with the pocket.
3. Run a hot tap until it stops getting hotter, measure the water with a cooking thermometer and
   compare it with the top probe. The tap water reads a little under the top of the cylinder, but
   the two should be close.

The bottom probe often reads the mains temperature, which is normal. See
[Why two probes](#why-two-probes).

## Why two probes

A single mid-tank sensor reads an average that can look fine while the top of the tank, the part
drawn from the hot tap, has already cooled. Two probes show two things separately:

- **The top probe** is the closest proxy for what comes out of the tap. Point the integration's
  water temperature sensor at it (**Hot water temperature sensor**,
  `immersion_temp_sensor_entity`). The minimum and target temperature rules exist to keep what you
  draw at the right temperature.
- **The bottom probe** shows how far the heat has reached down the tank. A cold bottom with a hot
  top means a short top-up would not show as heated at the bottom. That is useful context while
  watching a heating cycle, though the integration's rules do not act on it.

**Why the bottom probe often reads the mains temperature.** This is expected, not a mounting
problem. Hot water is less dense than cold, so inside a cylinder it floats rather than mixing. Cold
water entering at the bottom stays in its own layer, and the boundary between the cold layer and the
hot water above it can stay sharp for a long time. This is called thermal stratification, and a hot
water cylinder relies on it: it lets you draw hot water from the top while cold enters at the
bottom. A bottom probe reading close to mains temperature shows the cold layer still reaches up to
where the probe sits.

Both probes are plain Home Assistant `sensor` entities, so either can be charted, alerted on or
used in an automation of your own.

## Setting up the sensor board and connecting it to Home Assistant

These steps are for a Shelly Plus Uni. Other boards differ, and the app screens change between
firmware versions, so treat them as a guide. The Uni needs one extra step compared with most Shelly
devices: it does not pick the probes up on its own. You set the Uni up first, then add each probe
to it as a peripheral.

1. **Power the board and connect both probes** as described in
   [Parts for the temperature sensing](#parts-for-the-temperature-sensing), with the probes already
   fitted in the cylinder.
2. **Add the board to its app.** Follow the app's add-device steps and join your home Wi-Fi. Give
   it a name that says what it is, for example "Hot water cylinder".
3. **Open the device's Peripherals page.** It lists the peripherals the board knows about, with an
   **Add peripheral** button under them.
4. **Add one temperature peripheral for each probe.** Give each a name that says where it sits, for
   example one for the top of the cylinder and one for the lower part. Choose °C for the
   temperature units.
5. **Check the readings.** Each probe now shows as its own tile with a live temperature. On a hot
   cylinder the two tiles should be far apart. The top probe reads close to the target and the
   bottom probe close to the incoming mains temperature, the stratified tank described in
   [Why two probes](#why-two-probes).
6. **Tell the probes apart.** If you cannot tell from the names which tile is the top probe, warm
   one probe in your hand or in a cup of warm water and see which tile rises. Do this before the
   probes are fitted, because pulling a fitted probe out disturbs its paste and plug (see
   [Fitting the probes](#fitting-the-probes)).
7. **Add it to Home Assistant.** Home Assistant's Shelly integration talks to the device over your
   home network. A new Shelly on the same network normally appears under
   **Settings → Devices & Services**, ready to add. If it does not, choose **Add Integration** and
   pick **Shelly**. Check that each probe appears as its own temperature sensor.
8. **Rename the sensors in Home Assistant** to something like "Hot water top" and "Hot water
   bottom", so the setup wizard's sensor list is easy to read.

### The immersion switch

Set the switch up with its manufacturer's app, and give it a name that says it is the immersion.
Many Wi-Fi switches use the Tuya platform through the Smart Life or Tuya Smart app, and Home
Assistant's Tuya integration can usually connect with the same account, which brings the switch in
as a `switch` entity. Check your own switch's instructions, because another make will have its own
route. What matters is that you end up with a `switch` entity that turns the heater on and off.

A switch that reaches Home Assistant through the manufacturer's cloud stops responding to Home
Assistant if your internet connection drops. That is acceptable for two reasons. Both examples
above have a button on the unit and an indicator light, so you can always turn the heater on or off
by hand and see whether it is on. And the auto-off runs on the switch itself, so a heater left on
still turns off (see [Keep an auto-off on the switch as a safety net](#keep-an-auto-off-on-the-switch-as-a-safety-net)).
If cloud control would be a problem for you, choose a switch that Home Assistant can control over
your own network.

Test the switch from Home Assistant before you point the integration at it. Leave
[dry run](configuration.md#dry-run) on until you have seen it switch correctly.

## Wiring it in to this integration

1. Add the switch's `switch` entity as **Immersion switch** and the top probe's `sensor` entity as
   **Hot water temperature sensor**, either in the setup wizard's Hot water screen or later in
   **Configure**. See [Configuration](configuration.md#screen-hot-water).
2. Set **Immersion element power** to the element's rated wattage. It is used to estimate how long a
   heat to the target will take.
3. The bottom probe is not entered anywhere in the integration. Keep it as a separate sensor in
   Home Assistant, for your own charts or automations.

From here on, surplus diversion, the minimum and target temperature rules and scheduled heating in
the cheap window all follow the one temperature sensor entity, the same way they would for any
other `sensor`. See [Concepts](concepts.md#immersion-divert).
