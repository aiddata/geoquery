---
description: "GeoQuery's commitment to accessibility, its conformance with WCAG 2.2, known limitations, and how to report a problem."
---

# Accessibility

*Last updated: November 13, 2026*

We want GeoQuery to be usable by everyone, including people who use screen readers, keyboards, magnification or other assistive technologies.

## Our goal

We aim for the GeoQuery application and this documentation site to meet the [Web Content Accessibility Guidelines (WCAG) 2.2](https://www.w3.org/TR/WCAG22/) at level AA.

## Current status

GeoQuery **partially conforms** with WCAG 2.2 AA: most of it works with a keyboard and screen readers, but some parts don't yet. We assessed it in November 2026 using automated testing and keyboard testing, and we're working through what we found.

What works well:

- The site can be navigated with a keyboard, with a visible focus outline.
- Text contrast meets AA in both the light and dark themes, and a high-contrast mode is supported.
- Charts on the statistics page come with a data table.
- This documentation site has no known automated-test failures.

## Known limitations

- **Selecting individual areas on the map** requires a mouse. You can still select whole boundary sets with a keyboard, using the search box.
- **Boundary search suggestions** aren't announced to screen readers. You can reach them with the Tab key.
- **Option checkboxes on the Customize page** aren't announced with their names by screen readers.
- **Some details appear only on mouse hover**, such as the source and license of boundary sets in the Browse All list.
- **Status changes**, such as a dataset being added to your request, aren't always announced to screen readers.
- **Narrow windows and high zoom.** GeoQuery is designed for screens at least 1,024 pixels wide. On smaller screens, and at high browser zoom, pages are shown zoomed out or scroll sideways.

We're working on these, and the most important ones first.

## Report a problem

If something in GeoQuery is hard to use, or you need data in a different format, please tell us at [geo@aiddata.wm.edu](mailto:geo@aiddata.wm.edu). Let us know the page, what you were trying to do, and the browser and assistive technology you use. We'll do our best to help, including by preparing your data for you.
