# Changelog

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
