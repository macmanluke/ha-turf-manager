// Renders the history card in jsdom with a mock `hass` and checks filters and delete.
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
// Objects created inside jsdom have that window's prototypes; compare plain copies.
const plain = (value) => JSON.parse(JSON.stringify(value));

function makeEntries() {
  return [
    {
      id: "a1", lawn_id: "L1", lawn: "Front lawn", kind: "application", is_pgr: true,
      date: "2026-11-01", start: "2026-11-01T00:00:00+10:30", all_day: true,
      summary: "PGR: Primo Maxx 4 mL/100m²", product_name: "Primo Maxx",
    },
    {
      id: "m1", lawn_id: "L1", lawn: "Front lawn", kind: "mow",
      date: "2026-11-10", start: "2026-11-10T09:30:00+10:30", all_day: false,
      summary: "Mow 25 mm (cylinder)", clippings_l: 12, notes: "<img src=x onerror=alert(1)>",
    },
    {
      id: "f1", lawn_id: "L1", lawn: "Front lawn", kind: "application", is_pgr: false,
      date: "2026-11-12", start: "2026-11-12T08:00:00+10:30", all_day: false,
      summary: "Lawn food 2.5 kg/100m²", total_amount: 3750, total_unit: "g", area_m2: 150, n_g_m2: 5,
      weather: { temperature: { value: 22.5, unit: "°C" }, wind_speed: { value: 8, unit: "km/h" } },
    },
    {
      id: "x1", lawn_id: "L1", lawn: "Front lawn", kind: "application", is_pgr: true, product_type: "mix",
      date: "2026-11-15", start: "2026-11-15T07:00:00+10:30", all_day: false, area_m2: 100, n_g_m2: 5,
      summary: "PGR mix: Primo Maxx 4 mL/100m² + Lawn food 2.5 kg/100m²",
      products: [
        { product_name: "Primo Maxx", rate: 4, rate_unit: "mL/100m²", total_amount: 4, total_unit: "mL", is_pgr: true },
        { product_name: "Lawn food", rate: 2.5, rate_unit: "kg/100m²", total_amount: 2500, total_unit: "g" },
      ],
    },
    {
      id: "t1", lawn_id: "L1", lawn: "Front lawn", kind: "activity", activity: "top_dress",
      date: "2026-11-20", start: "2026-11-20T00:00:00+10:30", all_day: true, summary: "Top dress: 5 mm sand",
    },
  ];
}

function mockHass(store) {
  const calls = [];
  const hass = {
    locale: { language: "en-AU" },
    entities: {
      "sensor.front_log_entries": {
        entity_id: "sensor.front_log_entries", device_id: "front", platform: "turf_manager",
        translation_key: "log_entries",
      },
      "sensor.back_log_entries": {
        entity_id: "sensor.back_log_entries", device_id: "back", platform: "turf_manager",
        translation_key: "log_entries",
      },
    },
    states: {
      "sensor.front_log_entries": { state: String(store.entries.length), attributes: { last_modified: null } },
      "sensor.back_log_entries": { state: "0", attributes: { last_modified: null } },
    },
    callWS: async (message) => {
      calls.push(message);
      if (message.service === "get_history") {
        return { context: {}, response: { entries: store.entries.map((e) => ({ ...e })) } };
      }
      if (message.service === "delete_entry") {
        store.entries = store.entries.filter((e) => e.id !== message.service_data.entry_id);
        return { context: {} };
      }
      throw new Error(`unexpected ${message.service}`);
    },
  };
  return { hass, calls };
}

async function main() {
  const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only" });
  const { window } = dom;
  window.eval(SCRIPT);
  assert.ok(window.customElements.get("turf-manager-log-card"), "card element is defined");
  assert.ok(window.customCards.some((c) => c.type === "turf-manager-log-card"), "card is in the picker");
  assert.ok(window.customStrategies.some((s) => s.type === "turf-manager"), "strategy is offered");

  const store = { entries: makeEntries() };
  const { hass, calls } = mockHass(store);
  const card = window.document.createElement("turf-manager-log-card");
  window.document.body.appendChild(card);
  card.setConfig({ device_id: "front", title: "" });
  card.hass = hass;
  await tick();

  const root = card.shadowRoot;
  const rows = () => [...root.querySelectorAll("tbody tr")];
  const summaries = () => rows().map((r) => r.querySelector(".summary").textContent.trim());

  // Loads only this lawn's history, newest first.
  assert.deepEqual(plain(calls[0]), {
    type: "call_service", domain: "turf_manager", service: "get_history",
    service_data: { device_id: ["front"] }, return_response: true,
  });
  assert.deepEqual(summaries(), [
    "Top dress: 5 mm sand",
    "PGR mix: Primo Maxx 4 mL/100m² + Lawn food 2.5 kg/100m²",
    "Lawn food 2.5 kg/100m²",
    "Mow 25 mm (cylinder)",
    "PGR: Primo Maxx 4 mL/100m²",
  ]);
  // A mix lists each product's total.
  assert.equal(
    rows()[1].querySelector(".details").textContent,
    "Primo Maxx 4 mL, Lawn food 2500 g over 100 m² · N 5 g/m²",
  );
  assert.equal(root.querySelector("ha-card").hasAttribute("header"), false, "no header when title is empty");

  // Details line: totals, nutrients and weather; notes are escaped, never rendered as HTML.
  const fertRow = rows()[2];
  assert.match(fertRow.querySelector(".details").textContent, /3750 g over 150 m² · N 5 g\/m² · temperature 22.5°C, wind speed 8km\/h/);
  assert.equal(root.querySelector("img"), null, "notes are not rendered as HTML");
  assert.match(rows()[3].querySelector(".details").textContent, /12 L clippings · <img src=x onerror=alert\(1\)>/);

  // All-day entries show a date only; timed ones include the time.
  assert.doesNotMatch(rows()[0].querySelector(".when").textContent, /:/);
  assert.match(rows()[3].querySelector(".when").textContent, /\d:\d\d/);

  // Filters.
  const click = (selector) => root.querySelector(selector).click();
  click('button[data-value="pgr"]');
  assert.deepEqual(summaries(), [
    "PGR mix: Primo Maxx 4 mL/100m² + Lawn food 2.5 kg/100m²",
    "PGR: Primo Maxx 4 mL/100m²",
  ]);
  click('button[data-value="mow"]');
  assert.deepEqual(summaries(), ["Mow 25 mm (cylinder)"]);
  click('button[data-value="activity"]');
  assert.deepEqual(summaries(), ["Top dress: 5 mm sand"]);
  click('button[data-value="all"]');
  assert.equal(rows().length, 5);

  // Delete asks first; Cancel backs out without calling anything.
  click('button[data-action="ask-delete"][data-value="m1"]');
  assert.ok(root.querySelector('button[data-action="delete"][data-value="m1"]'), "confirm button shown");
  click('button[data-action="cancel"]');
  assert.equal(root.querySelector('button[data-action="delete"]'), null);
  assert.equal(calls.filter((c) => c.service === "delete_entry").length, 0);

  // Confirmed delete calls the action and reloads.
  click('button[data-action="ask-delete"][data-value="m1"]');
  click('button[data-action="delete"][data-value="m1"]');
  await tick();
  await tick();
  assert.deepEqual(plain(calls.find((c) => c.service === "delete_entry").service_data), { entry_id: "m1" });
  assert.equal(rows().length, 4);
  assert.ok(!summaries().includes("Mow 25 mm (cylinder)"));

  // A change to the lawn's Log entries sensor triggers a reload; unrelated updates don't.
  const loadsBefore = calls.filter((c) => c.service === "get_history").length;
  card.hass = { ...hass, states: { ...hass.states } };
  await tick();
  assert.equal(calls.filter((c) => c.service === "get_history").length, loadsBefore, "no reload without a change");
  store.entries.push({
    id: "n1", lawn_id: "L1", kind: "mow", date: "2026-11-25", start: "2026-11-25T07:00:00+10:30",
    all_day: false, summary: "Mow 24 mm (cylinder)",
  });
  card.hass = {
    ...hass,
    states: { ...hass.states, "sensor.front_log_entries": { state: "4", attributes: { last_modified: "x" } } },
  };
  await tick();
  assert.equal(summaries()[0], "Mow 24 mm (cylinder)");

  // Paging.
  store.entries = Array.from({ length: 20 }, (_, i) => ({
    id: `p${i}`, kind: "mow", date: `2026-10-${String(i + 1).padStart(2, "0")}`,
    start: "2026-10-01T07:00:00+10:30", all_day: true, summary: `Mow ${i}`,
  }));
  card.hass = {
    ...hass,
    states: { ...hass.states, "sensor.front_log_entries": { state: "20", attributes: { last_modified: "y" } } },
  };
  await tick();
  assert.equal(rows().length, 15);
  assert.match(root.querySelector("button.more").textContent, /Show more \(5\)/);
  click("button.more");
  assert.equal(rows().length, 20);

  console.log("history card: all checks passed");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
