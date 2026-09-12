# New Taipei Youth Observatory

Responsive React, Tailwind, and Recharts dashboard for exploring New Taipei City's cleaned household-registration population data.

## Quick start

1. Install dependencies in the `frontend` folder:

```bash
cd frontend
npm install
npm run dev
```

2. Open `http://localhost:5173` and explore pages.

The dashboard opens at `http://localhost:5173`. It includes district and year filters, light/dark themes, downloadable data, an interactive 3D district atlas with selected-place statistics, and responsive charts for population trends, migration, age structure, education levels, marriage status, and gender composition.

## Browser tests

Playwright is configured to use the installed Microsoft Edge browser at desktop and 390 px mobile widths. Run the interaction and responsive-layout checks from this folder:

```powershell
npm run test:e2e
```

The suite opens both custom selectors, searches for a district, changes the reference year, checks that the linked dashboard data updates, verifies mobile navigation, and guards against horizontal overflow.

## Spatial layout and motion

The dashboard uses an open paper/forest layout with stationary headings, indicators, controls, and chart labels. Lenis interpolates wheel input; sidebar clicks travel between section anchors over approximately 1.6–2.6 seconds. GSAP ScrollTrigger gradually fades analytical sections into focus as they enter the viewport, reaching full opacity in the reading area. Wheel input, Escape, and another sidebar selection can interrupt a journey. Keyboard navigation and reduced-motion preferences bypass the section fades.

Smooth motion and 3D are the defaults, with no mode switches. Old saved motion-toggle preferences are ignored. The operating system's reduced-motion setting still disables non-essential animation, without removing the static 3D map or its controls. Touch scrolling remains native. No extra motion dependency is needed.

If Windows/device animations are disabled, the dashboard explains why motion is paused and offers a one-time **Enable dashboard animations** action. Opening `http://localhost:5173/?motion=full` does the same thing. This explicit site-only choice is saved under `youth-compass-animation-consent` and enables Lenis, GSAP, CSS, and chart animations without changing Windows settings. The notice disappears after enabling; no permanent mode switches are added. `?motion=system` clears the opt-in. The parameter is removed from the address after saving, preserving other parameters and the current section.

For debugging, use Playwright's `reducedMotion: null` to read the real device preference. Omitting the option defaults to **emulated no-preference**, which previously hid the Windows restriction in our browser checks. The running-motion inspection script and dedicated preference regression tests now exercise native preferences and explicit dashboard consent.

Only the illustrative 3D city has idle movement and a scroll-responsive depth layer; it pauses offscreen and during interaction. Text does not bob, skew, or translate. The geographic map's hit targets remain stationary. Selected district and year stay visible in the header, with a shortcut back to the filters.

The district map and the 29-block city illustration use the selected year's population CSV. Map colors and block heights represent youth counts, not population density. Block placement and map relief are illustrative, not terrain. Selecting a map district updates the shared geography filter and the profile on its right (below on mobile): youth count, total residents, youth share, male/female youth, largest age cohort, and change from the prior release. Both release months are identified.

The map has no numbered labels, district directory, or comparison chart. All 29 district shapes are keyboard-selectable; small areas can also be selected from the shared Geography filter. Drag to pan, use +/− to zoom up to 300%, and use the reset-camera button to reframe. A focused map camera supports arrow keys, +/−, and Home. Vertical touch swipes and ordinary wheel input continue scrolling the page. Camera resets are interruptible, and drag gestures do not accidentally select a district. Hover relief is a non-interactive overlay so district hit targets stay still. Taipei City/Keelung City remain excluded neighboring context. Desktop wheel input over the sidebar also reaches Lenis.

Map geometry is checked in at `src/data/district-map.json`, derived from the MIT-licensed [taiwan-atlas 2021.9.20](https://github.com/dkaoster/taiwan-atlas). Boundaries are simplified 2021 geometry, separate from the year-filtered CSV counts. Attribution and the license are in `public/data/map-attribution.txt`. The map needs no external requests at runtime. To regenerate the geometry (network required):

```powershell
node scripts/build-district-map.mjs
```

With the dev server running, `node scripts/inspect-mono-atlas.mjs` captures desktop/mobile previews in both themes in `designs/mono-atlas/`. `node scripts/inspect-spatial.mjs` also records real scroll/velocity samples. Browser tests cover all 29 actual pointer targets, map camera interaction, CSV-backed profile values, proportional block heights, default/system motion preferences, interrupted sidebar journeys, and 320px filter menus.

## Mono chart design

All ten chart instances (including four KPI sparklines) adapt the [Amicro Mono Charts](https://amicro.vercel.app/mono-charts) design: monochrome ink, rounded spline caps, soft area gradients, full-radius pill bars, and a rounded donut with an interactive center readout. Charts retain the cleaned CSV data, readable axes, exact-value tooltips, and the migration forecast's dashed estimate and 80% interval. Open dashboard surfaces are preserved. The existing Recharts dependency is used; no demo data or showcase-only dependencies are imported. See `public/data/amicro-attribution.txt` for the pinned source revision and full MIT license.

`ChartMotion` starts line plots blank and gradually reveals their real geometry from left to right over 2.2 seconds, then stops. Bar and donut plots use shorter reveals. Axes, labels, values, and the underlying Recharts data remain fixed, and there is no repeating light sweep. Draw-ins replay for changed data, not on every scroll-by; the population chart also has a **Replay draw** button. Reduced motion shows the complete plot immediately. `node scripts/inspect-running-motion.mjs` saves successive screenshots in `designs/running-motion/` and logs measured animation positions on localhost.

## Refreshing dashboard data

From the repository root, rebuild the compact dashboard CSV from the cleaned population files:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_dashboard_data.ps1
```

The script reads the cleaned population, education, and marriage sources and writes compact analytical CSVs to `frontend/public/data/`. Population uses the latest available month in each year; marriage is restricted to ages 15–39; and education retains standardized source levels for UI grouping. Source files under `data/source` are never changed.

To copy all cleaned CSV files into Vite's public folder for additional analysis pages, run:

```powershell
.\scripts\sync_frontend_data.ps1
```

## Design assets

The `designs/wireframes/*.svg` files are lightweight reference frames that can be imported into Figma.
