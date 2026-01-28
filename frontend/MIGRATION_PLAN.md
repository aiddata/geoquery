# GeoQuery Angular to SvelteKit Migration Plan

## Overview

Migrate the AngularJS 1.x GeoQuery application to SvelteKit with shadcn-svelte, focusing on layout reproduction first, then layering in logic.

---

## Phase 1: Layout Shell & Navigation

### 1.1 Root Layout Structure
**Goal:** Recreate the app shell with header, sidebar, and main content area.

**Angular Structure (root.html):**
- Right sidebar (`md-sidenav`) for cart/help panels
- Header toolbar
- Main content area (`ui-view`)

**SvelteKit Implementation:**
- [ ] Create `+layout.svelte` with the shell structure
- [ ] Add shadcn `Sheet` component for right sidebar
- [ ] Create `Header.svelte` component
- [ ] Set up CSS variables for AidData brand colors

**Files to create:**
```
src/
├── lib/
│   ├── components/
│   │   ├── Header.svelte
│   │   ├── Sidebar.svelte
│   │   └── StepIndicator.svelte
│   └── stores/
│       └── sidebar.ts
└── routes/
    └── +layout.svelte (update)
```

### 1.2 Header Component
**Goal:** Recreate the dual-toolbar header with logo, nav buttons, and step indicator.

**Angular Features:**
- Logo linking to aiddata.org/geoquery
- Help button
- Past Requests button
- Submit Request button with badge count
- 3-step process indicator (Select Boundary → Customize Datasets → Review Request)

**Implementation:**
- [ ] Add shadcn `Button` component
- [ ] Create step indicator with current step highlighting
- [ ] Add request count badge
- [ ] Style with AidData green (#115740) as primary color

### 1.3 Sidebar Component
**Goal:** Sliding right panel for cart, help, and past requests.

**Implementation:**
- [ ] Use shadcn `Sheet` (side="right")
- [ ] Create `CartPanel.svelte`
- [ ] Create `HelpPanel.svelte`
- [ ] Create sidebar state store

---

## Phase 2: Page Layouts

### 2.1 Map Page (Step 1: Select Boundary)
**Route:** `/` or `/map`

**Angular Structure (map.html):**
- Geography search bar (autocomplete)
- Zoom controls overlay
- Leaflet map frame

**Implementation:**
- [ ] Create `/routes/+page.svelte` (or `/routes/map/+page.svelte`)
- [ ] Add `GeographySearch.svelte` component with shadcn `Command` for autocomplete
- [ ] Add `ZoomControls.svelte` component
- [ ] Integrate Leaflet via `svelte-leaflet` or direct integration
- [ ] Create `MapFrame.svelte` wrapper

**Files:**
```
src/routes/
├── +page.svelte (map page)
└── (or map/+page.svelte)

src/lib/components/map/
├── GeographySearch.svelte
├── ZoomControls.svelte
└── MapFrame.svelte
```

### 2.2 Search Page (Step 2: Customize Datasets)
**Route:** `/search/[boundary]/[subboundary]`

**Angular Structure (search.html):**
- Left column (4/12): Dataset selector list
- Right column (8/12): Selection text + filter/options panels

**Implementation:**
- [ ] Create `/routes/search/[boundary]/[subboundary]/+page.svelte`
- [ ] Create `DatasetSelector.svelte` - list of available datasets
- [ ] Create `SelectionText.svelte` - "Add to Request" button area
- [ ] Create filter components:
  - `FiltersList.svelte` - multi-select checkboxes
  - `FiltersRange.svelte` - range sliders
- [ ] Create `RasterOptions.svelte` - for raster dataset configuration

**Files:**
```
src/routes/search/[boundary]/[subboundary]/
├── +page.svelte
├── +page.server.ts (load datasets)
└── [dataset]/
    └── +page.svelte

src/lib/components/search/
├── DatasetSelector.svelte
├── SelectionText.svelte
├── FiltersList.svelte
├── FiltersRange.svelte
└── RasterOptions.svelte
```

### 2.3 Checkout Page (Step 3: Review Request)
**Route:** `/checkout`

**Angular Structure (checkout.html):**
- Left column (55%): Selected items list
- Right column (45%): Submission form (email, name, terms)

**Implementation:**
- [ ] Create `/routes/checkout/+page.svelte`
- [ ] Create `SelectionsList.svelte` - expandable request items
- [ ] Create `SubmissionForm.svelte` - email, request name, terms checkbox
- [ ] Add form validation with shadcn form components

**Files:**
```
src/routes/checkout/
└── +page.svelte

src/lib/components/checkout/
├── SelectionsList.svelte
└── SubmissionForm.svelte
```

### 2.4 Additional Pages

**Login Page** (`/login`):
- [ ] Simple email input for looking up past requests

**Requests Page** (`/requests/[email]`):
- [ ] List of user's past requests

**Status Page** (`/status/[id]`):
- [ ] Single request status and download link

---

## Phase 3: State Management

### 3.1 Svelte Stores (replacing Angular factories)

**queryStore.ts** (replaces queryFactory):
```typescript
// Manages: boundary selection, dataset filters, options, cart
interface QueryState {
  boundary: Boundary | null;
  cart: CartItem[];
  // ...
}
```

**mapStore.ts** (replaces mapFactory):
```typescript
// Manages: map instance, loaded geometries, zoom level
```

**uiStore.ts** (replaces modal/spin factories):
```typescript
// Manages: sidebar state, loading states, dialogs
```

**Files:**
```
src/lib/stores/
├── query.ts
├── map.ts
├── ui.ts
└── user.ts
```

---

## Phase 4: API Integration

### 4.1 API Routes
Create SvelteKit server routes to proxy API calls (or call backend directly).

**Endpoints to implement:**
- [ ] `POST /api/boundaries` - Get available boundaries
- [ ] `POST /api/geometry/[id]` - Get GeoJSON for boundary
- [ ] `POST /api/datasets/[boundaryId]` - Get datasets for boundary
- [ ] `POST /api/filters` - Get filter options
- [ ] `POST /api/requests` - Lookup user requests
- [ ] `POST /api/submit` - Submit new request
- [ ] `POST /api/info` - Get app configuration

**Files:**
```
src/routes/api/
├── boundaries/+server.ts
├── geometry/[id]/+server.ts
├── datasets/[boundaryId]/+server.ts
├── filters/+server.ts
├── requests/+server.ts
├── submit/+server.ts
└── info/+server.ts
```

---

## Phase 5: Component Migration Details

### shadcn-svelte Components to Add

Run these commands to add required components:
```bash
npx shadcn-svelte@next add button
npx shadcn-svelte@next add sheet
npx shadcn-svelte@next add command
npx shadcn-svelte@next add input
npx shadcn-svelte@next add checkbox
npx shadcn-svelte@next add slider
npx shadcn-svelte@next add card
npx shadcn-svelte@next add badge
npx shadcn-svelte@next add dialog
npx shadcn-svelte@next add form
npx shadcn-svelte@next add collapsible
npx shadcn-svelte@next add separator
npx shadcn-svelte@next add scroll-area
npx shadcn-svelte@next add sonner  # for toasts
```

### Third-Party Libraries

```bash
# Mapping
bun add leaflet
bun add -D @types/leaflet

# Utilities
bun add clsx  # already installed
```

---

## Phase 6: Styling

### 6.1 Brand Colors
Update `layout.css` to include AidData brand colors:

```css
:root {
  /* AidData Brand */
  --aiddata-navy: oklch(0.18 0.03 260);      /* #161f34 */
  --aiddata-steel: oklch(0.42 0.03 240);     /* #405469 */
  --aiddata-lime: oklch(0.70 0.15 130);      /* #76b657 */
  --wm-green: oklch(0.35 0.10 160);          /* #115740 */
  
  /* Override primary with WM Green */
  --primary: var(--wm-green);
}
```

---

## Implementation Order (Recommended)

1. **Week 1: Shell**
   - Layout structure
   - Header component
   - Sidebar with Sheet
   - Basic routing

2. **Week 2: Map Page**
   - Leaflet integration
   - Geography search (mock data)
   - Zoom controls

3. **Week 3: Search Page**
   - Dataset selector (mock data)
   - Filter components
   - Selection text

4. **Week 4: Checkout + API**
   - Checkout form
   - API integration
   - State management

5. **Week 5: Polish**
   - Login/Requests/Status pages
   - Error handling
   - Testing

---

## Key Differences: Angular → Svelte

| Angular Concept | Svelte Equivalent |
|----------------|-------------------|
| `ng-if` / `ng-show` | `{#if}` / `class:hidden` |
| `ng-repeat` | `{#each}` |
| `ng-model` | `bind:value` |
| `ng-click` | `onclick` |
| `$scope` / Controllers | Component `$state` / props |
| Factories/Services | Svelte stores |
| `$broadcast` / `$on` | Store subscriptions |
| UI-Router states | SvelteKit file-based routing |
| `resolve` | `+page.server.ts` `load` function |
| Directives | Svelte components or actions |

---

## Notes

- The Angular app uses **Angular Material + Bootstrap hybrid** - we'll use **shadcn-svelte** (Tailwind-based) for a cleaner, modern approach
- The original app is **AngularJS 1.x** (2016 era) - SvelteKit offers significant performance and DX improvements
- Keep the **3-step wizard flow** intact as it's core to the UX
- The backend API can remain unchanged - just update the frontend proxy
