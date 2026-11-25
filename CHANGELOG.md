# Changelog

## Unreleased

- Irrigation: add sprinkler zones (any on/off `switch`, `valve` or `input_boolean`, e.g. ESPHome) and every run is recorded with its start and length, including runs that span a restart and recent runs from history. Log watering by hand from the dashboard or with `turf_manager.log_watering`. New sensors: last watered, watering last 7 days, and per-zone last run and 7-day minutes. The dashboard gets an Irrigation block with zone toggles; the History table and calendar include watering.
- Irrigation zones can be hand-watered (no switch), and watering by hand can be logged against a zone. The dashboard shows each zone's own 7-day minutes beside its on/off tile, plus the all-zones total.
- The "water" activity is replaced by irrigation logging (its sensor is removed; old entries stay in the history).
- GDD comparison box: clearer wording. It says which PGR application the totals run from (date, days and main GDD), and the tiles are named by method, e.g. "Main sensor, daily-mean method".

## 0.3.0 (2026-11-25)

- GDD comparison: diagnostic sensors for GDD since PGR from the main and fallback sensors, each by daily mean and by min/max average, with the difference from the main figure. Shown together in a "GDD comparison" box on the dashboard's Settings tab (the fallback comparison moved there from the PGR section). The fallback sensor's daily-mean comparison is now always daily mean, whatever method the main count uses.

## 0.2.0 (2026-11-25)

- With a fallback temperature sensor configured, each lawn also counts GDD since PGR from the fallback sensor alone, with the difference from the main figure, shown just below the main GDD on the dashboard.
- Dashboard: before any PGR is recorded, the PGR section shows a prompt to set the last application instead of a gauge error ("non-numeric entity").

## 0.1.0 (2026-11-25)

First release.

- GDD tracking for plant growth regulators: true daily mean (or min/max) from Home Assistant's long-term statistics, fallback sensor, manual days, warm- and cool-season base temperatures, editable targets.
- Projected next PGR date from the forecast; PGR due sensor and event; reminder blueprint with a "Mark applied" button.
- UNL relative-growth model for trinexapac-ethyl, paclobutrazol and prohexadione-Ca.
- Lawn care log: product applications (including mixes of several products), mowing (mower type, cut height in mm or inches, clippings) and renovation activities, with back-dating.
- Product library with presets, default rates and N-P-K for seasonal nitrogen totals.
- Calendar per lawn, logbook entries, history and CSV export actions.
- Bundled dashboard (Settings → Dashboards → Add dashboard → Turf Manager) with history table and mix cards.
