---
description: "How GeoQuery's SvelteKit frontend is organised: routes, the stores that hold a request, tab state, recipes and share links, styling, maps and charts, and conventions."
---

# Frontend

`frontend/` is a SvelteKit 3 app using Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`), built with Vite and served by `adapter-node`. Use `bun` for everything: `bun install`, `bun run dev`, `bun run build`, `bun test`, `bun run check`.

## Conventions

- **Imports.** Use the `#lib/…` alias (declared in `package.json` `imports`), not `$lib`. `bun test` can't resolve it, so modules you unit-test import their own dependencies by relative path ([Testing](testing.md#frontend)).
- **Environment.** SvelteKit 3's modules are `$app/env` (for `browser`) and `$app/env/public` (for `PUBLIC_*` variables).
- **Components.** shadcn-svelte components are installed into `src/lib/components/ui/` (`bunx shadcn-svelte@next add <name>`), built on bits-ui. Icons are `@lucide/svelte`.
- **Styling.** Tailwind CSS v4, configured in CSS. `src/routes/layout.css` lists the folders Tailwind scans with `@source`: classes in a new folder outside them won't compile until it's added. The colour tokens, type and chart rules are in `design-system.md` at the repository root.
- **SSR.** Pages render on the server too, so anything touching `window`, `sessionStorage` or MapLibre runs in `onMount` or behind `browser`.

## Routes

| Route | Page |
|---|---|
| `/` | Step 1, Select Boundaries: the map, boundary search, Bulk select, presets, custom upload (beta) |
| `/customize` | Step 2, Customize Datasets. `?dataset=<name>` opens one dataset (Review's **Edit options**) |
| `/review` | Step 3, Review & Submit |
| `/requests/[id]` | One request: status, contents, download, **Copy results link** (the page's own address), and **Duplicate request**, which opens the request's share link in a new tab or copies it |
| `/requests/[[token]]` | Past Requests (signed out, with an emailed token) or My Requests (signed in) |
| `/legacy/[id]` | A request from the previous GeoQuery |
| `/s/[id]` | Opens a share link, after a confirmation if a request is in progress |
| `/stats` | System Status |
| `/account`, `/account/…` | Account, email addresses, GitHub sign-in callbacks |
| `/viz/…` | The map and visualize views (beta) |
| `/health/ready`, `/maintenance` | The readiness probe, and the maintenance page ([Site notices and maintenance](#site-notices-and-maintenance)) |

Keep new routes off `/requests/<id>/…`: the production proxy sends every path two or more segments under `/requests/` to the backend, which serves request downloads from there, so a page there works from an in-app link but 404s on a full page load, including one opened in a new tab ([Helm chart](deploying/kubernetes/helm-chart.md)).

`RequestPanel` (`lib/components/layout/`) is the left-hand panel shared by the three steps, with the step headings, the request summary and the **Copy share link** footer. On the first two steps the summary (features and boundary sets, columns and dataset selections) sits under **3. Review & Submit**; on Review it's under each step's own header.

### Narrow screens

There's no minimum width. Below Tailwind's `md` breakpoint (48rem) a step page shows either its panel or its detail view (the map, a dataset, the review), not both. `lib/stepDetail.ts` opens the detail as a shallow history entry, so the phone's back gesture closes it, and `layout.css` ("Narrow step pages") does the showing and hiding from `data-detail` on the layout's wrapper. Each detail view has a back button (`DetailBack`).

## The request being built

A request lives in Svelte stores in `src/lib/stores/` until it's submitted:

| Store | Holds |
|---|---|
| `selection` | The boundary selection: one set with optional feature ids, or several whole sets. `customizeHref` derives where step 2 is |
| `customBoundary` | An uploaded boundary file (beta) |
| `cart` | The datasets in the request and their options |
| `datasetChoices` | Per dataset: a raster's options while they're incomplete, or the feature selection being edited ([Saving dataset options](#saving-dataset-options)) |
| `requestForm` | The request's name and email |
| `features` | The caller's beta features, from `/api/config/` |
| `ui` | The current step and panel state |

### Saving dataset options

There's no "Add to Request": options save to the cart as they change (`routes/customize/+page.svelte`).

- **Rasters** have one cart entry per dataset, replaced on every change once it's complete: at least one measure, and a time period when the dataset has them. Incomplete options wait in `datasetChoices`.
- **Feature datasets** (`processing_class` `filter_and_agg`) can have several **selections**, each its own cart entry with its own name, which prefixes its columns. The one being edited is in `datasetChoices`, with `editingKey` set to its cart entry's kwargs (as JSON) while it's complete. A selection is complete with a measure chosen and at least one value in each field it splits by (`aggregate: false`); many feature datasets split by nothing. `saveFeatureChoices()` replaces the entry in place with `cart.replaceAt()`, which never merges it with another entry, adds it once it's complete, and takes it out (keeping its name in `datasetChoices.customName`) when it becomes incomplete or identical to another selection. `VersionCards` shows the selections, and **New selection** starts another.

A new selection, like a fresh raster, has nothing required chosen (the measure isn't preselected even when there's only one), so opening a dataset never adds it. The required cards with nothing chosen are outlined once anything in the dataset has been chosen (`MissingNote`, `MISSING_CARD`), and `OutputSummary` is the one-line status under "Select Dataset Options", with Reset at its end. A feature dataset's filters (`aggregate` true or unset) are behind **Custom filters**, open by default only when the selection narrows one.

Review's **Edit options** saves a feature entry to `datasetChoices` with its `editingKey` before opening Customize, so that entry is the one being edited. Raster period labels are formatted for display by `lib/utils/periods.ts` ("199501" as "1995 January"); the stored labels are left as they are, since recipes and the request documentation use them.

### Tab state

`stores/tabState.ts` saves the selection, cart, choices and form to `sessionStorage` under `geoquery-working-request`, debounced and flushed on `pagehide`, and `+layout.svelte` restores it before any page reads the stores. So a refresh keeps the request, two tabs don't overwrite each other, and closing the tab discards it. Nothing is saved while a custom upload is in use.

`sessionStorage` is copied into a tab opened from another, so a link opened in a new tab starts with the opener's request.

### Recipes, templates and share links

`lib/recipe.ts` defines the **recipe**: a versioned `{v: 1, boundaries, datasets}` description of a request, without its name or email. `currentRecipe()` builds one from the stores, `parseRecipe()` checks one from storage or the network, and `applyRecipe()` loads one into the stores. Tab state is stored as a recipe too.

`lib/loadRecipe.ts` loads a recipe from elsewhere (a share link at `/s/[id]`, which is also how a request's **Duplicate request** opens it). It replaces the current request, sets `recipeNotice` (shown by `RecipeNotice` on each step, listing anything that couldn't be loaded), and returns where to go: Review if there are datasets, otherwise the map.

`ShareLinkButton` posts the current recipe to `/api/analytics/shares/` and copies the link. Given a `current` key that changes with the request, it offers **Copy updated link** once the request changes after copying. Given a `url` (and a `label`) instead, it copies that address as it is: the request page's **Copy results link**. The backend side is in [APIs › Share links](apis.md#share-links-and-recipes).

## Talking to the backend

All API calls are in `src/lib/api.ts`, with their response types. `apiFetch` adds the CSRF header for writes. In development Vite proxies `/api` to the backend; in the cluster nginx does.

Authentication goes through django-allauth's headless API (`lib/allauth.ts`, `stores/auth.ts`).

## Site notices and maintenance

Both are switched on in `lib/config/status.ts`, which is built into the frontend image, so turning either on, off or changing its text means a commit and a frontend deploy.

- **`banner`** shows `StatusBanner` (`lib/components/layout/`), a slim bar above the header on every page, rendered by the root layout. Set `enabled`, a `type` (`info`, `warning` or `error`, coloured as in `design-system.md` §11) and the `message`. Visitors can dismiss it until they next load the page.
- **`maintenance`** takes the web app offline: `hooks.server.ts` redirects every page to `/maintenance` (307), which shows the `heading`, the `message` and, if set, `estimatedReturn`. It only covers the SvelteKit app. `/api/…` and request downloads go to the backend directly, so the API, the MCP server and the workers keep running unless they're scaled down separately.

Nothing switches these on by itself. If the backend can't be reached, the app still loads: `initAuth()` treats the visitor as signed out, and only the pages that fetch something show an error. `/stats` is the one place that says so, showing **Offline** when `/api/stats/status/` fails.

## Maps and charts

- **Maps** are MapLibre GL with a Protomaps basemap (`lib/map/`). Boundaries are vector tiles from `/api/features/tiles/…`. MapLibre is browser-only, so it's created in `onMount`.
- **Charts** use Observable Plot (`lib/charts/`, `lib/components/charts/`), following `design-system.md`.
- **The MCP map app** in `frontend/mcp-map/` is a separate single-file build (`bun run build:mcp-map`) written into `backend/mcp_server/apps/static/` for the MCP server to serve.

## Beta features

Gate a feature on `$features` (from `stores/features.ts`), with its name added to `FeatureName` and to `BETA_FEATURES` in `backend/accounts/features.py`. The backend decides who has it. Releasing it means removing it from `BETA_FEATURES`; the frontend checks can go afterwards.
