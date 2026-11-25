// Checks the dashboard strategy against a mock `hass` object.
// Run: node tests/js/test_dashboard.cjs
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

const { generateDashboard } = require(
  path.join(__dirname, "../../custom_components/turf_manager/frontend/turf-manager.js"),
);

function mockHass({ lawns = ["front", "back"] } = {}) {
  const entities = {};
  const states = {};
  const add = (entityId, deviceId, key, { enabled = true, attributes = {} } = {}) => {
    entities[entityId] = { entity_id: entityId, device_id: deviceId, platform: "turf_manager", translation_key: key };
    if (enabled) states[entityId] = { entity_id: entityId, state: "1", attributes };
  };

  states["weather.home"] = { entity_id: "weather.home", state: "sunny", attributes: {} };

  for (const device of lawns) {
    const id = (domain, key) => `${domain}.lawn_${device}_${key}`;
    for (const key of ["gdd_since_pgr", "pgr_progress", "gdd_today", "pgr_next_due", "last_mowed",
      "last_cut_height", "last_application", "nitrogen_season", "last_scarify", "last_core",
      "last_top_dress", "log_entries", "application_mix"]) {
      add(id("sensor", key), device, key);
    }
    add(id("sensor", "gdd_since_pgr_mean"), device, "gdd_since_pgr_mean");
    add(id("sensor", "gdd_since_pgr_minmax"), device, "gdd_since_pgr_minmax");
    if (device === "front") {
      add(id("sensor", "gdd_since_pgr_fallback"), device, "gdd_since_pgr_fallback");
      add(id("sensor", "gdd_since_pgr_fallback_minmax"), device, "gdd_since_pgr_fallback_minmax");
    }
    add(id("sensor", "mean_temperature_today"), device, "mean_temperature_today", {
      attributes: { weather_entity: "weather.home" },
    });
    add(id("sensor", "mean_temperature_yesterday"), device, "mean_temperature_yesterday");
    add(id("sensor", "pgr_relative_growth"), device, "pgr_relative_growth", { enabled: false });
    add(id("sensor", "last_aerate"), device, "last_aerate", { enabled: false });
    add(id("binary_sensor", "pgr_due"), device, "pgr_due");
    add(id("date", "last_pgr_application"), device, "last_pgr_application");
    add(id("date", "log_date"), device, "log_date");
    for (const key of ["log_pgr_today", "log_mow", "log_application", "save_default_rate", "add_to_mix", "clear_mix", "log_activity"]) add(id("button", key), device, key);
    for (const key of ["pgr_product", "product", "mower_type", "activity"]) add(id("select", key), device, key);
    for (const key of ["gdd_target", "base_temperature", "cut_height", "application_rate"]) add(id("number", key), device, key);
    add(`calendar.${device}_lawn`, device, "lawn_calendar");
  }
  // Another integration's entity on a lawn device must be ignored.
  entities["sensor.other"] = { entity_id: "sensor.other", device_id: "front", platform: "other" };
  states["sensor.other"] = { entity_id: "sensor.other", state: "1", attributes: {} };

  return {
    entities,
    states,
    devices: {
      front: { id: "front", name: "Front lawn", name_by_user: null },
      back: { id: "back", name: "Back lawn", name_by_user: "Back yard" },
    },
  };
}

const headingsOf = (view) => view.sections.map((s) => s.cards[0].heading);
const cardsOf = (view) => view.sections.flatMap((s) => s.cards);
// Find a form by an entity in it (log forms start with the shared Date row).
const formIn = (sectionCards, entity) =>
  sectionCards.find((c) => c.type === "entities" && c.entities.some((r) => r.entity === entity));

// Two lawns: a tab each (sorted, using the user's device rename), then History and Settings.
const config = generateDashboard({}, mockHass());
assert.equal(config.title, "Lawn");
assert.deepEqual(config.views.map((v) => v.title), ["Back yard", "Front lawn", "History", "Settings"]);
assert.deepEqual(config.views.map((v) => v.path), ["back-yard", "front-lawn", "history", "settings"]);
assert.ok(config.views.every((v) => v.type === "sections" && !v.icon), "tabs show names, not icons");

// Lawn tab: three sections, for three balanced columns.
const front = config.views[1];
assert.equal(front.max_columns, 3);
assert.deepEqual(headingsOf(front), ["Plant growth regulator", "Mowing", "Renovation"]);
const entityIds = JSON.stringify(front);
assert.ok(!entityIds.includes("lawn_back_"), "front tab only uses front entities");
assert.ok(!entityIds.includes("sensor.other"), "other integrations are ignored");
assert.ok(!entityIds.includes("pgr_relative_growth"), "disabled entities are skipped");
assert.ok(!entityIds.includes("last_aerate"), "disabled activity sensors are skipped");

// PGR: gauge (or, with no PGR yet, a prompt) beside a stack of three tiles,
// the missing-data notice, then the form.
const [pgr, mowing, renovation] = front.sections.map((s) => s.cards);
const progressEntity = "sensor.lawn_front_pgr_progress";
assert.equal(pgr[1].type, "gauge");
assert.deepEqual(pgr[1].grid_options, { columns: 6 });
assert.deepEqual(pgr[1].visibility, [
  { condition: "state", entity: progressEntity, state_not: ["unknown", "unavailable"] },
]);
assert.equal(pgr[2].type, "markdown");
assert.match(pgr[2].content, /No PGR recorded yet/);
assert.deepEqual(pgr[2].grid_options, { columns: 6 });
assert.deepEqual(pgr[2].visibility, [
  { condition: "state", entity: progressEntity, state: ["unknown", "unavailable"] },
]);
assert.equal(pgr[3].type, "vertical-stack");
assert.deepEqual(pgr[3].grid_options, { columns: 6 });
assert.deepEqual(pgr[3].cards.map((c) => c.name), ["GDD since PGR", "Next due", "GDD today"]);
assert.ok(pgr[3].cards.every((c) => !c.grid_options), "stacked tiles have no grid options");
assert.equal(pgr[4].type, "markdown");
assert.equal(pgr[4].show_empty, false);
assert.match(pgr[4].content, /state_attr\('sensor\.lawn_front_gdd_since_pgr', 'missing_days'\)/);
// Comparisons live on the Settings tab, not in the lawn tab.
assert.ok(!JSON.stringify(front).includes("gdd_since_pgr_fallback"));
assert.ok(!JSON.stringify(front).includes("gdd_since_pgr_minmax"));
assert.deepEqual(
  formIn(pgr, "date.lawn_front_last_pgr_application").entities.map((r) => r.entity),
  ["date.lawn_front_last_pgr_application", "button.lawn_front_log_pgr_today"],
);

// Mowing, then a Products subheading, each with tiles and a form.
assert.deepEqual(
  mowing.filter((c) => c.type === "heading").map((c) => c.heading),
  ["Mowing", "Products"],
);
assert.deepEqual(formIn(mowing, "select.lawn_front_mower_type").entities, [
  { entity: "date.lawn_front_log_date", name: "Date" },
  { entity: "select.lawn_front_mower_type", name: "Mower type" },
  { entity: "number.lawn_front_cut_height", name: "Cut height" },
  { entity: "button.lawn_front_log_mow", name: "Log a mow", action_name: "Log" },
]);
assert.deepEqual(
  formIn(mowing, "select.lawn_front_product").entities.map((r) => r.entity),
  [
    "date.lawn_front_log_date",
    "select.lawn_front_product",
    "number.lawn_front_application_rate",
    "button.lawn_front_save_default_rate",
    "button.lawn_front_add_to_mix",
    "button.lawn_front_log_application",
  ],
);
// The mix card follows the products form, shown only while a mix is being built.
const mixCard = mowing.find((c) => c.type === "custom:turf-manager-mix-card");
assert.equal(mixCard.entity, "sensor.lawn_front_application_mix");
assert.equal(mixCard.device_id, "front");
assert.deepEqual(mixCard.visibility, [
  { condition: "numeric_state", entity: "sensor.lawn_front_application_mix", above: 0 },
]);
assert.equal(mowing.indexOf(mixCard), mowing.indexOf(formIn(mowing, "select.lawn_front_product")) + 1);

// Renovation tiles are named without the lawn name; Weather follows.
assert.deepEqual(
  renovation.filter((c) => c.type === "tile" && c.entity.includes("_last_")).map((c) => c.name),
  ["Scarified", "Cored", "Top dressed"],
);
assert.deepEqual(
  renovation.filter((c) => c.type === "heading").map((c) => c.heading),
  ["Renovation", "Weather"],
);
assert.equal(renovation.find((c) => c.type === "weather-forecast").entity, "weather.home");
assert.deepEqual(
  renovation.filter((c) => c.type === "tile" && c.entity.includes("mean_temperature")).map((c) => c.entity),
  ["sensor.lawn_front_mean_temperature_today", "sensor.lawn_front_mean_temperature_yesterday"],
);

// History tab: log for all lawns, both calendars, GDD graph named by lawn.
const history = config.views[2];
assert.equal(history.max_columns, 2);
assert.deepEqual(headingsOf(history), ["Log", "Calendar", "GDD since PGR"]);
const logCard = cardsOf(history).find((c) => c.type === "custom:turf-manager-log-card");
assert.equal(logCard.device_id, undefined, "all lawns when there are several");
assert.deepEqual(cardsOf(history).find((c) => c.type === "calendar").entities, ["calendar.back_lawn", "calendar.front_lawn"]);
assert.deepEqual(
  cardsOf(history).find((c) => c.type === "history-graph").entities.map((g) => g.name),
  ["Back yard", "Front lawn"],
);

// Settings tab: a form per lawn plus where to manage lawns and products.
const settings = config.views[3];
// Each lawn's settings include a GDD comparison box: four tiles with the difference,
// or just the main-sensor pair when there's no fallback sensor (the back lawn here).
const comparisonTiles = (sectionIndex) =>
  settings.sections[sectionIndex].cards.filter((c) => c.type === "tile");
assert.deepEqual(
  comparisonTiles(1).map((c) => [c.entity, c.name]),
  [
    ["sensor.lawn_front_gdd_since_pgr_mean", "Main sensor, daily-mean method"],
    ["sensor.lawn_front_gdd_since_pgr_minmax", "Main sensor, min/max method"],
    ["sensor.lawn_front_gdd_since_pgr_fallback", "Fallback sensor, daily-mean method"],
    ["sensor.lawn_front_gdd_since_pgr_fallback_minmax", "Fallback sensor, min/max method"],
  ],
);
assert.ok(comparisonTiles(1).every((c) => JSON.stringify(c.state_content) === '["state","difference"]'));
assert.deepEqual(
  comparisonTiles(0).map((c) => c.name),
  ["Main sensor, daily-mean method", "Main sensor, min/max method"],
);
assert.ok(
  settings.sections[1].cards.some((c) => c.type === "heading" && c.heading === "GDD since last PGR, compared"),
);
// The explanation says which application the totals run from.
const explanation = settings.sections[1].cards.find((c) => c.type === "markdown");
assert.match(explanation.content, /state_attr\('sensor\.lawn_front_gdd_since_pgr', 'last_application'\)/);
assert.match(explanation.content, /Totals since the last PGR application/);
assert.deepEqual(headingsOf(settings), ["Back yard", "Front lawn", "Lawns and products"]);
assert.deepEqual(
  settings.sections[1].cards[1].entities.map((r) => r.entity),
  ["select.lawn_front_pgr_product", "number.lawn_front_gdd_target", "number.lawn_front_base_temperature"],
);

// One lawn: the log card is scoped to it and the graph line is just "GDD".
const one = generateDashboard({}, mockHass({ lawns: ["front"] }));
assert.deepEqual(one.views.map((v) => v.title), ["Front lawn", "History", "Settings"]);
assert.equal(cardsOf(one.views[1]).find((c) => c.type === "custom:turf-manager-log-card").device_id, "front");
assert.equal(cardsOf(one.views[1]).find((c) => c.type === "history-graph").entities[0].name, "GDD");

// No lawns: a single helpful view.
const empty = generateDashboard({}, { entities: {}, states: {}, devices: {} });
assert.equal(empty.views.length, 1);
assert.equal(empty.views[0].sections[0].cards[0].type, "markdown");

// Unique paths, even when lawns share a name or are called "History".
const twins = mockHass();
twins.devices.back.name_by_user = "History";
assert.deepEqual(
  generateDashboard({}, twins).views.map((v) => v.path),
  ["front-lawn", "history", "history-2", "settings"],
);

console.log("dashboard strategy: all checks passed");
