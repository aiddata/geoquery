---
name: style_guide
title: AidData style guide for artifacts
description: Structure, voice, design tokens, chart rules and evidence requirements for an interactive page or artifact built from GeoQuery data.
when: before you build an artifact, page, dashboard or chart for a user
---

# AidData style guide for artifacts

Apply this guide to anything visual you build from GeoQuery data: a single-file
HTML page, a dashboard, a map, a chart, a slide. Read it before you start. Its
rules shape structure and content, not only appearance, so applying them
afterwards means rebuilding.

Apply it in full when the user is working on AidData or GeoQuery material.
Apply the voice, evidence and chart rules anyway when they are not: those are
about being accurate, not about branding. If the user asks for a different look,
follow the user.

## What AidData sounds like

AidData is a research lab at William & Mary. Its work answers one question: who
is doing what, where, for whom, and to what effect. Frame every artifact as an
answer to some version of that question.

Reproduce the house pattern:

- A heading is followed by an italic one-line descriptor. Section headings carry
  the same pattern.
- Content carries a type label: Interactive, Methodology, Policy Brief, Working
  Paper, Story Map, Blog.
- A tool tile shows the domain, an external-link arrow, and one line with a
  count, for example "31,750 loans and grants across 200 countries".
- Photographs carry credit and license lines.
- The footer is a dark band carrying the William & Mary affiliation.

## Voice

Write like a research lab. Plain declarative sentences, evidence first, one
number with every claim.

- Use sentence case for headings and card titles.
- Lead with the finding, then its number, unit and data year.
- Name the data year of every layer. Write dates in prose as September 24, 2026.
- Say what is simulated, estimated or assumed in the sentence where it appears,
  not only in a footnote.
- Define acronyms on first use, for example LGA, UCDP and IBRA.
- Keep sentences under 25 words and paragraphs to three sentences.
- Do not use em dashes, hype words (cutting-edge, seamless, leverage, unlock),
  or "it is not X, it is Y" constructions.

## Page anatomy

Build every page in this order, top to bottom. Omit a part only when it does not
apply, never to save effort.

1. **Skip link and slim header.** A text label such as "AidData · GeoQuery".
   Leave a slot for the official logo.
2. **Title block.** A content-type label, a sentence-case H1, an italic one-line
   descriptor, and at most one primary button.
3. **Notice band.** A short banner whenever any data is simulated or
   provisional.
4. **Question this answers.** One line in the frame: where, for whom, with what
   effect.
5. **Main exhibit.** The map or chart first, controls above it, one sentence of
   note below it.
6. **Sections.** Each with an H2 and an italic one-line descriptor, ordered
   result, evidence, method, limits.
7. **Data used.** Tiles with the source name, an external-link arrow, and one
   line with a count.
8. **Footer.** A dark band with the affiliation line, sources and license
   status, the publish date, and a contact.

## Design tokens

Use these values. They are this guide's defaults rather than a brand-kit export,
so if the user supplies official AidData values prefer theirs and say that you
did. Keep every token in one `:root` block at the top of the stylesheet, so the
page can be re-skinned by replacing that block alone.

```css
:root{
  /* brand: William & Mary green and gold */
  --brand:#115740; --brand-deep:#0B3A2B; --accent:#B9975B;
  /* neutrals */
  --ink:#1B2A2C; --muted:#5B6B6C; --paper:#F6F7F4; --panel:#FFFFFF; --rule:#D9DFD8; --empty:#E4E7E3;
  /* status */
  --alert:#A8432B; --notice-bg:#FFF3D6; --notice-ink:#6A4A0E; --footer-bg:#0F2A22;
  /* data ramps (5 steps, light to dark) */
  --seq:#EEF3EC,#BBD3C5,#6FA58A,#2E7A5D,#115740;      /* magnitude, context layers */
  --concern:#FFF1D6,#F6C071,#E08A3C,#B9472A,#6E1F1F;  /* darker means worse */
  --diverge:#9A6A1E,#D9B56B,#F2EFE6,#8DBFC4,#1F5D73;  /* only around a meaningful zero */
}
```

**Type.** Headings in Source Serif 4 at weight 600. Body in Public Sans at 400,
500 and 600. Fall back to Georgia and system-ui. Sizes: H1 clamp(26px, 3.6vw,
38px), H2 21px, body 15px, notes 13px, chart ticks 11px.

**Layout.** Maximum width 1180px, an 8px spacing grid, 6px corner radius, 1px
rules, white cards on a pale paper background.

**Dark mode.** Redefine the same tokens under `prefers-color-scheme: dark` and
under a `data-theme="dark"` attribute.

## Maps and charts

Every exhibit must be readable with the surrounding text removed. State what it
shows, the unit, the year, and which direction is worse.

- Use real boundaries. Show a labelled tile grid only while they load.
- Use the sequential ramp for magnitude, the concern ramp where darker means
  worse, and the diverging ramp only around a meaningful zero. Never use a
  rainbow scale.
- Every legend shows the minimum, the maximum, the unit, and a "no value"
  swatch.
- Use at most six colors on a categorical map, each named in the legend.
- Outline the sampled or selected units, and give the selected unit a heavier
  stroke.
- Show uncertainty beside every estimate, as a range or a flag. Where the true
  value is known, plot estimate against truth.
- Label axes with units. Start rate axes at zero unless the range itself is the
  point.
- Give every tooltip the name, the value with its unit, and the year.
- Never let color carry meaning alone. Add labels, shapes or direct labels.
- Add one note per layer with its source, year and method, in one or two
  sentences.

## Evidence and honesty

A page earns trust by showing what is real, what is invented, and where it could
fail. These rules are not optional polish.

- Banner any page that uses simulated data, and list what is real and what is
  simulated.
- State what a simulation built in. Show at least one check that could have
  failed, such as cross-validation, a holdout, or redrawn samples.
- Report weak results beside strong ones, and say what the page does not show.
- List data problems in the Limits section: missing cells, layers that returned
  zeros, unit gaps, coarse cells.
- Offer a download for any derived number the page reports.

GeoQuery data carries two distinct kinds of gap, and they are not the same
finding. `unprocessed_features` means no extract has been run there yet, and an
export would fill it. `no_value_features` means the extract ran and the source
has nothing there, usually a feature smaller than a pixel or outside the data's
extent. Say which one a blank is. Never render either as zero.

## Attribution

Every GeoQuery result carries an `attribution` object. Carry it through to the
page. Do not summarise data while dropping where it came from.

- Give every layer its source, license and citation from `attribution`.
- Where the license is not recorded, write "license not recorded; check the
  source before republishing". Do not leave it blank, and do not guess.
- Call `get_citations` for a formatted reference list rather than assembling one
  by hand.
- Cite GeoQuery itself: Goodman, BenYishay, Lv and Runfola (2019), Computers &
  Geosciences 122, 103-112.
- Where a selection was truncated, link the `viz_url` from the result so the
  reader can open the full selection in GeoQuery.

## Interaction and accessibility

Every control works from the keyboard, and every exhibit has a text equivalent.

- Show a visible 2px focus ring on every control, row and link.
- Give each SVG exhibit `role="img"` and an `aria-label`. Use real table
  headers.
- Keep text contrast at 4.5:1 or better.
- Give every hover tooltip a click or focus equivalent.
- Respect dark mode and the phone safe-area insets.
- Let a wide table scroll inside its own container.
- Keep chart text at 11px or larger, and notes at 13px or larger.

## Building the file

Produce one self-contained HTML file that works without a sign-in.

- Load scripts only from cdnjs.cloudflare.com. Load fonts from Google Fonts with
  fallbacks.
- Do not depend on browser storage, and do not call another site at runtime.
- Embed the data. For boundaries, embed simplified geometry of about 100 m:
  fetch it once with `get_data(format="geojson")`, then embed it.
- Show "no value" for missing data. Never plot a missing value as zero.
- Name the file for what it shows, and publish updates to the same link.
- Test before handing it over: no console errors, every dropdown option renders,
  and every point falls inside its polygon.

## Before you return the page

Check each of these, and fix what fails rather than noting it.

- Every claim carries a number, a unit and a data year.
- Every exhibit states what it shows and which direction is worse.
- Every legend has a "no value" swatch, and no blank is drawn as zero.
- Every layer has a source, a license and a citation, with unrecorded licenses
  named as unrecorded.
- Simulated or partial data is bannered at the top, not buried.
- The page is keyboard-navigable and readable in dark mode.
- No em dashes and no hype words.
