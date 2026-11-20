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
| `/requests/[id]` | One request: status, contents, download, **Use as template**, share |
| `/requests/[[token]]` | Past Requests (signed out, with an emailed token) or My Requests (signed in) |
| `/legacy/[id]` | A request from the previous GeoQuery |
| `/s/[id]` | Opens a share link, after a confirmation if a request is in progress |
| `/stats` | System Status |
| `/account`, `/account/…` | Account, email addresses, GitHub sign-in callbacks |
| `/viz/…` | The map and visualize views (beta) |
| `/health`, `/maintenance` | Health check, and the maintenance page |

`RequestPanel` (`lib/components/layout/`) is the left-hand panel shared by the three steps, with the step headings, summaries and the **Copy share link** footer.

## The request being built

A request lives in Svelte stores in `src/lib/stores/` until it's submitted:

| Store | Holds |
|---|---|
| `selection` | The boundary selection: one set with optional feature ids, or several whole sets. `customizeHref` derives where step 2 is |
| `customBoundary` | An uploaded boundary file (beta) |
| `cart` | The datasets in the request and their options |
| `datasetChoices` | Options chosen for a dataset that isn't complete enough to be in the cart yet |
| `requestForm` | The request's name and email |
| `features` | The caller's beta features, from `/api/config/` |
| `ui` | The current step and panel state |

### Tab state

`stores/tabState.ts` saves the selection, cart, choices and form to `sessionStorage` under `geoquery-working-request`, debounced and flushed on `pagehide`, and `+layout.svelte` restores it before any page reads the stores. So a refresh keeps the request, two tabs don't overwrite each other, and closing the tab discards it. Nothing is saved while a custom upload is in use.

`sessionStorage` is copied into a tab opened from another, so a link opened in a new tab starts with the opener's request.

### Recipes, templates and share links

`lib/recipe.ts` defines the **recipe**: a versioned `{v: 1, boundaries, datasets}` description of a request, without its name or email. `currentRecipe()` builds one from the stores, `parseRecipe()` checks one from storage or the network, and `applyRecipe()` loads one into the stores. Tab state is stored as a recipe too.

`lib/loadRecipe.ts` loads a recipe from elsewhere ("Use as template" on a request page, or a share link at `/s/[id]`). It replaces the current request, sets `recipeNotice` (shown by `RecipeNotice` on each step, listing anything that couldn't be loaded), and returns where to go: Review if there are datasets, otherwise the map.

`ShareLinkButton` posts the current recipe to `/api/analytics/shares/` and copies the link. Given a `current` key that changes with the request, it offers **Copy updated link** once the request changes after copying. The backend side is in [APIs › Share links](apis.md#share-links-and-recipes).

## Talking to the backend

All API calls are in `src/lib/api.ts`, with their response types. `apiFetch` adds the CSRF header for writes. In development Vite proxies `/api` to the backend; in the cluster nginx does.

Authentication goes through django-allauth's headless API (`lib/allauth.ts`, `stores/auth.ts`).

## Maps and charts

- **Maps** are MapLibre GL with a Protomaps basemap (`lib/map/`). Boundaries are vector tiles from `/api/features/tiles/…`. MapLibre is browser-only, so it's created in `onMount`.
- **Charts** use Observable Plot (`lib/charts/`, `lib/components/charts/`), following `design-system.md`.
- **The MCP map app** in `frontend/mcp-map/` is a separate single-file build (`bun run build:mcp-map`) written into `backend/mcp_server/apps/static/` for the MCP server to serve.

## Beta features

Gate a feature on `$features` (from `stores/features.ts`), with its name added to `FeatureName` and to `BETA_FEATURES` in `backend/accounts/features.py`. The backend decides who has it. Releasing it means removing it from `BETA_FEATURES`; the frontend checks can go afterwards.
