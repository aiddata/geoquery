# AI Agent Instructions for GeoQuery Frontend

## Project Overview

This is a SvelteKit frontend for AidData's GeoQuery application, migrated from an AngularJS 1.x codebase. It allows users to select geographic boundaries, customize datasets, and submit data extraction requests.

## Tech Stack

- **Framework**: SvelteKit 2 with Svelte 5 (runes mode)
- **Styling**: Tailwind CSS v4 with shadcn-svelte components
- **Maps**: MapLibre GL JS
- **Package Manager**: Bun
- **Language**: TypeScript

## Key Commands

```bash
bun run dev      # Start dev server
bun run build    # Production build
bun run check    # TypeScript checking
```

## Project Structure

```
src/
├── lib/
│   ├── components/
│   │   ├── layout/      # Header, Sidebar, panels
│   │   ├── map/         # MapFrame, GeographySearch, ZoomControls
│   │   └── ui/          # shadcn-svelte components
│   ├── stores/          # Svelte stores (ui.ts, etc.)
│   └── utils.ts         # Utility functions (cn helper)
├── routes/
│   ├── +layout.svelte   # Root layout with Header/Sidebar
│   ├── +page.svelte     # Map page (step 1)
│   ├── requests/        # Past requests lookup
│   ├── search/          # Dataset selection (step 2) [TODO]
│   └── checkout/        # Review & submit (step 3) [TODO]
```

## Tailwind CSS v4 Configuration

**Important**: Tailwind v4 uses CSS-first configuration. Classes are detected via `@source` directives in `src/routes/layout.css`:

```css
@import "tailwindcss";
@source "../lib";
@source ".";
```

If new directories contain Tailwind classes, add them as `@source` directives or classes won't compile.

## Svelte 5 Patterns

This project uses Svelte 5 runes:

```svelte
<script lang="ts">
  // Props
  let { propName = defaultValue }: Props = $props();
  
  // State
  let count = $state(0);
  
  // Derived
  let doubled = $derived(count * 2);
  
  // Effects
  $effect(() => {
    console.log(count);
  });
</script>
```

## shadcn-svelte Components

Add new components with:

```bash
bunx shadcn-svelte@next add <component-name> -y
```

Components are installed to `src/lib/components/ui/`. Import as:

```svelte
import { Button } from '$lib/components/ui/button';
import * as Sheet from '$lib/components/ui/sheet';
```

## Styling Notes

- **Brand Colors**: Defined as CSS variables in `layout.css`
  - Primary: `--wm-green` (William & Mary green)
  - Additional: `--aiddata-navy`, `--aiddata-steel`, `--aiddata-lime`
- **Font**: Lato (loaded from Google Fonts in layout)
- Use shadcn color tokens: `bg-primary`, `text-muted-foreground`, etc.

## Component Patterns

### Header with Conditional Steps

The Header component accepts `showSteps` prop. The layout determines this based on route:

```svelte
const workflowPaths = ['/', '/search', '/checkout'];
let showSteps = $derived(
  workflowPaths.some((path) => page.url.pathname === path || page.url.pathname.startsWith(path + '/'))
);
```

### Sidebar State

Sidebar state is managed via stores in `src/lib/stores/ui.ts`:

```ts
import { openSidebar, closeSidebar } from '$lib/stores/ui';
openSidebar('cart');  // or 'help'
```

### MapLibre Integration

MapLibre is loaded client-side only (SSR-incompatible). The MapFrame component handles this in `onMount`:

```svelte
onMount(() => {
  map = new maplibregl.Map({ container, style, ... });
  return () => map?.remove();
});
```

## Workflow Pages

The app has a 3-step wizard flow:

1. **Map** (`/`) - Select geographic boundary
2. **Search** (`/search/[boundary]/[subboundary]`) - Select and filter datasets
3. **Checkout** (`/checkout`) - Review selections and submit

## API Integration (TODO)

Backend API endpoints to implement:

- `POST /api/boundaries` - Get available boundaries
- `POST /api/geometry/[id]` - Get GeoJSON for boundary
- `POST /api/datasets/[boundaryId]` - Get datasets for boundary
- `POST /api/filters` - Get filter options
- `POST /api/requests` - Lookup user requests by email
- `POST /api/submit` - Submit new request
