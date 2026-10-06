# Uninstall

## Remove the integration

1. Open **Settings → Devices & Services → GivEnergy Inverter Manager**.
2. Open the three-dot menu and choose **Delete**.
3. Remove the files. In HACS, open the integration and choose **Remove**. For a manual install, delete `config/custom_components/givenergy_inverter_manager/`.
4. Restart Home Assistant.

Deleting the entry removes the integration's entities and unregisters its six actions.

## Check your inverter

The integration may have changed these GivTCP entities, and removing it does not undo the changes:

- enable charge schedule, set to on;
- charge start time and end time, slot 1;
- target SoC;
- enable charge target;
- charge start time and end time of any other slot, if you used the repair **Other charge slots are active**. They were set to 00:00.

They keep the last values written. Open them in **Developer Tools → States** and set them the way you want before you rely on your own schedule. The immersion switch and the EV charger mode also stay in whatever state they were last left.

## Files that stay behind

Deleting the integration does not remove these. Delete them yourself if you want a clean start.

| What | Where |
|---|---|
| Generated dashboard file | `givenergy_dashboard.yaml` in the config folder |
| Energy export | `givenergy_energy_export.csv` in the config folder, if you ran `export_energy_data` |
| Accumulated energy and battery statistics | `.storage/givenergy_inverter_manager.energy` in the config folder |
| The dashboard you built from the file | **Settings → Dashboards** |
| The `lovelace:` block for YAML mode | `configuration.yaml`, if you added it |
| Automations and cards that use the entities | Your own automations and dashboards |

Home Assistant keeps the long-term statistics of removed entities in its database. Clear them in **Developer Tools → Statistics** if you want them gone.

Keep `.storage/givenergy_inverter_manager.energy` if you may add the integration again. It is read when the integration starts, so your totals, yesterday figures, monthly snapshots and battery cycle count come back.
