// Lovelace dashboard strategy for GivEnergy Inverter Manager.
// Add it from Settings > Dashboards > Add dashboard > Community dashboards, or use it as the
// whole dashboard configuration:
//   strategy:
//     type: custom:givenergy-manager
// The server builds the dashboard and decides what the signed-in user may see. The message it
// receives holds its type and nothing else, so the browser cannot ask for more.
const WS_TYPE = "givenergy_inverter_manager/dashboard";
const NAME = "givenergy-manager";
const DOCS = "https://github.com/macuistin/givenergy_inverter_manager/blob/main/docs";

function describe(err) {
  if (err && err.code === "not_found") {
    return "GivEnergy Inverter Manager is not loaded. Check Settings > Devices & services.";
  }
  const reason = (err && (err.message || err.code)) || "unknown error";
  return `GivEnergy Inverter Manager could not build the dashboard: ${reason}`;
}

class GivEnergyManagerStrategy extends HTMLElement {
  static noEditor = true;

  static getCreateSuggestions(_hass) {
    return { title: "GivEnergy", icon: "mdi:solar-power-variant" };
  }

  static async generate(_config, hass) {
    try {
      return await hass.callWS({ type: WS_TYPE });
    } catch (err) {
      const help = `See the [troubleshooting page](${DOCS}/troubleshooting.md).`;
      const content = `${describe(err)}\n\n${help}`;
      return { views: [{ title: "GivEnergy", cards: [{ type: "markdown", content }] }] };
    }
  }
}

for (const name of ["ll-strategy-givenergy-manager", "ll-strategy-dashboard-givenergy-manager"]) {
  if (!customElements.get(name)) {
    customElements.define(name, class extends GivEnergyManagerStrategy {});
  }
}

// The entry that lists this strategy under Community dashboards. A second load adds nothing.
window.customStrategies = window.customStrategies || [];
if (!window.customStrategies.some((entry) => entry.type === NAME)) {
  window.customStrategies.push({
    type: NAME,
    strategyType: "dashboard",
    name: "GivEnergy",
    description: "Power flow, cost, battery and hot water for a GivEnergy inverter.",
    documentationURL: `${DOCS}/dashboard.md`,
  });
}
