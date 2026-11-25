// Renders the mix card in jsdom and checks remove, clear and updates.
// Run: npm test (in tests/js), after npm install.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const SCRIPT = fs.readFileSync(
  path.join(__dirname, "../../custom_components/turf_manager/frontend/turf-manager.js"),
  "utf8",
);
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const plain = (value) => JSON.parse(JSON.stringify(value));

async function main() {
  const { window } = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only" });
  window.eval(SCRIPT);
  assert.ok(window.customElements.get("turf-manager-mix-card"));
  assert.ok(window.customCards.some((c) => c.type === "turf-manager-mix-card"));

  const calls = [];
  const mixState = (products) => ({
    entity_id: "sensor.front_application_mix",
    state: String(products.length),
    attributes: { products },
  });
  const hass = {
    states: {
      "sensor.front_application_mix": mixState([
        { product_id: "p1", product: "Lawn food", rate: 2.5, unit: "kg/100m²" },
        { product_id: "p2", product: "Wetting <b>agent</b>", rate: 20, unit: "mL/100m²" },
      ]),
    },
    callWS: async (message) => {
      calls.push(message);
      return { context: {} };
    },
  };

  const card = window.document.createElement("turf-manager-mix-card");
  window.document.body.appendChild(card);
  assert.throws(() => card.setConfig({}), /entity/);
  card.setConfig({ entity: "sensor.front_application_mix", device_id: "front" });
  card.hass = hass;
  await tick();

  const root = card.shadowRoot;
  const items = () => [...root.querySelectorAll("li")].map((li) => li.textContent.replace(/\s+/g, " ").trim());
  assert.deepEqual(items(), ["Lawn food2.5 kg/100m²", "Wetting <b>agent</b>20 mL/100m²"]);
  assert.equal(root.querySelector("b"), null, "product names are escaped");
  assert.match(root.querySelector(".title").textContent, /In this mix · 2 products/);

  // Remove one product.
  root.querySelector('button[data-action="remove"][data-value="p2"]').click();
  await tick();
  assert.deepEqual(plain(calls[0]), {
    type: "call_service", domain: "turf_manager", service: "mix_remove",
    service_data: { device_id: ["front"], product: "p2" },
  });

  // The card follows the sensor.
  card.hass = { ...hass, states: { "sensor.front_application_mix": mixState([
    { product_id: "p1", product: "Lawn food", rate: 2.5, unit: "kg/100m²" },
  ]) } };
  assert.deepEqual(items(), ["Lawn food2.5 kg/100m²"]);
  assert.match(root.querySelector(".title").textContent, /1 product$/);

  // Clear.
  root.querySelector('button[data-action="clear"]').click();
  await tick();
  assert.deepEqual(plain(calls[1]), {
    type: "call_service", domain: "turf_manager", service: "mix_clear",
    service_data: { device_id: ["front"] },
  });

  // Errors from the action are shown.
  card.hass = { ...card._hass, callWS: async () => { throw new Error("Lawn food isn't in the mix"); } };
  root.querySelector('button[data-action="clear"]').click();
  await tick();
  assert.match(root.querySelector(".error").textContent, /isn't in the mix/);

  console.log("mix card: all checks passed");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
