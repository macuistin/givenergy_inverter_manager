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

// Home Assistant gives a strategy 5 seconds to define its element and does not try again. When
// this script arrives later than that, the page shows an error card that names the element. The
// check below finds that card and asks the dashboard panel to build again, which it does on the
// same event it receives when the connection to Home Assistant comes back.
const TIMEOUT_TEXT = /Timeout waiting for strategy element ll-strategy-(dashboard-)?givenergy-manager/i;
const NOT_READY_CODES = ["unknown_command", "not_found"];
const CHECK_AFTER_MS = [0, 1000, 3000, 6000, 12000];
const MAX_REBUILDS = 2;
const MAX_NODES = 60000;

class GivEnergyManagerStrategy extends HTMLElement {
  static noEditor = true;

  // True when the page shows Home Assistant's timeout for this strategy and `rebuild` was called.
  // The search goes through shadow roots, because the error card is drawn inside one, and stops
  // after MAX_NODES nodes so a large page costs little.
  static recoverIfTimedOut(root, rebuild) {
    const pending = [root];
    let seen = 0;
    while (pending.length && seen < MAX_NODES) {
      const node = pending.pop();
      seen += 1;
      if (!node) continue;
      if (node.nodeType === 3 && TIMEOUT_TEXT.test(node.nodeValue || "")) {
        rebuild();
        return true;
      }
      if (node.shadowRoot) pending.push(node.shadowRoot);
      for (const child of Array.from(node.childNodes || [])) pending.push(child);
    }
    return false;
  }

  static getCreateSuggestions(_hass) {
    return { title: "GivEnergy", icon: "mdi:solar-power-variant" };
  }

  // Right after Home Assistant starts, the command may not be registered yet ("unknown_command")
  // or the integration may not have finished loading ("not_found"). The dashboard asks again
  // until it is, for up to retryForMs, while Home Assistant shows its loading screen.
  static retryEveryMs = 2000;
  static retryForMs = 60000;

  static async generate(_config, hass) {
    const started = Date.now();
    for (;;) {
      try {
        return await hass.callWS({ type: WS_TYPE });
      } catch (err) {
        const notReadyYet = err && NOT_READY_CODES.includes(err.code);
        if (notReadyYet && Date.now() - started < this.retryForMs) {
          await new Promise((resolve) => setTimeout(resolve, this.retryEveryMs));
          continue;
        }
        const help = `See the [troubleshooting page](${DOCS}/troubleshooting.md).`;
        const content = `${describe(err)}\n\n${help}`;
        return { views: [{ title: "GivEnergy", cards: [{ type: "markdown", content }] }] };
      }
    }
  }
}

// The name Home Assistant 2026.5+ looks for comes first, and each define stands alone, so one
// failure cannot stop the other and is written to the console.
for (const name of ["ll-strategy-dashboard-givenergy-manager", "ll-strategy-givenergy-manager"]) {
  try {
    if (!customElements.get(name)) {
      customElements.define(name, class extends GivEnergyManagerStrategy {});
    }
  } catch (err) {
    console.error(`GivEnergy Inverter Manager: could not define ${name}`, err);
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

// A page that got this script late recovers by itself. It is skipped where there is no page.
if (typeof document !== "undefined" && typeof window.setTimeout === "function") {
  const rebuild = () =>
    window.dispatchEvent(new CustomEvent("connection-status", { detail: "connected" }));
  let rebuilds = 0;
  for (const delay of CHECK_AFTER_MS) {
    window.setTimeout(() => {
      if (rebuilds < MAX_REBUILDS && GivEnergyManagerStrategy.recoverIfTimedOut(document, rebuild)) {
        rebuilds += 1;
      }
    }, delay);
  }
}
