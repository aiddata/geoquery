# GeoQuery Design System

The system has a light theme and a dark theme. Surfaces are separated by tone and soft shadow rather than borders.

Contrast ratios are WCAG 2.x, computed from the hex values. Colorblind checks use the Machado et al. (2009) simulation at full severity, with CIEDE2000 color differences.

---

## 1. Color Palette

| Group | Token | Hex | Source / use |
|---|---|---|---|
| **Primary** | `forest` | `#00231b` | RD2 hero background; text on light; dark-theme page |
| | `emerald` | `#00795e` | Logo teal darkened for light backgrounds; links and buttons |
| | `gold` | `#fdb714` | Logo gold; main action on dark |
| **Support** | `teal` | `#00b18f` | Logo |
| | `sage` | `#b8ddb1` | RD2 sage button; links in dark theme |
| | `sky` | `#70cacb` | Logo |
| | `leaf` | `#67963a` | Logo |
| | `lemon` | `#d6c152` | Logo |
| | `sage-gray` | `#70a095` | Logo; input borders in dark theme |
| **Light neutrals** | `white` | `#ffffff` | Raised cards |
| | `mist` | `#f3f5f4` | Page background (green-tinted) |
| | `haze` | `#eaefed` | Sunken bands, subtle fills |
| | `silver` | `#d8dcdb` | Rules; subheads on dark |
| | `pewter` | `#7b8985` | Input and control borders |
| | `granite` | `#495965` | Secondary text |
| | `cream` | `#fcfbfa` | Text on dark |
| **Dark neutrals** | `forest-deep` | `#001a14` | Sunken bands, footer (dark theme) |
| | `forest-muted` | `#0c3027` | Subtle fills, alerts (dark theme) |
| | `forest-card` | `#123a30` | Raised cards (dark theme) |
| | `forest-line` | `#3d5c52` | Rules (dark theme) |
| **Derived** | `emerald-dark` | `#00664f` | Hover/pressed for emerald |
| | `gold-text` | `#7a5600` | Gold-family text on light |
| | `leaf-text` | `#4a7a22` | Leaf-family text on page and cards only |
| **Status** | `danger` | `#b3122a` | Errors (light); `#ff9aa6` in dark |
| **Chart** | `chart-1`…`chart-4` | see §3 | Data visualization only |

---

## 2. Surfaces and elevation

Three steps, lowest to highest. A section either sits on the page or is a full-width band; cards sit on either.

| Step | Light | Dark | Used for |
|---|---|---|---|
| Band (sunken) | `haze` `#eaefed` | `forest-deep` `#001a14` | Full-width sections that hold cards |
| Page | `mist` `#f3f5f4` | `forest` `#00231b` | Default background, long-form text |
| Card (raised) | `white` + shadow | `forest-card` `#123a30` + shadow | Cards, forms, figure frames |

**Shadows**
- **Light:** `0 1px 2px rgba(0,35,27,.06), 0 6px 16px -8px rgba(0,35,27,.14)`. The shadow is tinted with forest rather than black, so it reads as part of the palette.
- **Dark:** `inset 0 1px 0 rgba(255,255,255,.05), 0 1px 2px rgba(0,0,0,.35), 0 8px 20px -10px rgba(0,0,0,.6)`. Shadows barely show on dark, so dark cards depend on the tone step plus a faint top highlight.

**Rules**
- **Radius:** 10px for cards and figure frames, 6px for buttons and inputs, fully rounded for pills.
- **No divider lines between sections.** Alternate page and band instead.
- **Keep borders where they carry meaning:** form inputs and controls (`pewter`, 3.3:1 or better), table rules (`silver`), color swatches, and outline buttons.
- **Inputs inside cards** use the page tone as their fill, so fields read as slightly sunken.
- **Always-dark bands:** the hero and footer use `forest` (footer `forest-deep` in the dark theme), with a 4px `gold` rule where they meet the page.

---

## 3. Roles

### Text

| Role | Light | Dark |
|---|---|---|
| Body and headings | `forest` | `cream` |
| Secondary text | `granite` | `silver` |
| Links | `emerald`, hover `emerald-dark` | `sage`, hover `white` |
| Eyebrow labels / categories | `gold-text` (replaces bronze `#7c6541` / `#8d734a`) | `gold` |
| Errors | `danger` `#b3122a` | `#ff9aa6` |
| Hero headline (always dark) | `gold` | `gold` |
| Hero subhead (always dark) | `silver` | `silver` |

### Interactive
- **Primary button:** `emerald` with `white` text in light, `gold` with `forest` text in dark.
- **Buttons on always-dark bands:** `gold` fill with `forest` text for the main action (hero CTA, footer newsletter). For a secondary action, use a `teal` outline with `cream` text.
- **Links on dark bands (footer, hero):** `cream` text with a 2px `gold` underline on hover and focus.
- **Focus ring:** 2px outline offset 2px, `emerald` on light and `gold` on dark.
- **Switch knob:** uses the primary button's text color, so the knob stays at least 3:1 against its track in both themes.

### Data visualization
Don't use the six logo colors as a chart palette. Under simulated color vision deficiency, gold/lemon and teal/sage-gray become nearly identical (CIEDE2000 below 6), and teal/sky and leaf/sage-gray merge under tritanopia.

Use four chart series instead, with a separate set per theme. Each set stays distinct under protanopia, deuteranopia and tritanopia (minimum CIEDE2000 of 18.8 in light, 14.8 in dark):

| Series | Light | Label ink | Dark | Label ink |
|---|---|---|---|---|
| `chart-1` | `#00795e` emerald | `white` | `#67963a` leaf | `forest` |
| `chart-2` | `#fdb714` gold | `forest` | `#fdb714` gold | `forest` |
| `chart-3` | `#0d3e4a` deep blue | `white` | `#4fa8c4` blue | `forest` |
| `chart-4` | `#70cacb` sky | `forest` | `#fcfbfa` cream | `forest` |

- Keep `chart-2` and `chart-4` apart in stacked charts, since they share a gray value.
- Beyond four categories, use direct labels, shapes or small multiples rather than more colors.
- Give every mark a 1px edge in `forest` (light) or `cream` (dark), because gold and sky marks are below 3:1 against a light background. Label marks directly wherever §9.5 says a label fits.
- In map and point figures, pair each category with its own shape as well as its color.

### Sequential and diverging ramps

Maps and charts share two five-step ramps for continuous values. Both are ColorBrewer schemes that GeoQuery's maps already offer.

| Step | `seq` (YlGn) | Label ink | `div` (BrBG) | Label ink |
|---|---|---|---|---|
| 1 | `#ffffcc` | `forest` 16.3 | `#8c510a` | `white` 6.4 |
| 2 | `#c2e699` | `forest` 12.0 | `#d8b365` | `forest` 8.4 |
| 3 | `#78c679` | `forest` 8.1 | `#f5f5f5` | `forest` 15.3 |
| 4 | `#31a354` | `forest` 5.2 | `#5ab4ac` | `forest` 6.8 |
| 5 | `#006837` | `white` 6.9 | `#01665e` | `white` 6.9 |

- **Sequential** shows magnitude. Where darker means worse, use it anyway and state the direction in the legend.
- **Diverging** is only for data around a meaningful midpoint, such as zero, a correlation of 0 or a national average. Name the midpoint in the legend.
- **Why these two:**
  - Under the colorblind simulation, adjacent steps stay CIEDE2000 8.6 or more apart in `seq` and 17.5 or more in `div`.
  - `seq` lightness falls steadily (L* 99, 87, 73, 59, 38), and `div` is close to symmetric (40, 75, 97, 68, 38).
  - Every step takes a label ink at 5.2:1 or better. In `YlOrRd`, GeoQuery's current map default, the fourth step reaches only 4.3 with either ink.
  - Yellow-to-green and brown-to-teal sit nearest the brand palette.
- **Five classes, not a gradient.** Bin values into the five steps with thresholds or quantiles, so a legend reads as five classes and a chart matches its map.
- **The same values in both themes,** so a value keeps its color when the theme changes. The light end nearly disappears on a light card (1.0:1), and the dark end nearly does on a dark card (1.8:1). So every chart cell keeps its `--chart-edge`, and every map feature keeps its outline.
- **Missing values** are `--no-value` (`pewter`), never a ramp step (§11).
- **A chart drawn beside a map** uses that map's ramp, even when someone picked a different one.

---

## 4. Verified pairings

**Light theme**

| Foreground | On card `#ffffff` | On page `#f3f5f4` | On band `#eaefed` |
|---|---|---|---|
| `forest` | 16.7 | 15.3 | 14.4 |
| `granite` | 7.2 | 6.6 | 6.2 |
| `emerald-dark` | 7.0 | 6.4 | 6.0 |
| `gold-text` | 6.7 | 6.1 | 5.7 |
| `danger` | 6.9 | 6.3 | 6.0 |
| `emerald` | 5.4 | 4.9 | 4.6 |
| `leaf-text` | 5.1 | 4.7 | 4.4 (fails; don't use on bands) |
| `leaf` | 3.5 | 3.2 | 3.0 (graphics only) |
| `teal` | 2.7 | 2.5 | 2.4 (graphics only) |
| `gold` | 1.8 | 1.6 | 1.5 (never for text or thin lines) |

**Dark theme**

| Foreground | On card `#123a30` | On page `#00231b` | On band `#001a14` |
|---|---|---|---|
| `cream` | 12.1 | 16.2 | 17.6 |
| `silver` | 9.1 | 12.1 | 13.1 |
| `sage` | 8.4 | 11.2 | 12.1 |
| `gold` | 7.2 | 9.5 | 10.3 |
| `sky` | 6.6 | 8.8 | 9.5 |
| `#ff9aa6` (error) | 6.2 | 8.3 | 9.0 |
| `teal` | 4.6 | 6.1 | 6.6 |
| `sage-gray` | 4.3 (borders only) | 5.7 | 6.2 |
| `leaf` | 3.6 (graphics only) | 4.8 | 5.2 |

**Buttons, pills and controls**
- `white` on `emerald`: 5.4
- `forest` on `gold`: 9.5
- `forest` on `teal`: 6.1
- `forest` on `sage`: 11.2
- `forest` on `sky`: 8.8
- `pewter` input border: 3.7 on white, 3.3 on page
- `sage-gray` input border in dark: 4.3 on card, 5.7 on page

Rule of thumb: **`teal`, `gold`, `sky`, `lemon` and `leaf` are for dark backgrounds, fills and graphics. On light backgrounds, text uses `forest`, `granite`, `emerald`, `gold-text` or `leaf-text`.**

---

## 5. Accessibility modes

- **Increased contrast (`prefers-contrast: more`):**
  - Secondary text, links, eyebrows and borders step darker in light (`#2e3b44`, `#00664f`, `#5c4100`) and lighter in dark (`#eef0ef`, `#d4ecd0`, `#ffc83d`).
  - Input borders become `forest` in light and `sage` in dark.
  - Chart axes (`--chart-axis`) follow the input borders, and gridlines (`--chart-grid`) step up to `pewter` in light (3.7 on card) and `sage-gray` in dark (4.3 on card).
  - All links are underlined.
  - Cards and figure frames get a solid border and drop their shadow.
  - Decorative hero art is hidden.
- **Forced colors (Windows High Contrast):**
  - Shadows and background colors are removed in this mode, so cards, notes, figure frames, pills and buttons get a `CanvasText` border.
  - Custom checkboxes and switches draw with `Highlight` / `HighlightText` so their state stays visible.
  - Charts, swatches and maps opt out with `forced-color-adjust: none` so their colors keep meaning.
- **Reduced motion:** all transitions are disabled.

---

## 6. CSS tokens

Semantic names follow shadcn/ui so components port directly.

```css
:root {
  /* Surfaces */
  --background: #f3f5f4;        /* page */
  --card: #ffffff;              /* raised */
  --band: #eaefed;              /* sunken */
  --muted: #eaefed;             /* subtle fills */
  --card-shadow: 0 1px 2px rgba(0,35,27,.06), 0 6px 16px -8px rgba(0,35,27,.14);
  --radius: 6px;                /* buttons, inputs */
  --radius-card: 10px;          /* cards, figure frames */

  /* Text */
  --foreground: #00231b;
  --muted-foreground: #495965;
  --eyebrow: #7a5600;
  --danger-text: #b3122a;

  /* Lines and controls */
  --border: #d8dcdb;
  --input: #7b8985;

  /* Actions */
  --primary: #00795e;
  --primary-foreground: #ffffff;
  --primary-hover: #00664f;
  --ring: #00795e;
  --link: #00795e;
  --link-hover: #00664f;

  /* Always-dark bands */
  --hero-bg: #00231b;
  --footer-bg: #00231b;

  /* Status */
  --alert-bg: #e9f4e6;

  /* Charts */
  --chart-1: #00795e; --chart-1-ink: #ffffff;
  --chart-2: #fdb714; --chart-2-ink: #00231b;
  --chart-3: #0d3e4a; --chart-3-ink: #ffffff;
  --chart-4: #70cacb; --chart-4-ink: #00231b;
  --chart-edge: #00231b;
  --chart-grid: #d8dcdb;        /* silver: gridlines */
  --chart-axis: #7b8985;        /* pewter: baselines, tooltip borders */

  /* Ramps (§3): the same in both themes, so not repeated below */
  --seq-1: #ffffcc; --seq-2: #c2e699; --seq-3: #78c679; --seq-4: #31a354; --seq-5: #006837;
  --seq-1-ink: #00231b; --seq-2-ink: #00231b; --seq-3-ink: #00231b; --seq-4-ink: #00231b; --seq-5-ink: #ffffff;
  --div-1: #8c510a; --div-2: #d8b365; --div-3: #f5f5f5; --div-4: #5ab4ac; --div-5: #01665e;
  --div-1-ink: #ffffff; --div-2-ink: #00231b; --div-3-ink: #00231b; --div-4-ink: #00231b; --div-5-ink: #ffffff;
  --no-value: #7b8985;          /* pewter: missing values on maps and charts */

  /* Brand constants */
  --forest: #00231b; --emerald: #00795e; --gold: #fdb714;
  --teal: #00b18f; --sage: #b8ddb1; --sky: #70cacb;
  --leaf: #67963a; --lemon: #d6c152; --sage-gray: #70a095;
  --cream: #fcfbfa; --silver: #d8dcdb;
  --wm-bar: #115740;            /* W&M endorsement bar only */
}

/* Dark theme: repeat under @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { … } } */
:root[data-theme="dark"] {
  --background: #00231b;
  --card: #123a30;
  --band: #001a14;
  --muted: #0c3027;
  --card-shadow: inset 0 1px 0 rgba(255,255,255,.05), 0 1px 2px rgba(0,0,0,.35), 0 8px 20px -10px rgba(0,0,0,.6);
  --foreground: #fcfbfa;
  --muted-foreground: #d8dcdb;
  --eyebrow: #fdb714;
  --danger-text: #ff9aa6;
  --border: #3d5c52;
  --input: #70a095;
  --primary: #fdb714;
  --primary-foreground: #00231b;
  --primary-hover: #ffc83d;
  --ring: #fdb714;
  --link: #b8ddb1;
  --link-hover: #ffffff;
  --footer-bg: #001a14;
  --alert-bg: #0c3027;
  --chart-1: #67963a; --chart-1-ink: #00231b;
  --chart-2: #fdb714; --chart-2-ink: #00231b;
  --chart-3: #4fa8c4; --chart-3-ink: #00231b;
  --chart-4: #fcfbfa; --chart-4-ink: #00231b;
  --chart-edge: #fcfbfa;
  --chart-grid: #3d5c52;
  --chart-axis: #70a095;
  color-scheme: dark;
}
```

---

## 7. Wiring the tokens into shadcn-svelte

GeoQuery's frontend uses shadcn-svelte on Tailwind CSS v4. Its theme lives in `frontend/src/routes/layout.css`, and the components are copied into `frontend/src/lib/components/ui/`, so we own and edit them. The tokens in §6 replace that file's `:root` and `.dark` blocks. Five things need more than a copy.

### Tokens the components need that §6 doesn't define

| Token | Light | Dark | Used by |
|---|---|---|---|
| `--card-foreground`, `--popover-foreground` | `forest` | `cream` | Card, Select, DropdownMenu |
| `--popover` | `white` | `forest-card` | Select and DropdownMenu content |
| `--secondary` / `--secondary-foreground` | `haze` / `forest` (14.4) | `forest-line` / `cream` (7.1) | Badge `secondary` |
| `--accent` / `--accent-foreground` | `haze` / `forest` | `forest-line` / `cream` | Ghost and outline hover, menu and select highlight |
| `--destructive` / `--destructive-foreground` | `danger` / `white` (6.9) | `#ff9aa6` / `forest` (8.3) | Destructive button, invalid fields |
| `--warning-bg` | `#fff5de` | `forest-muted` | Status pills and alerts (§11) |
| `--danger-bg` | `#f9ecee` | `forest-muted` | Status pills and alerts (§11) |

`#fff5de` is `gold` at 14% over white and `#f9ecee` is `danger` at 8% over white. Both are new derived values.

Register every token a utility needs in `@theme inline`, for example `--color-band: var(--band)`, `--color-eyebrow: var(--eyebrow)`, `--color-link: var(--link)` and `--color-destructive-foreground: var(--destructive-foreground)`.

### Radius and shadow

shadcn derives its whole radius scale from `--radius`: `rounded-md` is `--radius` minus 2px, `rounded-lg` is `--radius`, and `rounded-xl` is `--radius` plus 4px. With `--radius: 6px` that makes buttons and inputs 4px and dialogs 6px. Set the scale explicitly instead:

```css
@theme inline {
  --radius-sm: 4px;                  /* checkboxes, tooltips */
  --radius-md: var(--radius);        /* buttons, inputs, menus: 6px */
  --radius-lg: var(--radius-card);   /* dialogs, sheets, popovers: 10px */
  --radius-xl: var(--radius-card);   /* cards, figure frames: 10px */
  --shadow-card: var(--card-shadow); /* gives the shadow-card utility */
}
```

§6 originally called these tokens `--radius-lg` and `--shadow-card`. Those names collide with Tailwind theme keys, which makes it unclear which value wins, so §6 now uses `--radius-card` and `--card-shadow`.

### Dark-mode selector

`layout.css` declares `@custom-variant dark (&:is(.dark *));`, but §6 switches themes with `data-theme` and the system preference. Replace the variant so every `dark:` class in the components follows the same rule:

```css
@custom-variant dark {
  &:where([data-theme="dark"], [data-theme="dark"] *) { @slot; }
  @media (prefers-color-scheme: dark) {
    &:where(:root:not([data-theme="light"]), :root:not([data-theme="light"]) *) { @slot; }
  }
}
```

Nothing in the app sets a theme today, so GeoQuery is light-only. Turning dark mode on also means switching the Protomaps basemap from `namedFlavor('light')` to `namedFlavor('dark')` in `MapFrame.svelte`.

### Focus

shadcn draws focus as a 3px ring at 50% `--ring`. Emerald at 50% over white is `#80bcae`, which is 2.2:1, below the 3:1 a focus indicator needs. Use the §3 rule instead:

- Components: replace `focus-visible:ring-ring/50 focus-visible:ring-[3px]` with `focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring`.
- Base layer: change `outline-ring/50` to `outline-ring`.
- Never ship `focus:outline-none` without a replacement.

Resulting contrast: `emerald` is 5.4 on card and 4.9 on page; `gold` is 7.1 on a dark card.

### Per-component edits

| Component | Now | Change |
|---|---|---|
| Card | `border shadow-sm` | `shadow-card`, no border. Add `contrast-more:border contrast-more:shadow-none` and `forced-colors:border` (§5) |
| Input, Select trigger, Checkbox | `dark:bg-input/30` fills fields with 30% `sage-gray` | `bg-background`, so fields read as sunken in both themes (§2) |
| Button `destructive` | `text-white` and `dark:bg-destructive/60` | `text-destructive-foreground`. White fails on dark-theme `#ff9aa6` |
| Dialog, Sheet | `bg-background`, overlay `bg-black/50` | `bg-card shadow-card`; overlay is `forest` at 60% |
| Tooltip | Body is `bg-foreground`, arrow is `bg-primary` | Arrow `bg-foreground` too. Today an emerald arrow points out of a forest tooltip |
| All | `tw-animate-css` enter and exit animations | Add a global `prefers-reduced-motion: reduce` rule that zeroes `animation-duration` as well as `transition-duration` (§5) |

---

## 8. Typography

Three typefaces, each with one job:

- **Avenir Next** for headings.
- **Barlow** for reading text.
- **Noto Sans** for interface and data labels.

Headings and body text need visibly different faces. A DIN-style face for both made headings read too much like body copy, so headings stay on the rounder Avenir.

### Typefaces

| Role | Family | Source and license | Weights in use | Fallback stack |
|---|---|---|---|---|
| Headings (`--font-heading`) | Avenir Next | System font on macOS and iOS; commercial (Monotype) | 700 | `"Avenir Next", Avenir, "Helvetica Neue", Helvetica, Arial, Roboto, sans-serif` |
| Body (`--font-body`) | Barlow | Google Fonts, SIL Open Font License | 400, 400 italic, 700 | `"Barlow", "DIN Next", "DIN Alternate", "Helvetica Neue", Arial, sans-serif` |
| Interface (`--font-ui`) | Noto Sans | Google Fonts, SIL Open Font License | 700 | `"Noto Sans", "Helvetica Neue", Arial, sans-serif` |

Avenir Next is not served as a webfont. Mac and iPhone users see it; everyone else gets Helvetica Neue, Arial or Roboto (see §12).

**What each face is for**

- **Avenir Next:** page and section headings (h1–h4), card titles and the hero subhead.
- **Barlow:** body text, standfirsts, captions, footnotes, form labels and inputs, navigation links, inline text links and table cells.
- **Noto Sans:**
  - The "AidData" wordmark text, buttons and category pills.
  - Chart and map labels and table column headers.
  - Footer column headings, footnote markers and the skip link.
  - Anywhere a short label has to read as interface rather than prose.

### Type scale

All sizes are in `rem`, so they scale with the reader's browser settings. Pixel values assume a 16px root.

| Style | Family | Size | Line height | Weight | Notes |
|---|---|---|---|---|---|
| Heading 1 | Avenir Next | `clamp(1.9rem, 4vw, 2.6rem)` (30–42px) | 1.12 | 700 | Letter-spacing −0.01em |
| Heading 2 | Avenir Next | 1.75rem (28px) | 1.2 | 700 | |
| Heading 3 | Avenir Next | 1.25rem (20px) | 1.3 | 700 | |
| Heading 4 / card title | Avenir Next | 1.0625rem (17px) | 1.4 | 700 | |
| Hero subhead | Avenir Next | 1.25rem (20px) | 1.4 | 700 | `silver` on `forest` |
| Standfirst | Barlow | 1.25rem (20px) | 1.5 | 400 | Article and report intros |
| Body | Barlow | 1.0625rem (17px) | 1.6 | 400 | 1.7 for long-form articles |
| Small / secondary | Barlow | 0.875rem (14px) | 1.45 | 400 | Dates, bylines, card summaries |
| Caption / footnote | Barlow | 0.875rem (14px) | 1.5 | 400 | "Figure 1." prefix in 700 |
| Form label | Barlow | 0.875rem (14px) | 1.45 | 700 | Input text is 0.9375rem (15px) |
| Hint / error | Barlow | 0.8125rem (13px) | 1.45 | 400 / 700 | Errors also get an icon |
| Nav link | Barlow | 0.875rem (14px) | 1.6 | 700 | |
| Button | Noto Sans | 0.875rem (14px) | 1.3 | 700 | |
| Pill | Noto Sans | 0.8125rem (13px) | 1.4 | 700 | See rule 9 |
| Chart / table label | Noto Sans | 0.8125–0.875rem (13–14px) | 1.4 | 700 | Tabular figures |
| Column heading | Noto Sans | 0.8125rem (13px) | 1.4 | 700 | Uppercase, +0.08em tracking; footer only |

### Rules for consistent use

1. **One family per element.** Don't mix faces inside a heading, button or label. Body copy is never set in Noto Sans, and headings are never set in Barlow.
2. **Hierarchy comes from size and face, not extra weights.**
   - Use Barlow at 400 for reading and 700 for emphasis and labels.
   - Avoid 500 and 600, which blur the difference between text and labels.
   - Headings are always Avenir Next 700.
3. **Uppercase is reserved for column headings.** Use it with +0.08em letter-spacing, and don't use it for headings, buttons, pills or eyebrows.
4. **Italic is for emphasis only.** That covers the hero lede, inline emphasis and publication titles in references. Barlow is the only face set in italic.
5. **Line length.** Keep running text at or below 65 characters (`max-width: 65ch`). Standfirsts can run to 40rem.
6. **Balanced headings.** Give headings `text-wrap: balance` and paragraphs `text-wrap: pretty` so short last lines don't strand a single word.
7. **Numbers.** Use `font-variant-numeric: tabular-nums` in tables, charts and any column of figures, so digits line up.
8. **Codes and identifiers.** Barlow's capital I, lowercase l and numeral 1 are close, which is common in DIN-style faces. Set identifiers in Noto Sans where a misread matters, such as project IDs, request IDs, ADM codes and dataset keys.
9. **Pill baseline.** Noto Sans sits slightly high in a pill, so pills shift their label down with a `--nudge` value of 0.03em. The vertical padding is `calc(0.17em + var(--nudge))` on top and `calc(0.17em - var(--nudge))` below. Because the padding is in `em`, the adjustment scales with the pill's size.
10. **Other scripts.** Barlow and the base Noto Sans cover Latin scripts. For names or passages in other scripts, add the matching Noto family (for example Noto Sans Arabic) to the stack, so the interface face and the fallback match. Boundary names in GeoQuery often need this.

### Accessibility

- Nothing is set below 13px, and body text is 17px.
- Paragraph line height is 1.5 or more.
- Containers use `min-height` rather than fixed heights. Text stays readable when people increase letter, word or line spacing (WCAG 1.4.12) or zoom to 200%.
- Don't put text in images, including headings in banner graphics. Live text keeps theme, zoom and contrast settings working.

### CSS tokens

```css
:root {
  --font-heading: "Avenir Next", Avenir, "Helvetica Neue", Helvetica, Arial, Roboto, sans-serif;
  --font-body: "Barlow", "DIN Next", "DIN Alternate", "Helvetica Neue", Arial, sans-serif;
  --font-ui: "Noto Sans", "Helvetica Neue", Arial, sans-serif;
}
body { font-family: var(--font-body); font-size: 1.0625rem; line-height: 1.6; }
h1, h2, h3, h4 { font-family: var(--font-heading); font-weight: 700; text-wrap: balance; }
.btn, .badge, .wordmark, th[scope="col"], .chart-label { font-family: var(--font-ui); font-weight: 700; }
```

### In the GeoQuery app

The rules above apply unchanged. This is how they map onto Tailwind and shadcn-svelte.

**Tokens.** In the app, declare the families and the scale in a plain `@theme` block instead of `:root`. Tailwind emits them as the same custom properties and also generates the `font-heading`, `font-body`, `font-ui` and `text-h1` … `text-field` utilities.

```css
@theme {
  --font-heading: "Avenir Next", Avenir, "Helvetica Neue", Helvetica, Arial, Roboto, sans-serif;
  --font-body: "Barlow", "DIN Next", "DIN Alternate", "Helvetica Neue", Arial, sans-serif;
  --font-ui: "Noto Sans", "Helvetica Neue", Arial, sans-serif;
  --font-sans: var(--font-body);                   /* Tailwind and shadcn default */

  --text-xs: 0.8125rem;   --text-xs--line-height: 1.45;   /* 13px floor: hint, pill, chart label */
  --text-sm: 0.875rem;    --text-sm--line-height: 1.45;   /* 14px: small, label, button, nav */
  --text-field: 0.9375rem; --text-field--line-height: 1.45; /* 15px: input text */
  --text-base: 1.0625rem; --text-base--line-height: 1.6;  /* 17px: body */
  --text-h4: 1.0625rem;   --text-h4--line-height: 1.4;
  --text-h3: 1.25rem;     --text-h3--line-height: 1.3;
  --text-standfirst: 1.25rem; --text-standfirst--line-height: 1.5;
  --text-h2: 1.75rem;     --text-h2--line-height: 1.2;
  --text-h1: clamp(1.9rem, 4vw, 2.6rem); --text-h1--line-height: 1.12; --text-h1--letter-spacing: -0.01em;
}
```

Redefining `--text-xs` as 13px brings every existing `text-xs` up to the floor without touching call sites. Leave Tailwind's larger steps (`text-lg` and up) unused, and use the named heading sizes instead.

**Density.** Content pages (help, account, review, requests) set running text at Body (17px). Map panels, sheets, menus and tables are denser, so their running text uses Small (14px). Headings, labels and buttons keep their scale sizes everywhere.

**Faces by component.**

| Element | Face | Weight | Size |
|---|---|---|---|
| Button | `font-ui` | 700 | `text-sm` |
| Header navigation (Docs, Help, Past requests) and step bar | `font-body` | 700 | `text-sm` (nav link) |
| Badge: status and category pills | `font-ui` | 700 | `text-xs`, padded per rule 9 |
| Card title | `font-heading` | 700 | `text-h4` |
| Dialog and Sheet titles | `font-heading` | 700 | `text-h3` |
| Label | `font-body` | 700 | `text-sm` |
| Input, Select trigger | `font-body` | 400 | `text-field` |
| Select and DropdownMenu items, Tooltip | `font-body` | 400 | `text-sm` |
| DropdownMenu label and group heading | `font-body` | 700 | `text-sm` |
| Column headers, legend entries, chart labels, popup field names | `font-ui` | 700 | `text-xs` or `text-sm`, `tabular-nums` |
| Request IDs, ADM codes, dataset keys | `font-ui` | 700 | Size of the surrounding text |
| Index-builder formula field | `font-mono` (system monospace) | 400 | `text-field` |

The formula field is code entry, which the rules above don't cover, so it keeps a monospace face.

**Map labels.** The Protomaps basemap already labels places in Noto Sans, using its Regular, Medium and Italic glyphs. Labels GeoQuery adds to the map through MapLibre use `Noto Sans Medium`, because that glyph set has no 700. Legends and popups are HTML, so they use `font-ui` at 700.

**Loading.** Self-host the two webfonts with Fontsource rather than linking Google Fonts, so pages make no third-party request:

- Import `@fontsource/barlow/400.css`, `400-italic.css` and `700.css`, and `@fontsource/noto-sans/700.css`, in `+layout.svelte`.
- Load nothing else. Avenir Next is a system font and isn't loaded.
- Fontsource splits each weight by Unicode range, so browsers fetch only the scripts a page uses (rule 10).

**shadcn defaults that break the rules.** Edit these in `src/lib/components/ui/`:

- **Weights (rule 2).**
  - Button and Badge `font-medium` → `font-ui font-bold`.
  - Label `font-medium` and DropdownMenu label `font-medium` → `font-bold`.
  - DropdownMenu group heading `font-semibold` → `font-bold`.
  - Card, Dialog and Sheet titles `font-semibold` → `font-heading font-bold`.
  - Drop Input's `font-medium`.
- **Line height.** Card titles, Dialog titles and Label use `leading-none`, which collides when text wraps. Use the scale's line heights.
- **Fixed heights.** Button, Input and Select trigger use fixed heights (`h-8`, `h-9`, `h-10`). Use `min-h-*` so text-spacing overrides don't clip (WCAG 1.4.12).
- **Pill padding.** Badge uses `py-0.5`. Replace it with the rule 9 padding.

---

## 9. Charts with Observable Plot

Observable Plot (ISC license, free for all uses) is the chart library for AidData pages, artifacts and GeoQuery. It draws plain SVG, and most charts are one short declarative call. This section turns §2–§8 into Plot settings. §11 covers how GeoQuery's existing charts move to Plot.

### 9.1 Loading

For standalone pages and artifacts:

```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6.17/dist/plot.umd.min.js"></script>
```

- Load D3 first. Plot's script build reads the global `d3`. The pair is about 477 KB minified.
- Plot comes from jsDelivr because cdnjs doesn't host it.
- Pin exact versions. 0.6.17 (February 14, 2025) is the latest release. Plot's online docs also describe features marked "prerelease"; those aren't in 0.6.17, so don't use them.
- In the GeoQuery app, install the npm package instead (§11).

### 9.2 Colors come from the tokens

- **Never hard-code hex values in chart code.** Plot takes colors as values, so read the tokens from CSS at draw time (`aidTokens()` in §9.7).
- **Redraw when the theme changes:** on the `data-theme` attribute, `prefers-color-scheme` and `prefers-contrast`. `aidChart()` in §9.7 does this.
- **Categorical color:** always set the scale's domain explicitly, in a fixed order, with the range from `--chart-1` onward: `color: {domain: categories, range: t.series.slice(0, categories.length)}`. A category then keeps its color when others are filtered out.
- **At most four series** (§3). Past four, facet into small multiples (`fx` / `fy`) or fold the smallest categories into "Other".
- **Don't use Plot's built-in color schemes** (`observable10`, `tableau10`, `turbo` and so on); they sit outside this palette. For Plot's sequential and diverging schemes (`blues`, `rdbu` and so on), use the §3 ramps instead.
- **Continuous color:** use a §3 ramp as a five-class threshold scale: `color: {type: "threshold", domain: breaks, range: t.seq, unknown: t.noValue}`. `breaks` holds the four inner class boundaries; for `t.div`, place them symmetrically around the midpoint. A label inside a cell uses that step's ink (`t.seqInk`, `t.divInk`).
- **Text never takes a series color.** Chart text uses `--foreground` or `--muted-foreground`; a label inside a filled mark uses that series' `--chart-N-ink`.
- **Gridlines and axes** use `--chart-grid` and `--chart-axis` (§6).
  - `--chart-grid` is the rule color, faint on purpose: 1.4:1 on a light card and 1.7:1 on a dark one. Gridlines are only reference marks, since tick labels and the data table carry the values, so they don't need 3:1. They stay CIEDE2000 7.6 or more from every series color under the colorblind simulation.
  - `--chart-axis` is the control-border color, which clears 3:1 on every surface: `pewter` is 3.7 on card and 3.3 on page; `sage-gray` is 4.3 on a dark card.
  - Under `prefers-contrast: more`, `--chart-axis` steps with the input borders (§5): `forest` in light, `sage` in dark.

### 9.3 Shared settings

| Setting | Value | Follows |
|---|---|---|
| Background | `transparent`; the figure frame supplies the card surface | §2 |
| Chart text | `--muted-foreground`, set as `style.color` (Plot's axes use `currentColor`) | §3 secondary text |
| Labels on marks | `--foreground`, weight 700 | §3 body text, §8 rule 2 |
| Font | `--font-ui` (Noto Sans) 700 at 13px, with tabular figures. Plot sets its own 10px `system-ui` on every SVG, so this must be passed in | §8 chart label |
| Gridlines | `Plot.gridY(ticks, {stroke: --chart-grid, strokeOpacity: 1})`; solid, never dashed; along the value axis only | §2 rules |
| Baseline | `Plot.ruleY([0], {stroke: --chart-axis})` | |
| Ticks | `tickSize: 0`, explicit tick values, `labelArrow: "none"` | |
| Size | Width = container width, redrawn on resize (Plot draws at a fixed width). Height 220–320px | |
| Overflow | `style.overflow: "visible"` so tooltips aren't clipped | |

### 9.4 Marks

| Mark | Settings |
|---|---|
| **Line** | `Plot.lineY`, `strokeWidth: 2`. Add `Plot.dot` on each point: `r: 3.5`, `stroke: --chart-edge`, `strokeWidth: 1.5`. The dots carry the §3 edge, which keeps gold and sky lines visible on light surfaces. |
| **Bar / column** | At most 24px thick: set `insetTop`/`insetBottom` (bars) or `insetLeft`/`insetRight` (columns) from the band size. `stroke: --chart-edge`, `strokeWidth: 1`. Round the data end 4px and keep the baseline end square: `ry2: 4` on columns, `rx2: 4` on horizontal bars. |
| **Stacked bar** | One `barX` mark per category, so only the outer ends round: `rx1: 4` on the first category, `rx2: 4` on the last. Order categories `chart-1` to `chart-4` so `chart-2` and `chart-4` never touch. |
| **Grouped columns** | One facet per group (`fx`), with the series on `x` inside it. Plot doesn't rotate crowded labels by itself, so set `fx.tickRotate: -35` (and a larger `marginBottom`) when a facet is narrower than about 72px. |
| **Points** | `Plot.dot`, `r: 5`, `stroke: --chart-edge`, `strokeWidth: 1.5`. Pair color with shape: `symbol: {domain: categories, range: ["circle", "diamond", "square", "triangle"], legend: true}`. Plot then draws one legend showing both. |

### 9.5 Labels, legends and tooltips

- **Legend:** for two or more series, set `legend: true` on the color scale (or on the symbol scale for points). A single series gets no legend; the title names it. Plot puts the legend above the SVG as HTML, so style it with the CSS in §9.7.
- **Direct labels by chart type:**
  - **Bars and stacked segments:** label each segment that is at least 34px wide, centered, in its `--chart-N-ink`. Narrower segments rely on the tooltip and table.
  - **Lines:** label the end value only, with `Plot.text` and `Plot.selectLast` (`dx: 8`, `textAnchor: "start"`, leave about 44px of right margin).
  - **Points:** no per-point labels. Shape, legend, tooltip and table carry identity and value.
- **Number formats:** compact on axes and labels (`2K`, `10.4K`, `$200M`, `25%`); full values with thousands separators in tooltips and tables.
- **Tooltips:**
  - Use one `Plot.tip` mark per chart, driven by `Plot.pointer` or `Plot.pointerX`, with `fill: --card`, `stroke: --chart-axis`, `fontFamily: --font-ui`, `fontSize: 13`.
  - Don't set `tip: true` on several marks. In 0.6.17 each mark draws its own tip, so several can appear at once.
  - For a line chart, build one row per x value that lists every series, tip that, and add `Plot.ruleX(…, Plot.pointerX(…))` in `--chart-axis` as the crosshair.

### 9.6 Figures and accessibility

- **Frame:** put each chart in the figure pattern: a `.fig-frame` card surface (10px radius, card shadow, 1.25rem padding) with a `figcaption` below, starting "**Figure N.**" (§8 caption style).
- **ARIA:** every plot sets `ariaLabel` (a short name) and `ariaDescription` (the finding, in a sentence or two). Plot already hides tick marks and gridlines from screen readers.
- **Data table:** every chart has a twin table in the standard table style, either directly below or in a `<details>` labeled "Show the numbers". Plot has no keyboard navigation, so the table is how keyboard and screen-reader users reach exact values.
- **§5 modes:**
  - Redraw when `prefers-contrast` changes so the stepped tokens apply.
  - Under forced colors, keep `forced-color-adjust: none` on the chart and its legend so the colors keep their meaning.
  - Plot doesn't animate, so reduced motion needs nothing.

### 9.7 Reference implementation

**CSS**, alongside the page's figure styles:

```css
.aid-plot { overflow: visible; }            /* chart frames: let tooltips extend past the edge */
.aid-plot figure { margin: 0; }
.aid-plot figure > div {                    /* Plot's legend, rendered as HTML above the SVG */
  font-family: var(--font-ui) !important;
  font-size: 13px !important;
  font-weight: 700;
  color: var(--foreground);
  margin-bottom: 6px !important;
}
.aid-plot svg { display: block; font-variant-numeric: tabular-nums; }
@media (forced-colors: active) {
  .aid-plot svg, .aid-plot figure > div { forced-color-adjust: none; }
}
```

**Helpers**, shared by every chart on the page:

```js
// Tokens, read fresh on every draw so both themes and contrast modes apply
function aidTokens() {
  const cs = getComputedStyle(document.documentElement);
  const v = (name) => cs.getPropertyValue(name).trim();
  return {
    fg: v("--foreground"), muted: v("--muted-foreground"), card: v("--card"),
    grid: v("--chart-grid"), axis: v("--chart-axis"), edge: v("--chart-edge"),
    font: v("--font-ui"),
    series: [1, 2, 3, 4].map((i) => v(`--chart-${i}`)),
    ink: [1, 2, 3, 4].map((i) => v(`--chart-${i}-ink`)),
    seq: [1, 2, 3, 4, 5].map((i) => v(`--seq-${i}`)),
    seqInk: [1, 2, 3, 4, 5].map((i) => v(`--seq-${i}-ink`)),
    div: [1, 2, 3, 4, 5].map((i) => v(`--div-${i}`)),
    divInk: [1, 2, 3, 4, 5].map((i) => v(`--div-${i}-ink`)),
    noValue: v("--no-value"),
  };
}

// Settings every plot starts from (§9.3)
function aidBase(t, width, height = 260) {
  return {
    width, height,
    style: { background: "transparent", color: t.muted, fontFamily: t.font, fontSize: "13px", fontWeight: 700, overflow: "visible" },
  };
}

// Tooltip box (§9.5)
function aidTip(t) {
  return { fill: t.card, stroke: t.axis, fontFamily: t.font, fontSize: 13 };
}

// 2000 → "2K", 10400 → "10.4K", 200000000 → "200M"
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format;

// Draw into a container; redraw on theme, contrast and width changes.
// Returns a cleanup function for pages that remove charts.
function aidChart(el, draw) {
  let width = 0;
  const render = () => {
    width = el.clientWidth;
    el.replaceChildren(draw(aidTokens(), width));
  };
  render();
  const themeObserver = new MutationObserver(render);
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const queries = ["(prefers-color-scheme: dark)", "(prefers-contrast: more)"].map((q) => matchMedia(q));
  for (const mq of queries) mq.addEventListener("change", render);
  const sizeObserver = new ResizeObserver(() => { if (Math.abs(el.clientWidth - width) > 4) render(); });
  sizeObserver.observe(el);
  return () => {
    themeObserver.disconnect();
    sizeObserver.disconnect();
    for (const mq of queries) mq.removeEventListener("change", render);
  };
}
```

**Figure markup:**

```html
<figure class="fig" aria-labelledby="fig1-cap">
  <div class="fig-frame aid-plot" id="fig-trend"></div>
  <figcaption id="fig1-cap"><b>Figure 1.</b> Locations geocoded per year in three portfolios.</figcaption>
</figure>
<details class="numbers">
  <summary>Show the numbers</summary>
  <!-- data table in the standard table style -->
</details>
```

**Line chart** with end labels and a shared tooltip. `rows` holds one object per point: `{series, year, value}`.

```js
aidChart(document.querySelector("#fig-trend"), (t, width) => {
  const series = ["Portfolio A", "Portfolio B", "Portfolio C"];
  const yTicks = [0, 2000, 4000, 6000, 8000, 10000, 12000];
  // One row per year listing every series, for the shared tooltip
  const byYear = d3.groups(rows, (d) => d.year).map(([year, ds]) => ({
    year,
    top: d3.max(ds, (d) => d.value),
    text: [year, ...ds.map((d) => `${d.series}: ${d.value.toLocaleString("en-US")}`)].join("\n"),
  }));
  return Plot.plot({
    ...aidBase(t, width),
    marginTop: 22, marginRight: 44, marginLeft: 44,
    ariaLabel: "Locations geocoded per year",
    ariaDescription: "All three portfolios grew between 2015 and 2024, with a dip in 2020.",
    x: { ticks: width < 420 ? 4 : 10, tickFormat: "d", tickSize: 0, label: null, inset: 8 },
    y: { domain: [0, 12000], ticks: yTicks, tickFormat: compact, tickSize: 0, label: "Locations geocoded", labelArrow: "none" },
    color: { domain: series, range: t.series.slice(0, series.length), legend: true },
    marks: [
      Plot.gridY(yTicks.slice(1), { stroke: t.grid, strokeOpacity: 1 }),
      Plot.ruleY([0], { stroke: t.axis }),
      Plot.lineY(rows, { x: "year", y: "value", stroke: "series", strokeWidth: 2 }),
      Plot.dot(rows, { x: "year", y: "value", fill: "series", r: 3.5, stroke: t.edge, strokeWidth: 1.5 }),
      Plot.text(rows, Plot.selectLast({
        x: "year", y: "value", z: "series", text: (d) => compact(d.value),
        dx: 8, textAnchor: "start", fill: t.fg, fontWeight: 700,
      })),
      Plot.ruleX(byYear, Plot.pointerX({ x: "year", stroke: t.axis })),
      Plot.tip(byYear, Plot.pointerX({ x: "year", y: "top", title: "text", ...aidTip(t) })),
    ],
  });
});
```

**Stacked bar** of shares that sum to 100, with rounded outer ends and labels that only appear where they fit. `portfolios` holds `{name, shares: [exact, near, district, region]}`.

```js
aidChart(document.querySelector("#fig-precision"), (t, width) => {
  const levels = ["Exact point", "Near", "District only", "Region only"];
  const height = 220, marginTop = 6, marginRight = 12, marginBottom = 26, marginLeft = 88;
  const plotWidth = width - marginLeft - marginRight;
  const step = (height - marginTop - marginBottom) / portfolios.length;
  const inset = Math.max(0, (step - 24) / 2);              // 24px bars

  // Each segment's start, end and midpoint
  const segs = portfolios.flatMap((p) => {
    let x1 = 0;
    return p.shares.map((share, i) => {
      const seg = { portfolio: p.name, level: levels[i], i, share, x1, x2: x1 + share, mid: x1 + share / 2 };
      x1 += share;
      return seg;
    });
  });

  // One bar mark per level, so only the stack's outer ends are rounded
  const bars = levels.map((level, i) => Plot.barX(segs.filter((d) => d.i === i), {
    x1: "x1", x2: "x2", y: "portfolio", fill: "level",
    stroke: t.edge, strokeWidth: 1, insetTop: inset, insetBottom: inset,
    ...(i === 0 && { rx1: 4 }),
    ...(i === levels.length - 1 && { rx2: 4 }),
  }));

  // Labels in each level's ink, only where the segment is at least 34px wide
  const labels = levels.map((level, i) => Plot.text(
    segs.filter((d) => d.i === i && (d.share / 100) * plotWidth >= 34),
    { x: "mid", y: "portfolio", text: (d) => `${d.share}%`, fill: t.ink[i], fontWeight: 700 },
  ));

  return Plot.plot({
    ...aidBase(t, width, height),
    marginTop, marginRight, marginBottom, marginLeft,
    ariaLabel: "Location precision by portfolio",
    ariaDescription: "Portfolio A has the most exact locations; four in ten of Portfolio C's are known only to the region.",
    x: { domain: [0, 100], ticks: [0, 25, 50, 75, 100], tickFormat: (d) => `${d}%`, tickSize: 0, label: null },
    y: { domain: portfolios.map((p) => p.name), padding: 0, tickSize: 0, label: null },
    color: { domain: levels, range: t.series, legend: true },
    marks: [
      Plot.gridX([25, 50, 75, 100], { stroke: t.grid, strokeOpacity: 1 }),
      ...bars,
      ...labels,
      Plot.tip(segs, Plot.pointer({
        x: "mid", y: "portfolio",
        title: (d) => `${d.portfolio}\n${d.level}: ${d.share}%`,
        ...aidTip(t),
      })),
    ],
  });
});
```

### 9.8 Checklist

- Colors come from the tokens, the color domain is set explicitly, and there are no more than four series. Continuous color uses a §3 ramp in five classes.
- Gridlines are solid `--chart-grid` hairlines, the baseline is `--chart-axis`, and tick marks are off.
- Every mark has its `--chart-edge` edge; bars are at most 24px thick with a 4px rounded data end.
- Chart text is Noto Sans 700 at 13px or larger, labels follow §9.5, and no text uses a series color.
- There is one tooltip mark, styled with `aidTip`.
- The plot has `ariaLabel` and `ariaDescription`, sits in a captioned figure frame, and has a data table.
- The chart redraws on theme, contrast and width changes, and has been checked in both themes.

---

## 10. Components: which to use when

### Installed components

| Component | Use for | Don't use for |
|---|---|---|
| Button | Every clickable action, and links styled as actions (`href`) | — |
| Card | A raised group of related content or controls | Wrapping a single line of text |
| Input + Label | Free text | Choosing from known values |
| Checkbox | Independent on/off choices, multi-select lists | Mutually exclusive choices |
| Select | One choice from a short, known list (about 15 or fewer) | Long or searchable lists |
| DropdownMenu | Actions under one trigger: account menu, row overflow | Choosing a value |
| Collapsible | Optional detail inside a panel, such as cart item details | Hiding required fields |
| Sheet | Supporting content beside the map that keeps the map visible: request cart, help | Blocking decisions |
| Dialog | A blocking decision, a destructive confirmation, the one-time welcome | Content people need to read alongside the map |
| Tooltip | Naming an icon-only control; defining a term | The only place essential information appears |
| Badge | Status pills and category pills | Buttons |
| ScrollArea | Panels with their own scroll inside a fixed frame | Whole pages |
| Separator | Between groups of controls inside one card, panel or menu | Between page sections (§2: alternate page and band) |
| Avatar | The signed-in user | — |

### Add from the registry when needed

Add these with `bunx shadcn-svelte@latest add <name>` from `frontend/`, then apply §7 before first use. Don't hand-build them.

- **Alert** for inline notices. It replaces today's hand-built `bg-green-50` and `text-amber-700` boxes.
- **Sonner** (toasts) to confirm background actions: request submitted, link copied.
- **Skeleton** for loading content that takes up layout.
- **Switch** for settings that apply immediately; §3 already defines its colors.
- **Table** for the request list and dataset tables.
- **Command + Popover** for a combobox. GeographySearch could move to it.
- **Tabs** and **Progress** when a page needs them.

### Buttons

| Variant | Use | Examples |
|---|---|---|
| `default` | The one action that moves the task forward. At most one per panel, card or dialog | Review request, Submit, Get started |
| `outline` | Secondary actions beside a primary | Add another boundary, Cancel |
| `ghost` | Toolbars, header navigation, map controls, row actions, icon buttons | Help, Zoom in, Remove item |
| `link` | Actions inside a sentence | "Read the methodology" |
| `destructive` | Irreversible deletion, inside a confirmation Dialog | Delete request |
| `secondary` | Not used; `outline` covers secondary actions | — |

Sizes:

- `default`: forms, dialogs and page content.
- `sm`: floating map panels, cards and dense lists.
- `xs`: table rows only.
- `lg`: the single call to action in a dialog or empty state.
- `icon` and `icon-sm`: map controls and toolbars, always with `aria-label`.

Reversible removal, such as taking an item out of the request, is a ghost icon button, not `destructive`.

**Never hand-roll a button or field.** Use `<Button href>` for links that look like buttons. These are hand-rolled today:

- SupportBanner's "Contact our partnerships team" link
- The StatusBanner and SupportBanner dismiss buttons
- CartPanel's remove button
- The step bar's "Map and visualize data" link
- The viz pages' `.viz-btn-primary`, `.viz-select` and `.viz-input`

### Forms

- Every field has a visible Label. A placeholder is not a label; CartPanel's "Selection Name" field has only a placeholder.
- Group related checkboxes in a `fieldset` with a `legend`.
- Show an error as `aria-invalid` on the field plus a message below it in `text-destructive`, linked with `aria-describedby`. The message says how to fix the problem.
- If a submit button is disabled, nearby text says why.
- Inside a card, fields use the page tone as their fill (§2).

### Icons

- Use Lucide only.
- Sizes: 16px inside buttons and inline with text, 20px standalone, 24px in dialog feature lists.
- Every icon-only control has an `aria-label`. When a label hides on small screens, use `sr-only sm:not-sr-only`, not `hidden sm:inline`. `hidden` is `display: none`, which also removes the accessible name, so today the header's Docs, Help and Past Requests buttons have no name on phones.

---

## 11. Interface patterns

### Layout

- **Shell:** status banner (when enabled), then the sticky header (80px), then the step bar (48px, workflow pages only), then content.
- **Map workspace** (`/`, `/viz/*`): the map fills the remaining viewport and acts as the page surface; don't alternate page and band here.
  - Task panels float 16px from the left edge, 384px wide (`w-96`). They stack with 8px gaps and scroll inside themselves.
  - Map controls sit top right.
  - Floating panels use the card surface and `shadow-card`.
- **Content pages** (requests, account, review, stats): a centered column on the page background. Use `max-w-2xl` for forms and single records, and `max-w-5xl` for tables and dashboards.
- **Spacing:**
  - 8px between related controls (`gap-2`).
  - 16px inside panels (`p-4`).
  - 24px between cards and inside content cards (`gap-6`, `p-6`).
  - Bands get at least 48px vertical padding.

### The request workflow

- The three steps carry the same names in the step bar, page headings and buttons: select boundary, customize datasets, review request.
- Each step's primary action sits at the bottom of its panel. It is the only `default` button there.
- Anything selected on the map can also be reached without the map, through GeographySearch or a list, so the workflow works from the keyboard.

### Maps

**Boundaries.** `lib/utils/boundaryStyle.ts` cycles eight Tailwind hues, against §3.

- Use `chart-1` to `chart-4` in order.
- Beyond four collections, distinguish by line width (admin level) and chip labels rather than more colors.
- `gold` and `sky` lines are under 3:1 on the light basemap (`gold` is 1.8 on white), so draw each colored line over a `forest` casing 2px wider. This is a proposal; check it on the basemap before adopting it.

**Feature states.**

- Default fill is 15% opacity, hover 35% and selected 50%.
- A selected feature also gets a heavier outline (width plus 1.5px), so selection doesn't rest on opacity alone.
- Shapes being drawn or edited use a dashed `--ring` line, not today's orange (`#f97316`).

**Choropleth ramps** (`lib/viz.ts`):

- Default to the §3 `seq` ramp, and offer `div` when the data has a meaningful midpoint. Today both viz pages default to `YlOrRd`.
- Keep the other ColorBrewer ramps as options people can pick.
- Retire `RdYlGn`. Under the colorblind simulation described at the top of this document its second and fourth steps are CIEDE2000 2.0 apart, so they read as the same. `RdBu`, `PuOr` and `BrBG` keep their ends at least 21.8 apart.
- Use a diverging ramp only around a meaningful midpoint, and name the midpoint in the legend.

**Gaps.** GeoQuery has two kinds of gap, and they mean different things.

- **No value:** the extract ran and the source has nothing there. Fill with `pewter`. Under the colorblind simulation `pewter` stays at least CIEDE2000 10.2 from every step of every ramp. Today's `#cbd5e1` is 2.2 from a `Blues` step.
- **Not processed:** no extract has run there yet. Use a `pewter` diagonal hatch over the page tone.
- Never draw either gap as zero.

**Legends and popups.**

- A legend shows the minimum, maximum, unit and data year, plus a swatch for each gap type present.
- A popup shows the feature name, the value with its unit, and the year.

### Charts

Build GeoQuery's charts with Observable Plot, following §9. The seven hand-built SVG charts in `lib/components/viz/charts/` move to it.

- **Install, don't link.** Add `@observablehq/plot`, pinned to exactly `0.6.17`, with bun. Its ES module build imports D3 itself, so the app needs no script tags. Adding it needs `docker compose up --build frontend`.
- **One wrapper component.** A `PlotFigure.svelte` renders the §9.6 figure: frame, caption and "Show the numbers" table.
  - It calls `aidChart` from an `$effect` and returns `aidChart`'s cleanup function, so the observers disconnect when the chart unmounts.
  - Each chart component supplies only its draw function and its table rows.
- **Chart types:**

| Component | Plot mark | Notes |
|---|---|---|
| TimeSeries | Line: `lineY` plus `dot` | |
| RankedBar, BinaryBar | Bar: `barX` | |
| Histogram | `rectY` with `binX` | Single series, no legend. Bins are contiguous, so the 24px thickness cap doesn't apply; separate bins by 1px (`inset: 0.5`). This is a proposal |
| BoxPlot | `boxY` | The box follows the Bar settings; outliers follow the Points settings |
| Scatter | Points: `dot` with `symbol` | Today it colors up to six collections (`FC_COLORS`). Cap at four per §9.2 |
| CorrelationMatrix | `cell` | §3 `div` ramp with thresholds at −0.6, −0.2, 0.2 and 0.6, so the middle class is "little or no correlation". Coefficients labeled in each step's ink |

- **Reference lines.** A mean or median is a `Plot.ruleX` or `Plot.ruleY` in `--foreground`, dashed, with a direct label. Today it is red (`#ef4444`), which reads as an error.
- **Map export.** `exportMapImage()` in `routes/viz/` draws the legend onto a canvas, and canvas doesn't read CSS. Resolve the tokens with `getComputedStyle`, as `aidTokens` does, and set `ctx.font` to `700 13px` followed by the `--font-ui` stack.

### Status

One vocabulary across request lists, account badges and anything else with state. Always pair the color with an icon and a word.

| Meaning | Request statuses | Light pill | Dark pill | Icon |
|---|---|---|---|---|
| Done | completed, verified | `emerald-dark` on `alert-bg` (6.2) | `sage` on `forest-muted` (9.5) | CircleCheck |
| In progress or pending | preparing, processing, unverified | `gold-text` on `warning-bg` (6.1) | `gold` on `forest-muted` (8.1) | Clock |
| Failed | error | `danger` on `danger-bg` (6.0) | `#ff9aa6` on `forest-muted` (7.1) | CircleAlert |
| Neutral | queued, anything else | `granite` on `haze` (6.2) | `silver` on `forest-muted` (10.3) | Circle |

The pale fills are nearly invisible on a white card (`warning-bg` is 1.1:1), so the text and icon carry the meaning; the fill only reinforces it.

**Site-wide banner** (`StatusBanner`):

| Type | Background | Text | Contrast | Today |
|---|---|---|---|---|
| Info | `forest` | `cream` | 16.2 | `blue-600` with white, 5.2 |
| Warning | `gold` | `forest` | 9.5 | `amber-500` with white, 2.2 (fails) |
| Error | `danger` | `white` | 6.9 | `red-600` with white, 4.8 |

**Feedback by situation:**

| Situation | Pattern |
|---|---|
| Wait under about 1 second | Show nothing |
| Small async check | Inline spinner plus text in `muted-foreground`, inside `role="status"`. The existing "Checking coverage…" is the model |
| Content still loading | Skeleton in the shape of the content |
| Long job of known length | Progress |
| Background action succeeded | Toast |
| Something needs attention in place | Alert in the section it concerns |
| Irreversible action | Confirmation Dialog. Buttons name the verb ("Delete request" / "Cancel"), never "OK" |

**Empty states** say what is empty and offer the next action as a button. Prefer "Your request is empty. Select a boundary and add datasets to start." over "Your Request is Empty".

**Errors** say what happened, why if known, and what to do next. Keep whatever the user entered. Never show raw exception text.

### Writing in the interface

- Use sentence case for headings, buttons, labels, pills and step names (see §12). The app currently uses Title Case: "Review Request", "Past Requests", "1. Select Boundary".
- Buttons are a verb plus an object: "Add to request", "Download CSV".
- Use one name for one thing everywhere. A request is a "request" in the header, sheet, review page and emails.
- Numbers get thousands separators, units and the data year. Write dates as September 24, 2026.

### Accessibility checklist

In addition to §4 and §5:

- Every control is reachable and operable from the keyboard, with a visible focus ring (§7).
- Overlays close with Escape and return focus to their trigger. bits-ui does this; don't override it.
- Every icon-only control has an accessible name at every breakpoint (§10).
- Touch targets are at least 24×24px. The banner dismiss buttons are 20px and 22px today.
- Color never carries meaning alone: status pills have icons and words, map selection has a heavier outline, and chart series have direct labels.
