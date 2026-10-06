---
name: style_guide
title: AidData style guide for artifacts
description: Structure, voice, design tokens, chart rules and evidence requirements for an interactive page or artifact built from GeoQuery data.
when: before you build an artifact, page, dashboard or chart for a user
---

# AidData-style guide for artifacts (draft v0.1)

Use this guide when you ask Claude to build an interactive page for AidData work. It sets structure, voice, design tokens and evidence rules, and it marks which values still need checking against the AidData brand kit.

## Status: confirmed and provisional

Structure and voice below come from the [aiddata.org homepage](https://www.aiddata.org); fonts and spacing are provisional because the site's stylesheet could not be read, and the colors are accepted.

**Confirmed from the homepage text**

- AidData presents itself as a research lab at William & Mary and frames its work as one question: who is doing what, where, for whom, and to what effect.
- Headlines are followed by an italic one-line descriptor. Section headings carry the same pattern.
- Content cards carry a type label: Blog, Policy Brief, Methodology, Working Paper, Story Map, Interactive.
- Tool tiles show the domain, an external-link arrow and one line with a count, for example 31,750 loans and grants across 200 countries.
- Photos carry credit and license lines. The footer holds the William & Mary crest on a dark band.

**Not confirmed**

- Font families and spacing. The colors are accepted as the William & Mary green and gold. The sandbox cannot reach aiddata.org or its stylesheet host.
- To confirm them, paste the values from the AidData brand kit, or allow aiddata.org and cdn.prod.website-files.com in network settings so Claude can read the live CSS.

## Voice and writing rules

Write like a research lab: plain declarative sentences, evidence first, one number with every claim.

- Use sentence case for headings and card titles.
- Lead with the finding, then its number, unit and data year.
- Frame each artifact around where, for whom and with what effect.
- Do not use em dashes, hype words (cutting-edge, seamless, leverage, unlock) or "it is not X, it is Y" constructions.
- Define acronyms on first use, for example LGA, UCDP and IBRA.
- Write dates in prose as September 24, 2026. Name the data year of every layer.
- Say what is simulated, estimated or assumed in the sentence where it appears.
- Keep sentences under 25 words and paragraphs to three sentences.

## Page anatomy

Every demo or interactive page follows the same order, top to bottom.

1. **Skip link and slim header.** A text label such as "AidData · GeoQuery". Leave a slot for the official logo.
2. **Title block.** A content-type label (Interactive, Methodology, Policy brief), a sentence-case H1, an italic one-line descriptor and at most one primary button.
3. **Notice band.** A short banner when any data is simulated or provisional.
4. **Question this answers.** One line using the frame: where, for whom, with what effect.
5. **Main exhibit.** The map or chart first, controls above it, one sentence of note below it.
6. **Sections.** Each has an H2 and an italic one-line descriptor. Order them as result, evidence, method, limits.
7. **Data used.** Tiles with the source name, an external-link arrow and one line with a count.
8. **Footer.** A dark band with the affiliation line (a research lab at William & Mary), sources and license status, the publish date and a contact.

## Design tokens

These values are stand-ins. Keep them in one `:root` block so a page can be re-skinned by replacing that block once.

```css
:root{
  /* brand: William & Mary green and gold, accepted */
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

**Type.** Headings in Source Serif 4 at weight 600. Body in Public Sans at 400, 500 and 600. Fall back to Georgia and system-ui. Sizes: H1 clamp(26px, 3.6vw, 38px), H2 21px, body 15px, notes 13px, chart ticks 11px.

**Layout.** Maximum width 1180px, an 8px spacing grid, 6px corner radius, 1px rules, white cards on a pale paper background.

**Dark mode.** Redefine the same tokens under `prefers-color-scheme: dark` and under a `data-theme="dark"` attribute.

## Maps and charts

Maps and charts must be readable without the text around them: every one states what it shows, the unit, the year and which direction is worse.

- Use real boundaries. Show a labelled tile grid only while boundaries load.
- Use the sequential ramp for magnitude and the concern ramp where darker means worse. Use the diverging ramp only around a meaningful zero. Do not use rainbow scales.
- Every legend shows the minimum, the maximum, the unit and a "no value" swatch.
- Categorical maps use at most six colors, each named in the legend.
- Outline the sampled or selected units. Give the selected unit a heavier stroke.
- Show uncertainty beside every estimate, as a range or a flag. Where the true value is known, plot estimate against truth.
- Label axes with units. Start rate axes at zero unless the range itself is the point.
- Tooltips give the name, the value with its unit and the year.
- Never let color carry meaning alone. Add labels, shapes or direct labels.
- Add one note per layer with its source, year and method in one or two sentences.

## Evidence, simulated data and attribution

A demo earns trust by showing what is real, what is invented and where it could fail.

- Put a banner at the top of any page that uses simulated data. List what is real and what is simulated.
- State what the simulation built in. Show at least one check that could fail, such as cross-validation, a holdout or redrawn samples.
- Report weak results next to strong ones, and say what the page does not show.
- Give every data layer a citation and its license status from the GeoQuery export documentation. If no license is recorded, write "license not recorded; check the source before republishing".
- Keep the GeoQuery citation: Goodman, BenYishay, Lv and Runfola (2019), Computers & Geosciences 122, 103-112.
- List data issues in a Limits section: missing cells, layers that returned zeros, unit gaps and coarse cells.
- Offer a download for any derived number the page reports.

## Interaction and accessibility

Every control works from the keyboard, and every exhibit has a text equivalent.

- Show a visible 2px focus ring on every control, row and link.
- Give each SVG exhibit `role="img"` and an `aria-label`. Use real table headers.
- Keep text contrast at 4.5:1 or better.
- Give every hover tooltip a click or focus equivalent.
- Respect dark mode and the phone safe-area insets.
- Let wide tables scroll inside their own container.
- Keep chart text at 11px or larger and notes at 13px or larger.

## Technical checklist for single-file artifacts

Build one self-contained HTML file that works without a sign-in.

- Load scripts only from cdnjs.cloudflare.com. Load fonts from Google Fonts with fallbacks.
- Do not depend on browser storage or on calls to other sites.
- For a shareable page, embed simplified boundaries (about 100 m). Capture them once through the owner's GeoQuery connector, embed them, then republish with capabilities cleared.
- Show "no value" for missing data. Never plot a missing value as zero.
- Keep all tokens in one `:root` block at the top of the style sheet.
- Test in a headless browser before publishing: no console errors, every dropdown option renders, and every point falls inside its polygon.
- Name the file for what it shows and publish updates to the same link.

## Prompt block to reuse

Paste this into a request, then describe the data and the question.

```text
Build this as a single-file HTML artifact in the AidData style (guide v0.1).
Structure: slim header label, content-type label, sentence-case H1 with an italic
one-line descriptor, a notice band if any data is simulated, a "question this
answers" line (where, for whom, with what effect), the main map or chart first,
then result, evidence, method and limits sections, a "data used" tile row with
counts, and a dark footer with affiliation, sources, license status and date.
Writing: plain declarative sentences, evidence first, a number with unit and year
in every claim, no em dashes, no hype words.
Visuals: real boundaries, a single-hue sequential ramp for magnitude, a gold to
brown ramp where darker means worse, legends with units and a no-value swatch,
uncertainty beside every estimate, keyboard focus rings and aria labels.
Tokens: use the :root block from the guide. Keep colors and fonts replaceable.
```
