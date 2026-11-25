/*
 * Turf Manager frontend: a dashboard strategy and a history card.
 *
 * Served by the Turf Manager integration and loaded on every page.
 *
 * - Dashboard strategy: adds "Turf Manager" to Settings > Dashboards > Add
 *   dashboard. The dashboard is generated each time it opens: one view per
 *   lawn, built from the lawn's entities, so it follows any lawns you add,
 *   rename or remove. Entities are found by their translation key, never by
 *   entity id, because Home Assistant builds entity ids from area and device
 *   names.
 * - History card (custom:turf-manager-log-card): a table of logged entries
 *   with filters and delete.
 * - Mix card (custom:turf-manager-mix-card): the products added to a lawn's
 *   mix so far, with remove and clear.
 */

const DOMAIN = "turf_manager";
const STRATEGY_TYPE = "turf-manager";
const ELEMENT_NAME = `ll-strategy-dashboard-${STRATEGY_TYPE}`;
const CARD_TYPE = "turf-manager-log-card";
const MIX_CARD_TYPE = "turf-manager-mix-card";

const ACTIVITIES = [
  ["scarify", "Scarified"],
  ["core", "Cored"],
  ["aerate", "Aerated"],
  ["top_dress", "Top dressed"],
  ["level", "Levelled"],
  ["overseed", "Overseeded"],
  ["soil_test", "Soil tested"],
  ["other", "Other activity"],
];

const HALF = { grid_options: { columns: 6 } };
const FULL = { grid_options: { columns: 12 } };

/** Group this integration's enabled entities by device: { deviceId: { "domain:key": entityId } }. */
function entitiesByDevice(hass) {
  const byDevice = {};
  for (const entity of Object.values(hass.entities || {})) {
    if (entity.platform !== DOMAIN || !entity.device_id || entity.hidden) continue;
    if (!(entity.entity_id in hass.states)) continue; // disabled or not loaded
    const [domain, objectId] = entity.entity_id.split(".");
    const key = entity.translation_key || objectId;
    if (!byDevice[entity.device_id]) byDevice[entity.device_id] = {};
    byDevice[entity.device_id][`${domain}:${key}`] = entity.entity_id;
  }
  return byDevice;
}

function deviceName(hass, deviceId, fallback) {
  const device = (hass.devices || {})[deviceId];
  return (device && (device.name_by_user || device.name)) || fallback;
}

function slugify(text) {
  return (
    String(text)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "lawn"
  );
}

/* Card helpers. Each returns null when its entity doesn't exist (e.g. disabled). */

function tile(entity, name, extra = {}) {
  return entity ? { type: "tile", entity, ...(name ? { name } : {}), ...HALF, ...extra } : null;
}

function heading(text, icon, style = "title") {
  return { type: "heading", heading: text, icon, heading_style: style };
}

/**
 * A compact form: dropdowns for selects, type-in boxes for numbers, a date
 * picker for dates and a labelled button for the log action.
 */
function form(rows) {
  const entities = rows.filter((row) => row && row.entity);
  return entities.length ? { type: "entities", entities, state_color: false, ...FULL } : null;
}

function row(entity, name) {
  return entity ? { entity, name } : null;
}

function logRow(entity, name, action = "Log") {
  return entity ? { entity, name, action_name: action } : null;
}

/** A section with a heading; null if it would have nothing but headings. */
function section(title, icon, cards) {
  const content = cards.filter(Boolean);
  if (!content.some((card) => card.type !== "heading")) return null;
  return { type: "grid", cards: [heading(title, icon), ...content] };
}

/** Shown only when days since the last application have no temperature data. */
function missingDataNotice(entity) {
  if (!entity) return null;
  return {
    type: "markdown",
    show_empty: false,
    content:
      `{% set m = state_attr('${entity}', 'missing_days') or [] %}` +
      "{% if m | count %}" +
      "**{{ m | count }} day{{ '' if m | count == 1 else 's' }} without temperature data** " +
      "since the last application, counted as 0 GDD. Fill them in with " +
      "*Turf Manager: Set daily temperature* under Developer tools → Actions." +
      "{% endif %}",
    ...FULL,
  };
}

function pgrSection(e) {
  const progress = e["sensor:pgr_progress"];
  // Progress is unknown until a PGR application is recorded; a gauge can't show
  // that ("non-numeric entity"), so a prompt takes its place until then.
  const noValue = ["unknown", "unavailable"];
  const gauge = progress
    ? {
        type: "gauge",
        entity: progress,
        name: "PGR progress",
        min: 0,
        max: 120,
        needle: true,
        severity: { green: 0, yellow: 85, red: 100 },
        visibility: [{ condition: "state", entity: progress, state_not: noValue }],
      }
    : null;
  const noPgrYet = progress
    ? {
        type: "markdown",
        content:
          "### No PGR recorded yet\n" +
          "Set **Last applied** below to your last application, or press **Log** on " +
          "**Applied today**. Progress shows here once there is one.",
        visibility: [{ condition: "state", entity: progress, state: noValue }],
      }
    : null;
  const keyTiles = [
    tile(e["sensor:gdd_since_pgr"], "GDD since PGR"),
    tile(e["sensor:pgr_next_due"], "Next due"),
    tile(e["sensor:gdd_today"], "GDD today"),
  ].filter(Boolean);

  // The gauge sits beside a stack of three tiles of about the same height.
  let summary;
  if (gauge && keyTiles.length) {
    summary = [
      { ...gauge, ...HALF },
      { ...noPgrYet, ...HALF },
      { type: "vertical-stack", cards: keyTiles.map(({ grid_options, ...card }) => card), ...HALF },
    ];
  } else {
    summary = gauge ? [{ ...gauge, ...FULL }, { ...noPgrYet, ...FULL }] : keyTiles;
  }

  return section("Plant growth regulator", "mdi:sprout", [
    ...summary,
    missingDataNotice(e["sensor:gdd_since_pgr"]),
    tile(e["sensor:pgr_relative_growth"], "Relative growth", FULL),
    form([
      row(e["date:last_pgr_application"], "Last applied"),
      logRow(e["button:log_pgr_today"], "Applied today"),
    ]),
  ]);
}

function mixCard(mixSensor, deviceId) {
  if (!mixSensor) return null;
  return {
    type: `custom:${MIX_CARD_TYPE}`,
    entity: mixSensor,
    device_id: deviceId,
    // Only shown while a mix is being built.
    visibility: [{ condition: "numeric_state", entity: mixSensor, above: 0 }],
    ...FULL,
  };
}

function mowingAndProductsSection(e, deviceId) {
  const products = [
    tile(e["sensor:last_application"], "Last application"),
    tile(e["sensor:nitrogen_season"], "N this season"),
    form([
      row(e["date:log_date"], "Date"),
      row(e["select:product"], "Product"),
      row(e["number:application_rate"], "Rate"),
      logRow(e["button:save_default_rate"], "Make this the product's usual rate", "Save"),
      logRow(e["button:add_to_mix"], "Add to mix (for several products)", "Add"),
      logRow(e["button:log_application"], "Log an application"),
    ]),
    mixCard(e["sensor:application_mix"], deviceId),
  ].filter(Boolean);
  return section("Mowing", "mdi:mower", [
    tile(e["sensor:last_mowed"], "Last mowed"),
    tile(e["sensor:last_cut_height"], "Last height"),
    form([
      row(e["date:log_date"], "Date"),
      row(e["select:mower_type"], "Mower type"),
      row(e["number:cut_height"], "Cut height"),
      logRow(e["button:log_mow"], "Log a mow"),
    ]),
    ...(products.length ? [heading("Products", "mdi:spray"), ...products] : []),
  ]);
}

function weatherCards(hass, e) {
  const todaySensor = e["sensor:mean_temperature_today"];
  const weatherEntity = todaySensor
    ? (hass.states[todaySensor].attributes || {}).weather_entity
    : null;
  const cards = [
    tile(todaySensor, "Mean today"),
    tile(e["sensor:mean_temperature_yesterday"], "Mean yesterday"),
    weatherEntity && weatherEntity in hass.states
      ? {
          type: "weather-forecast",
          entity: weatherEntity,
          forecast_type: "daily",
          show_current: false,
          show_forecast: true,
          ...FULL,
        }
      : null,
  ].filter(Boolean);
  return cards.length ? [heading("Weather", "mdi:weather-partly-cloudy"), ...cards] : [];
}

/** Watering: last watered, 7-day total, a toggle per sprinkler zone, and logging by hand. */
function irrigationCards(hass, e) {
  const total = e["sensor:watering_7d"];
  const totalState = total ? hass.states[total] : null;
  const zones = (totalState && totalState.attributes && totalState.attributes.zones) || [];
  const cards = [
    tile(e["sensor:last_watered"], "Last watered"),
    tile(total, "Last 7 days"),
    ...zones
      .filter((zone) => zone.entity_id in hass.states)
      .map((zone) => tile(zone.entity_id, zone.name, { tap_action: { action: "toggle" } })),
    form([
      row(e["date:log_date"], "Date"),
      row(e["number:watering_minutes"], "Minutes"),
      logRow(e["button:log_watering"], "Log watering by hand"),
    ]),
  ].filter(Boolean);
  return cards.length ? [heading("Irrigation", "mdi:sprinkler-variant"), ...cards] : [];
}

function renovationAndWeatherSection(hass, e) {
  return section("Renovation", "mdi:shovel", [
    ...ACTIVITIES.map(([key, label]) => tile(e[`sensor:last_${key}`], label)),
    form([
      row(e["date:log_date"], "Date"),
      row(e["select:activity"], "Activity"),
      logRow(e["button:log_activity"], "Log it"),
    ]),
    ...irrigationCards(hass, e),
    ...weatherCards(hass, e),
  ]);
}

/** One tab per lawn: three columns of similar height. */
function lawnView(hass, lawn) {
  const e = lawn.entities;
  return {
    type: "sections",
    title: lawn.name,
    path: slugify(lawn.name),
    max_columns: 3,
    sections: [
      pgrSection(e),
      mowingAndProductsSection(e, lawn.id),
      renovationAndWeatherSection(hass, e),
    ].filter(Boolean),
  };
}

/** Everything logged, the calendars and the GDD graph, for all lawns. */
function historyView(lawns) {
  const single = lawns.length === 1;
  const calendars = lawns.map((l) => l.entities["calendar:lawn_calendar"]).filter(Boolean);
  const gdd = lawns
    .filter((l) => l.entities["sensor:gdd_since_pgr"])
    .map((l) => ({ entity: l.entities["sensor:gdd_since_pgr"], name: single ? "GDD" : l.name }));
  return {
    type: "sections",
    title: "History",
    path: "history",
    max_columns: 2,
    sections: [
      section("Log", "mdi:format-list-bulleted", [
        {
          type: `custom:${CARD_TYPE}`,
          title: "",
          ...(single ? { device_id: lawns[0].id } : {}),
          ...FULL,
        },
      ]),
      section("Calendar", "mdi:calendar", [
        calendars.length
          ? { type: "calendar", entities: calendars, initial_view: "dayGridMonth", ...FULL }
          : null,
      ]),
      section("GDD since PGR", "mdi:chart-line", [
        gdd.length ? { type: "history-graph", hours_to_show: 24 * 60, entities: gdd, ...FULL } : null,
      ]),
    ].filter(Boolean),
  };
}

/** GDD since PGR counted by each sensor and method, with the difference from the main figure. */
function comparisonCards(e) {
  const compare = (key, name) =>
    tile(e[`sensor:${key}`], name, { state_content: ["state", "difference"] });
  const tiles = [
    compare("gdd_since_pgr_mean", "Main sensor, daily-mean method"),
    compare("gdd_since_pgr_minmax", "Main sensor, min/max method"),
    compare("gdd_since_pgr_fallback", "Fallback sensor, daily-mean method"),
    compare("gdd_since_pgr_fallback_minmax", "Fallback sensor, min/max method"),
  ].filter(Boolean);
  if (!tiles.length) return [];
  const main = e["sensor:gdd_since_pgr"];
  const since = main
    ? `{% set d = state_attr('${main}', 'last_application') %}` +
      "{% if d %}**Totals since the last PGR application, {{ as_datetime(d).strftime('%a %-d %b') }}** " +
      "{% set n = state_attr('" + main + "', 'days_since_application') %}" +
      "({{ n }} day{{ '' if n == 1 else 's' }}, main GDD " +
      "{{ states('" + main + "') }}).{% else %}**No PGR recorded yet**, so there's nothing to total.{% endif %} "
    : "";
  return [
    heading("GDD since last PGR, compared", "mdi:compare-horizontal", "subtitle"),
    {
      type: "markdown",
      content:
        since +
        "Each total is counted from that application to now. *Daily mean* averages every " +
        "reading through each day; *min/max* uses (high + low) ÷ 2. The second figure is the " +
        "difference from your main GDD.",
      ...FULL,
    },
    ...tiles,
  ];
}

/** The rarely changed per-lawn settings. */
function settingsView(lawns) {
  return {
    type: "sections",
    title: "Settings",
    path: "settings",
    max_columns: 3,
    sections: [
      ...lawns.map((lawn) =>
        section(lawn.name, "mdi:grass", [
          form([
            row(lawn.entities["select:pgr_product"], "PGR product"),
            row(lawn.entities["number:gdd_target"], "GDD target"),
            row(lawn.entities["number:base_temperature"], "Base temperature"),
          ]),
          ...comparisonCards(lawn.entities),
        ]),
      ),
      section("Lawns and products", "mdi:cog", [
        {
          type: "markdown",
          content:
            "Add or edit lawns and products, and change the temperature sensors, under " +
            "**Settings → Devices & services → Turf Manager**.",
          ...FULL,
        },
      ]),
    ].filter(Boolean),
  };
}

function emptyView() {
  return {
    type: "sections",
    title: "Lawn",
    path: "lawn",
    sections: [
      {
        type: "grid",
        cards: [
          {
            type: "markdown",
            content:
              "## No lawns yet\n\nAdd Turf Manager and a lawn from " +
              "**Settings → Devices & services**, then come back here.",
          },
        ],
      },
    ],
  };
}

/** Build the dashboard config. Exported so it can be tested outside a browser. */
function generateDashboard(config, hass) {
  const byDevice = entitiesByDevice(hass);
  const lawns = Object.keys(byDevice)
    .filter((id) => byDevice[id]["sensor:gdd_since_pgr"])
    .map((id) => ({ id, name: deviceName(hass, id, "Lawn"), entities: byDevice[id] }))
    .sort((a, b) => a.name.localeCompare(b.name));

  const views = lawns.length
    ? [...lawns.map((lawn) => lawnView(hass, lawn)), historyView(lawns), settingsView(lawns)]
    : [emptyView()];

  // Keep view paths unique (a lawn could be called "History").
  const seen = {};
  for (const view of views) {
    const base = view.path;
    seen[base] = (seen[base] || 0) + 1;
    if (seen[base] > 1) view.path = `${base}-${seen[base]}`;
  }
  return { title: (config && config.title) || "Lawn", views };
}

class TurfManagerDashboardStrategy extends (globalThis.HTMLElement || class {}) {
  static async generate(config, hass) {
    return generateDashboard(config, hass);
  }
}

if (globalThis.customElements && !customElements.get(ELEMENT_NAME)) {
  customElements.define(ELEMENT_NAME, TurfManagerDashboardStrategy);
}

if (globalThis.window) {
  window.customStrategies = window.customStrategies || [];
  if (!window.customStrategies.some((s) => s.type === STRATEGY_TYPE)) {
    window.customStrategies.push({
      type: STRATEGY_TYPE,
      strategyType: "dashboard",
      name: "Turf Manager",
      description: "PGR timing, mowing, applications and the lawn care log for every lawn.",
    });
  }
}

/* ------------------------------------------------------------------------ */
/* History card                                                             */
/* ------------------------------------------------------------------------ */

const FILTERS = [
  { key: "all", label: "All" },
  { key: "pgr", label: "PGR" },
  { key: "application", label: "Applications" },
  { key: "mow", label: "Mowing" },
  { key: "activity", label: "Activities" },
  { key: "irrigation", label: "Watering" },
];

const KIND_ICONS = {
  application: "mdi:spray",
  mow: "mdi:mower",
  activity: "mdi:shovel",
  irrigation: "mdi:sprinkler-variant",
};

function escapeHtml(value) {
  return String(value === null || value === undefined ? "" : value).replace(
    /[&<>"']/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch],
  );
}

function filterEntries(entries, filter) {
  if (filter === "pgr") return entries.filter((e) => e.kind === "application" && e.is_pgr);
  if (filter && filter !== "all") return entries.filter((e) => e.kind === filter);
  return entries;
}

function entryIcon(entry) {
  if (entry.kind === "application" && entry.is_pgr) return "mdi:sprout";
  if (entry.kind === "irrigation" && entry.source === "manual") return "mdi:watering-can";
  return KIND_ICONS[entry.kind] || "mdi:grass";
}

/** Secondary line: amounts, nutrients, clippings, weather and notes. */
function entryDetails(entry) {
  const parts = [];
  if (entry.kind === "application") {
    const items = (entry.products || [entry]).filter(
      (item) => item.total_amount !== undefined && item.total_amount !== null,
    );
    if (items.length && entry.area_m2) {
      const totals = items.map((item) => {
        const name = entry.products ? `${item.product_name} ` : "";
        return `${name}${Math.round(item.total_amount)} ${item.total_unit || ""}`.trim();
      });
      parts.push(`${totals.join(", ")} over ${entry.area_m2} m²`);
    }
    if (entry.n_g_m2) parts.push(`N ${entry.n_g_m2} g/m²`);
  }
  if (entry.kind === "irrigation") {
    parts.push(entry.source === "manual" ? "By hand" : "Automatic");
  }
  if (entry.clippings_l !== undefined && entry.clippings_l !== null) {
    parts.push(`${entry.clippings_l} L clippings`);
  }
  if (entry.weather) {
    const bits = Object.entries(entry.weather).map(
      ([key, reading]) => `${key.replace(/_/g, " ")} ${reading.value}${reading.unit || ""}`,
    );
    if (bits.length) parts.push(bits.join(", "));
  }
  if (entry.notes) parts.push(entry.notes);
  return parts.join(" · ");
}

function formatWhen(entry, locale) {
  const day = new Date(`${entry.date}T12:00:00`);
  const date = day.toLocaleDateString(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  if (entry.all_day) return date;
  const time = new Date(entry.start).toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
  return `${date}, ${time}`;
}

const CARD_STYLES = `
  ha-card { overflow: hidden; }
  .filters { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 16px 4px; }
  .filters button {
    border: 1px solid var(--divider-color); border-radius: 16px; padding: 4px 12px;
    background: none; color: var(--primary-text-color); font: inherit; cursor: pointer;
  }
  .filters button.active {
    background: var(--primary-color); border-color: var(--primary-color);
    color: var(--text-primary-color, #fff);
  }
  table { width: 100%; border-collapse: collapse; }
  td { padding: 10px 16px; border-top: 1px solid var(--divider-color); vertical-align: top; }
  td.when { white-space: nowrap; color: var(--secondary-text-color); width: 1%; }
  td.what ha-icon { --mdc-icon-size: 18px; color: var(--secondary-text-color); margin-right: 6px; }
  .summary { color: var(--primary-text-color); }
  .details { color: var(--secondary-text-color); font-size: 0.9em; margin-top: 2px; }
  td.actions { width: 1%; white-space: nowrap; text-align: right; }
  td.actions button {
    background: none; border: none; cursor: pointer; padding: 4px 6px;
    color: var(--secondary-text-color); font: inherit; border-radius: 4px;
  }
  td.actions button:hover { color: var(--primary-text-color); }
  td.actions button.danger { color: var(--error-color); font-weight: 500; }
  .message { padding: 16px; color: var(--secondary-text-color); }
  .error { color: var(--error-color); }
  .more { display: block; width: 100%; padding: 12px; background: none; border: none;
    border-top: 1px solid var(--divider-color); color: var(--primary-color); font: inherit; cursor: pointer; }
  @media (max-width: 500px) { td.when { white-space: normal; width: auto; } td { padding: 8px 10px; } }
`;

/** A table of a lawn's logged entries with filters and delete. */
class TurfManagerLogCard extends (globalThis.HTMLElement || class {}) {
  constructor() {
    super();
    this._filter = "all";
    this._entries = null;
    this._error = null;
    this._confirming = null;
    this._busy = false;
    this._signature = undefined;
  }

  static getStubConfig() {
    return { title: "Lawn history" };
  }

  setConfig(config) {
    this._config = { title: "Lawn history", page_size: 15, ...config };
    this._limit = this._config.page_size;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    }
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Reload whenever a lawn's "Log entries" sensor changes (an entry was added, edited or deleted).
    const signature = this._logSignature(hass);
    if (signature !== this._signature) {
      this._signature = signature;
      this._load();
    }
  }

  getCardSize() {
    return 2 + Math.min(this._limit || 15, (this._entries || []).length);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  _logSignature(hass) {
    return Object.values(hass.entities || {})
      .filter(
        (e) =>
          e.platform === DOMAIN &&
          e.translation_key === "log_entries" &&
          (!this._config.device_id || e.device_id === this._config.device_id),
      )
      .map((e) => {
        const state = hass.states[e.entity_id];
        return state ? `${state.state}|${state.attributes.last_modified}` : "";
      })
      .join(",");
  }

  async _call(service, data, returnResponse = false) {
    const message = { type: "call_service", domain: DOMAIN, service, service_data: data };
    if (returnResponse) message.return_response = true;
    return this._hass.callWS(message);
  }

  async _load() {
    if (!this._hass || !this._config) return;
    const data = this._config.device_id ? { device_id: [this._config.device_id] } : {};
    try {
      const result = await this._call("get_history", data, true);
      const entries = (result && result.response && result.response.entries) || [];
      this._entries = entries.slice().reverse(); // newest first
      this._error = null;
    } catch (err) {
      this._error = (err && err.message) || String(err);
    }
    this._render();
  }

  async _delete(entryId) {
    this._busy = true;
    this._render();
    try {
      await this._call("delete_entry", { entry_id: entryId });
      this._confirming = null;
    } catch (err) {
      this._error = (err && err.message) || String(err);
    }
    this._busy = false;
    await this._load();
  }

  _onClick(ev) {
    const button = ev.target.closest("button");
    if (!button || this._busy) return;
    const { action, value } = button.dataset;
    if (action === "filter") {
      this._filter = value;
      this._limit = this._config.page_size;
      this._confirming = null;
    } else if (action === "ask-delete") {
      this._confirming = value;
    } else if (action === "cancel") {
      this._confirming = null;
    } else if (action === "delete") {
      this._delete(value);
      return;
    } else if (action === "more") {
      this._limit += this._config.page_size;
    } else {
      return;
    }
    this._render();
  }

  _row(entry, locale, showLawn) {
    const id = escapeHtml(entry.id);
    const details = entryDetails(entry);
    const lawn = showLawn && entry.lawn ? `${escapeHtml(entry.lawn)} · ` : "";
    const actions =
      this._confirming === entry.id
        ? `<button class="danger" data-action="delete" data-value="${id}">Delete</button>` +
          `<button data-action="cancel">Cancel</button>`
        : `<button data-action="ask-delete" data-value="${id}" title="Delete entry" aria-label="Delete entry">` +
          `<ha-icon icon="mdi:delete-outline"></ha-icon></button>`;
    return `
      <tr>
        <td class="when">${escapeHtml(formatWhen(entry, locale))}</td>
        <td class="what">
          <div class="summary"><ha-icon icon="${entryIcon(entry)}"></ha-icon>${escapeHtml(entry.summary)}</div>
          ${details || lawn ? `<div class="details">${lawn}${escapeHtml(details)}</div>` : ""}
        </td>
        <td class="actions">${actions}</td>
      </tr>`;
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const locale = (this._hass && this._hass.locale && this._hass.locale.language) || undefined;
    const entries = filterEntries(this._entries || [], this._filter);
    const shown = entries.slice(0, this._limit);
    const showLawn = !this._config.device_id;
    const title = this._config.title ? ` header="${escapeHtml(this._config.title)}"` : "";

    const filters = FILTERS.map(
      (f) =>
        `<button data-action="filter" data-value="${f.key}"` +
        `${f.key === this._filter ? ' class="active"' : ""}>${f.label}</button>`,
    ).join("");

    let body;
    if (this._entries === null && !this._error) {
      body = `<div class="message">Loading…</div>`;
    } else if (!shown.length) {
      body = `<div class="message">Nothing logged${this._filter === "all" ? "" : " of this kind"} yet.</div>`;
    } else {
      body =
        `<table><tbody>${shown.map((e) => this._row(e, locale, showLawn)).join("")}</tbody></table>` +
        (entries.length > shown.length
          ? `<button class="more" data-action="more">Show more (${entries.length - shown.length})</button>`
          : "");
    }
    const error = this._error ? `<div class="message error">${escapeHtml(this._error)}</div>` : "";

    this.shadowRoot.innerHTML =
      `<style>${CARD_STYLES}</style>` +
      `<ha-card${title}><div class="filters">${filters}</div>${error}${body}</ha-card>`;
  }
}

if (globalThis.customElements && !customElements.get(CARD_TYPE)) {
  customElements.define(CARD_TYPE, TurfManagerLogCard);
}

/* ------------------------------------------------------------------------ */
/* Mix card                                                                 */
/* ------------------------------------------------------------------------ */

const MIX_STYLES = `
  .title { display: flex; align-items: center; gap: 8px; padding: 12px 16px 4px; font-weight: 500; }
  .title ha-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
  ul { list-style: none; margin: 0; padding: 0 8px 0 16px; }
  li { display: flex; align-items: center; gap: 8px; padding: 6px 0;
    border-bottom: 1px solid var(--divider-color); }
  li:last-child { border-bottom: none; }
  .name { flex: 1; color: var(--primary-text-color); }
  .rate { color: var(--secondary-text-color); white-space: nowrap; }
  button { background: none; border: none; cursor: pointer; font: inherit; border-radius: 4px; }
  button.remove { color: var(--secondary-text-color); padding: 4px; }
  button.remove:hover { color: var(--error-color); }
  .footer { display: flex; align-items: center; gap: 8px; padding: 8px 16px 12px;
    color: var(--secondary-text-color); font-size: 0.9em; }
  .footer span { flex: 1; }
  button.clear { color: var(--primary-color); padding: 6px 8px; font-weight: 500; }
  .error { color: var(--error-color); padding: 0 16px 12px; }
`;

/** The products added to a lawn's mix so far, with remove and clear. */
class TurfManagerMixCard extends (globalThis.HTMLElement || class {}) {
  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    if (!config || !config.entity) throw new Error("Set entity to a lawn's Application mix sensor");
    this._config = config;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    }
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._config.entity];
    if (state !== this._state) {
      this._state = state;
      this._render();
    }
  }

  getCardSize() {
    return 2 + this._items().length;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  _items() {
    const state = this._state;
    return (state && state.attributes && state.attributes.products) || [];
  }

  async _call(service, data) {
    try {
      this._error = null;
      await this._hass.callWS({
        type: "call_service",
        domain: DOMAIN,
        service,
        service_data: { device_id: [this._config.device_id], ...data },
      });
    } catch (err) {
      this._error = (err && err.message) || String(err);
      this._render();
    }
  }

  _onClick(ev) {
    const button = ev.target.closest("button");
    if (!button || !this._hass) return;
    if (button.dataset.action === "remove") this._call("mix_remove", { product: button.dataset.value });
    if (button.dataset.action === "clear") this._call("mix_clear", {});
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const items = this._items();
    const rows = items
      .map((item) => {
        const rate = item.rate === null || item.rate === undefined ? "" : `${item.rate} ${item.unit || ""}`;
        return (
          `<li><span class="name">${escapeHtml(item.product)}</span>` +
          `<span class="rate">${escapeHtml(rate.trim())}</span>` +
          `<button class="remove" data-action="remove" data-value="${escapeHtml(item.product_id)}"` +
          ` title="Remove from mix" aria-label="Remove ${escapeHtml(item.product)} from mix">` +
          `<ha-icon icon="mdi:close"></ha-icon></button></li>`
        );
      })
      .join("");
    const count = `${items.length} product${items.length === 1 ? "" : "s"}`;
    this.shadowRoot.innerHTML =
      `<style>${MIX_STYLES}</style><ha-card>` +
      `<div class="title"><ha-icon icon="mdi:flask-outline"></ha-icon>In this mix · ${count}</div>` +
      `<ul>${rows}</ul>` +
      `<div class="footer"><span>Log an application logs these together.</span>` +
      `<button class="clear" data-action="clear">Clear</button></div>` +
      (this._error ? `<div class="error">${escapeHtml(this._error)}</div>` : "") +
      `</ha-card>`;
  }
}

if (globalThis.customElements && !customElements.get(MIX_CARD_TYPE)) {
  customElements.define(MIX_CARD_TYPE, TurfManagerMixCard);
}

if (globalThis.window) {
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === CARD_TYPE)) {
    window.customCards.push({
      type: CARD_TYPE,
      name: "Turf Manager history",
      description: "A table of logged lawn care with filters and delete. Set device_id to show one lawn.",
    });
  }
  if (!window.customCards.some((c) => c.type === MIX_CARD_TYPE)) {
    window.customCards.push({
      type: MIX_CARD_TYPE,
      name: "Turf Manager mix",
      description: "The products in a lawn's application mix. Set entity to its Application mix sensor and device_id to the lawn.",
    });
  }
}

if (typeof module !== "undefined") {
  module.exports = {
    generateDashboard,
    TurfManagerLogCard,
    TurfManagerMixCard,
    escapeHtml,
    filterEntries,
    entryDetails,
    formatWhen,
  };
}
