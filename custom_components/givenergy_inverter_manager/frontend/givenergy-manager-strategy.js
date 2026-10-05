// Lovelace dashboard strategy for GivEnergy Inverter Manager.
// Use it as the whole dashboard configuration:
//   strategy:
//     type: custom:givenergy-manager
const WS_TYPE = "givenergy_inverter_manager/dashboard";

class GivEnergyManagerStrategy extends HTMLElement {
  static async generate(_config, hass) {
    try {
      return await hass.callWS({ type: WS_TYPE });
    } catch (err) {
      const reason = (err && (err.message || err.code)) || "unknown error";
      return {
        views: [
          {
            title: "GivEnergy",
            cards: [
              {
                type: "markdown",
                content: `GivEnergy Inverter Manager could not build the dashboard: ${reason}`,
              },
            ],
          },
        ],
      };
    }
  }
}

for (const name of ["ll-strategy-givenergy-manager", "ll-strategy-dashboard-givenergy-manager"]) {
  if (!customElements.get(name)) {
    customElements.define(name, class extends GivEnergyManagerStrategy {});
  }
}
