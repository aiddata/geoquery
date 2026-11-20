# AI Agent Instructions for GeoQuery Frontend

See also `../AGENTS.md` (project-wide rules, including permissions) and the developer docs page `docs/get-involved/contributing/dev/frontend.md`, which this summarizes.

## Project Overview

The SvelteKit frontend for AidData's GeoQuery: users select boundaries, choose datasets and their options, and submit extraction requests.

## Tech Stack

- **Framework**: SvelteKit 3 with Svelte 5 (runes mode), `adapter-node`
- **Styling**: Tailwind CSS v4 with shadcn-svelte components (bits-ui)
- **Maps**: MapLibre GL with a Protomaps basemap
- **Charts**: Observable Plot
- **Package manager**: Bun
- **Language**: TypeScript

## Key Commands

```bash
bun run dev      # dev server (in Compose: the frontend service)
bun run build    # production build
bun run check    # svelte-check: types and Svelte diagnostics
bun test         # unit tests (*.test.ts)
bun run build:mcp-map   # the MCP server's map app, into backend/mcp_server/apps/static/
```

## Project Structure

```
src/
├── lib/
│   ├── api.ts           # every backend call, with response types
│   ├── recipe.ts        # the request recipe format and loader
│   ├── loadRecipe.ts    # templates and share links
│   ├── components/
│   │   ├── layout/      # Header, RequestPanel, UserMenu, RecipeNotice, ...
│   │   ├── datasets/    # Customize page options
│   │   ├── map/         # map, boundary search, Bulk select
│   │   ├── charts/, stats/, viz/
│   │   └── ui/          # shadcn-svelte components
│   ├── stores/          # selection, cart, datasetChoices, requestForm, tabState, features, ui, ...
│   ├── map/             # basemap, choropleth
│   └── utils/
├── routes/
│   ├── +layout.svelte   # restores tab state before pages read the stores
│   ├── +page.svelte     # step 1: Select Boundaries (the map)
│   ├── customize/       # step 2: Customize Datasets
│   ├── review/          # step 3: Review & Submit
│   ├── requests/        # a request's page; Past Requests / My Requests
│   ├── s/[id]/          # opens a share link
│   ├── legacy/, stats/, account/, viz/ (beta), health/, maintenance/
mcp-map/                 # single-file map app served by the MCP server
```

## Conventions

- Import with the `#lib/...` alias (package.json `imports`), not `$lib`. `bun test` can't resolve it, so a module under unit test imports its dependencies by relative path.
- SvelteKit 3's environment modules are `$app/env` (`browser`) and `$app/env/public`.
- Pages render on the server too: anything using `window`, `sessionStorage` or MapLibre goes in `onMount` or behind `browser`.
- Beta features are gated on `$features` (`stores/features.ts`); the backend's `accounts/features.py` decides who has them.

## Tailwind CSS v4 Configuration

Tailwind v4 is configured in CSS. Classes are detected via `@source` directives in `src/routes/layout.css`:

```css
@import "tailwindcss";
@source "../lib";
@source ".";
```

If new directories contain Tailwind classes, add them as `@source` directives or classes won't compile.

## Styling Notes

- Colour tokens are CSS variables in `layout.css` (`--primary` and friends), with a dark theme under `[data-theme="dark"]` and the system preference. Use the shadcn token classes: `bg-primary`, `text-muted-foreground`, etc.
- Fonts: Barlow for body text and Noto Sans for UI controls (both from `@fontsource`), and Avenir Next for headings where the system has it (`--font-body`, `--font-ui`, `--font-heading` in `layout.css`).
- `design-system.md` at the repository root is the reference for colour, type, charts and UI copy.

## shadcn-svelte Components

```bash
bunx shadcn-svelte@next add <component-name> -y
```

Components are installed to `src/lib/components/ui/`. Import as:

```svelte
import { Button } from '#lib/components/ui/button/index.js';
import * as Dialog from '#lib/components/ui/dialog/index.js';
```

## The Request Being Built

The selection, cart, in-progress dataset choices and form live in stores, saved to `sessionStorage` by `stores/tabState.ts` and restored in `+layout.svelte`, so a refresh keeps them. Recipes (`lib/recipe.ts`) are the portable form of a request, used by tab state, "Use as template" and share links.

## API Integration

All endpoints are Django REST Framework views under `/api/` (proxied by Vite in development). Use the functions in `lib/api.ts`; `apiFetch` adds the CSRF header for writes. See `docs/get-involved/contributing/dev/apis.md`.
