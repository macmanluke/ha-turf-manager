# Turf Manager for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![Validate](https://github.com/macmanluke/ha-turf-manager/actions/workflows/validate.yml/badge.svg)](https://github.com/macmanluke/ha-turf-manager/actions/workflows/validate.yml)
[![Tests](https://github.com/macmanluke/ha-turf-manager/actions/workflows/tests.yml/badge.svg)](https://github.com/macmanluke/ha-turf-manager/actions/workflows/tests.yml)

A Home Assistant custom integration (install with HACS) that does two jobs:

1. **PGR timing by growing degree days (GDD).** Reads temperatures from sensors you already have (Ecowitt, BOM, anything with a temperature sensor) and counts GDD since your last plant growth regulator application. It projects the next due date from the forecast and reminds you on your phone.
2. **A lawn care log.** Fertiliser, herbicide and other product applications, mowing (mower type and cut height), and jobs like scarifying, coring and top dressing. Everything shows on a calendar per lawn.

It works with as many lawns as you like, each with its own grass type, base temperature, target and history.

**Highlights**

- True daily-mean GDD from your own weather station, backfilled from Home Assistant's history, so you can enter an application from weeks ago
- Warm-season (base 10 °C) and cool-season (base 0 °C) lawns, with editable targets (200 GDD by default)
- Projected next PGR date from your forecast, and a phone reminder with a "Mark applied" button
- Log applications (including tank mixes of several products), mowing and renovation, back-dated if you forgot
- A ready-made dashboard with a history table you can filter and delete from
- Seasonal nitrogen totals, and weather recorded with each spray

> **Not agronomic advice.** Turf Manager is a record-keeping and timing aid. Always follow the product label for rates, intervals and safety, and calibrate GDD targets for your own turf.

## How GDD is calculated

```
daily GDD = max(0, daily temperature − base temperature)
```

| Grass | Base | Example: day averaging 24 °C |
|---|---|---|
| Warm season (couch, kikuyu, buffalo, zoysia) | 10 °C | 14 GDD |
| Cool season (fescue, rye, bent, poa) | 0 °C | 24 GDD |

- **Daily temperature** defaults to the true daily mean: the average of every hourly mean that Home Assistant's recorder keeps for your sensor. You can also choose the average of the daily min and max, or the UNL "Hi-Lo" version, where lows are raised to the base.
- **A cold day counts as 0.** It never subtracts from the running total. Some spreadsheet versions let cold days go negative.
- **The count includes the day you apply** (UNL convention) and today's GDD so far.
- **The target** defaults to 200 GDD (trinexapac-ethyl). Change it per lawn.
- **GDD is always in °C-days**, the unit the 200 GDD target was set in. °F sensors are converted automatically.

The models follow the *PGR GDD Tracker v2.0* (Kreuser, University of Nebraska-Lincoln) and Syngenta's *Grow Degree Days Workbook*.

## Install

1. In HACS, open **⋮ → Custom repositories** and add `https://github.com/macmanluke/ha-turf-manager` as an **Integration**.
2. Install **Turf Manager** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → Turf Manager**.

Requires Home Assistant 2026.10 or later.

Turf Manager is new. Please [report problems](https://github.com/macmanluke/ha-turf-manager/issues) with your Home Assistant version and, if you can, the integration's diagnostics (integration page → ⋮ → Download diagnostics).

## Setup

**Site.** Pick your outdoor temperature sensor (for example the Ecowitt outdoor temperature). Then, optionally:
- a **fallback** sensor (for example a BOM observation sensor), used on days the main sensor has gaps
- a **weather** entity for forecasts, used to project the due date
- humidity, wind and rain sensors, recorded with every application for spray records

**First lawn.** Name, grass type, area, and GDD target. You can add the Primo Maxx preset to the product library at the same time.

**More lawns and products.** On the integration page, use **Add lawn** and **Add product**. Product presets fill in the PGR GDD interval and growth model. They deliberately leave the rate blank: use the label rate for your turf and region.

> **The temperature sensor needs `state_class: measurement`.** That makes Home Assistant keep long-term statistics, which are kept forever. Turf Manager can then backfill GDD for an application you enter weeks later. Ecowitt and BOM sensors have it already. If yours doesn't, a repair notice explains the fix.

## What you get per lawn

Each lawn is a device. Home Assistant builds entity ids from the lawn's area and name, so `<lawn>` below might be, for example, `backyard_front_lawn`. The bundled dashboard finds them for you.

| Entity | What it's for |
|---|---|
| `sensor.<lawn>_gdd_since_pgr` | GDD since the last PGR application. Attributes include the days since, the product, and any days with missing or incomplete data. |
| `sensor.<lawn>_pgr_progress` | % of target |
| `sensor.<lawn>_pgr_next_due` | Projected due date, from the forecast first and then the last 7 days' average |
| `binary_sensor.<lawn>_pgr_due` | On once the target is reached |
| `sensor.<lawn>_pgr_relative_growth` | UNL clipping-yield model (below 100% suppressed, above 100% rebound). Validated only for cool-season grass at base 0, so it's disabled by default for warm-season lawns. |
| `date.<lawn>_last_pgr_application` | **Pick a date** to log an application. A later date logs a new one; an earlier date corrects the last one. |
| `button.<lawn>_log_pgr_applied_today` | One tap |
| `number.<lawn>_pgr_gdd_target`, `number.<lawn>_base_temperature` | Fine-tune per lawn |
| `select.<lawn>_mower_type`, `number.<lawn>_cut_height`, `button.<lawn>_log_mow` | Set the mower and height once, then tap **Log mow** each time |
| `select.<lawn>_product`, `number.<lawn>_application_rate`, `button.<lawn>_log_application` | The same for product applications |
| `date.<lawn>_log_date` | The day the Log buttons record. Set an earlier day to catch up on things you forgot; it goes back to today at midnight. Back-dated entries are all-day, with no weather snapshot. |
| `button.<lawn>_save_rate_as_product_default` | Saves the rate you've entered as the selected product's default, so it's filled in next time |
| `button.<lawn>_add_to_mix`, `button.<lawn>_clear_mix`, `sensor.<lawn>_application_mix` | Build a mix of several products, then **Log application** logs them together |
| `select.<lawn>_activity`, `button.<lawn>_log_activity` | Scarify, core, aerate, top dress, level, overseed, soil test, water |
| `sensor.<lawn>_last_mowed`, `_last_cut_height`, `_last_application`, `_last_scarified`… | Shown as "3 days ago" |
| `sensor.<lawn>_nitrogen_this_season` | g N/m² from products with an N analysis. Resets each season (start month is set per site). |
| `sensor.<lawn>_mean_temperature_today`, `_yesterday` | The daily mean temperature the GDD is calculated from, with hours of data and which sensor it came from |
| `calendar.<lawn>` | Every entry, plus the projected PGR date. Delete an event to remove a mistake. |

Cut height is stored in mm and shown in mm or inches (site setting, or automatic from your unit system).

## Actions

| Action | Use |
|---|---|
| `turf_manager.log_pgr_application` | Log a PGR application (defaults to the lawn's PGR product) |
| `turf_manager.log_application` | Log a product application. Rate defaults to the product's rate and area to the lawn's area. For a mix, give `products` instead of `product`, e.g. `products: [{product: Lawn food, rate: 2.5}, {product: Primo Maxx, rate: 4}]`. |
| `turf_manager.mix_add` / `mix_remove` / `mix_clear` | Build a lawn's mix on the dashboard from scripts or other cards |
| `turf_manager.log_mow` | `mower_type`, `height`, optional `height_unit`, `clippings` (litres) |
| `turf_manager.log_activity` | Scarify, core, top dress… with details |
| `turf_manager.update_entry` / `delete_entry` | Fix an entry. The entry id is in the calendar event details. |
| `turf_manager.set_daily_temperature` | Enter a day's temperature by hand |
| `turf_manager.recalculate` | Fetch temperatures again after changing sensors |
| `turf_manager.get_history` | Returns entries and daily GDD (for scripts and templates) |
| `turf_manager.export_csv` | Writes the log and daily temperatures to `/config/turf_manager/` |

Every entry also appears in the logbook and fires a `turf_manager_entry_logged` event. Crossing the target fires `turf_manager_pgr_due`.

## Mixes

Several products applied together (a tank mix, or fertiliser with a wetting agent) are logged as **one application**:

- one calendar event and one history row, e.g. "PGR mix: Primo Maxx 4 mL/100m² + Lawn food 2.5 kg/100m²"
- each product's rate and total, and the nitrogen of all of them combined
- if the mix includes a PGR, it counts as a PGR application and restarts the GDD count

To change a mix's rates, delete it and log it again; its date, area and notes can be edited.

## Reminders

Import the blueprint, then create an automation from it. It picks the lawn's PGR progress sensor, your phone, a threshold (for example 90%) and a time of day:

[![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fmacmanluke%2Fha-turf-manager%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fturf_manager%2Fpgr_due_notify.yaml)

The notification has a **Mark applied today** button, which logs the application and restarts the count. The calendar entity also works with calendar triggers if you'd rather build your own.

## Dashboard

Turf Manager includes a ready-made dashboard:

1. Go to **Settings → Dashboards → Add dashboard**.
2. Choose **Turf Manager**, name it (for example "Lawn") and pick an icon.

You get a tab for each lawn, plus **History** and **Settings** tabs.

**Each lawn's tab** has three columns:

- **Plant growth regulator:** a progress gauge beside GDD since application, the projected due date and today's GDD. Below them are a date picker for the last application and an **Applied today** button. A notice appears if any days since the application have no temperature data.
- **Mowing and products:** mower type and cut height with a **Log** button, then product and rate with a **Log** button. Each form starts with a **Date**: today unless you pick an earlier day to catch up. Above each are when you last did it and, for products, nitrogen this season. For a mix, pick each product and rate and press **Add**; an "In this mix" card lists them (remove one with ✕, or **Clear**), and **Log** records them together.
- **Renovation and weather:** when you last scarified, cored and top dressed, an activity picker with a **Log** button, then the daily mean temperatures and your forecast.

**History:**

- A table of everything logged, newest first, filterable by PGR, applications, mowing or activities. Each row shows the details (totals, nitrogen, clippings, weather, notes) and has a delete button that asks you to confirm.
- The lawn calendars.
- A 60-day graph of GDD since PGR.

**Settings:** each lawn's PGR product, GDD target and base temperature.

The history table is also available as a card for your own dashboards: search for **Turf Manager history** in the card picker. Add `device_id` to show one lawn.

The dashboard is generated each time it opens, so it picks up lawns you add, rename or remove. To customise it, open the dashboard's **⋮ → Edit dashboard → Take control**. That converts it to a normal dashboard you can edit, which no longer updates itself.

## Tips

- **Calibrate the target.** 200 GDD was worked out on US cool-season golf greens. Log clipping volume when you mow (the `clippings` field), and adjust the target until the rebound flush disappears before re-application.
- **Sensor siting matters.** A temperature sensor in sun or near paving reads high. A +2 °C bias adds about 60 GDD a month at base 10. Use a radiation shield.
- **Spray records.** With humidity, wind and rain sensors configured, each application records the conditions at the time. Add a mode-of-action group to herbicides so you can rotate groups.

## Development

```bash
uv venv -p 3.14 && source .venv/bin/activate
uv pip install -r requirements_test.txt
pytest
```

`tests/test_gdd.py` checks the maths against values from the reference spreadsheets and runs without Home Assistant installed.

The frontend (dashboard strategy and history card) has its own tests, which need Node.js:

```bash
cd tests/js && npm install && npm test
```

To try it in a real Home Assistant, run the official image with the integration mounted. Copy the example configuration first: it adds a temperature you can set by hand and a fixed forecast. `dev_config/` isn't committed, since Home Assistant keeps your login and location there.

```bash
mkdir -p dev_config && cp -n dev/* dev_config/
```

```bash
docker compose -f docker-compose.dev.yml up -d
```

Then open http://localhost:8123. After changing code, restart the container:

```bash
docker compose -f docker-compose.dev.yml restart
```

The integration's icon (`custom_components/turf_manager/brand/`) is drawn by `scripts/make_icon.py`:

```bash
.venv/bin/python scripts/make_icon.py custom_components/turf_manager/brand
```

## Credits

- PGR GDD models and relative-growth coefficients: *PGR GDD Tracker v2.0*, Bill Kreuser, University of Nebraska-Lincoln, with research from the University of Wisconsin-Madison and Cornell University.
- Warm-season approach: Syngenta's *Grow Degree Days Workbook*, and the Australian lawn community's spreadsheet adaptations.

## Licence

MIT. The reference spreadsheets and workbooks above are their authors' work and aren't included in this repository.
