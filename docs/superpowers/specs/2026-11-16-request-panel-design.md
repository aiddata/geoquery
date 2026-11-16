# Persistent request panel: design

Date: 2026-11-16. Status: approved in conversation; not yet planned.

## Goal

Keep the main request navigation in one left panel that stays put across the three request steps. The steps are Select Boundaries (`/`), Customize Datasets (`/customize`) and Review & Submit (`/review`). Each section of the panel expands when its step is active. The main area to the right shows the step's working content.

## Decisions

These were made with the user on 2026-11-16:

- **Layout:** the panel is a docked, fixed-width column (400px, at least as wide as the header breadcrumbs) on all three steps. On step 1 the map sits beside it rather than under a floating card.
- **Header steps:** stay as a minimal "you are here" indicator. They are not links, and the panel is the navigation.
- **Review & Submit section:** holds the request name, the email, the custom-boundary consent when it applies, and Submit. The main area holds only what's being reviewed.
- **Structure:** one shared `RequestPanel` component, rendered by each of the three routes, which stay separate.
  - It was chosen over a shared layout, which would have meant lifting the map page's working selection into stores.
  - It was also chosen over a single page, which would have broken URLs and history.

## Panel

There are three sections, always in this order. Exactly one is expanded: the current route's. Collapsed sections are one-line headers, above or below the expanded one.

| Section | Expanded on | Expanded body | Collapsed header | Header clickable when |
|---|---|---|---|---|
| 1. Boundaries | `/` | Today's boundary card: tabs (Explore / Browse All / Custom), search, chips, coverage count, notes, the selection-changed warning, **Find Data** | "1. Select Boundaries" with "{X} features across {Y} boundaries selected" and a pencil | Always, and goes to `/` |
| 2. Datasets | `/customize` | Today's `DatasetSelector`: category, search, sort, list with ✓ / ! marks | "2. Datasets: {n} in request" | A boundary selection exists (`customizeHref` is not null). Otherwise greyed out. |
| 3. Review & Submit | `/review` | Request name, email, custom-boundary consent (custom mode), error, **Submit Request** | "3. Review & Submit", plus a highlighted **Review ({n}) →** button once the cart has items | The cart has items, and goes to `/review`. Otherwise greyed out. |

- Find Data stays on step 1 as the primary way forward. Clicking the Datasets header does the same thing.
- After submitting, the Review & Submit body shows the existing success state, and the main area keeps the submitted summary.
- The panel scrolls inside its own body if the content is taller than the viewport. The headers stay visible.
- Accessibility:
  - Each section header is a button, or a disabled element with a tooltip saying what's needed first.
  - The expanded section has `aria-current="step"` on its header.
  - The panel is a `<nav aria-label="Request steps">`.
  - The header steps lose their `nav` and links, and become plain text with `aria-current` on the current one.

## Main area by step

- **`/` (map):** the map fills the area right of the panel. Zoom controls and the attribution stay on the map. There's no more floating card. The welcome modal's "centred panel" behaviour (panel docked or undocked) is removed, since the panel is always docked.
- **`/customize`:** the dataset header (metadata, cite, more metadata), the action row, and the options for the open dataset. Customize's own left column is removed, because the list now lives in the panel.
- **`/review`:** "Review your Selections", with the Boundaries and Datasets subsections, Modify Boundaries, Add Another Dataset, Edit options and Remove. The "Submit your Request" card is removed from the main area and moves to the panel.

## Components

- **New:** `lib/components/layout/RequestPanel.svelte`.
  - Props:
    - `active: 'map' | 'search' | 'review'`;
    - one snippet, `children`, for the expanded body;
    - an optional `footer` snippet.
  - It reads `selection`, `selectionSummary`, `customBoundary`, `customizeHref` and `cartCount` to build the collapsed headers, and navigates with `goto`.
- **Moved, not rewritten:** the boundary card body (map page), `DatasetSelector` (Customize) and the submit form (Review) become the snippet passed to `RequestPanel` by their page. Page-local state stays in the page.
- **Header.svelte:** the steps become non-interactive text with a muted current-step style. The next-step button styling goes, along with the link logic added earlier today (commits `60c380ad` and `c71357f8`).

## Known trade-off

The panel re-renders on navigation, so text typed in a panel search box is cleared when you change step. Selections, dataset choices and the cart are unaffected, since they live in stores.

## Out of scope

- Phone layouts. The minimum width and the notice stay as they are.
- Changes to what each step does: auto-save, GEO-104 behaviour, and the Measure / Split / Filter sections.

## Testing

- svelte-check clean.
- Puppeteer runs on the dev server:
  - The full flow: pick a boundary, then Find Data, then add ESA and ACLED, then Review, then Submit.
  - Going back through each collapsed header. Choices are kept, and the right section expands.
  - Disabled headers before a boundary is selected, and before the cart has items.
  - The GEO-104 edit flow, steps 1–17.
  - Screenshots of all three steps in light and dark mode, at 1440px and at the minimum width.
