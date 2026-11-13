// Accessibility fixes for the Zensical theme.
//
// Each nav section's nested <nav> is labelled by the section's toggle
// <label>. With navigation.indexes on, a section that has an index page puts
// its title in a sibling link instead, so that label is empty and the <nav>
// has no name: screen readers can't tell those landmarks apart. Name them from
// the title link.
function nameNavSections() {
  // The breadcrumb trail (navigation.path) is also labelled "Navigation",
  // the same as the main site nav.
  document.querySelector("nav.md-path")?.setAttribute("aria-label", "Breadcrumb");

  for (const nav of document.querySelectorAll("nav.md-nav[aria-labelledby]")) {
    const label = document.getElementById(nav.getAttribute("aria-labelledby"));
    if (!label || label.textContent.trim()) continue;
    const title = label.parentElement?.querySelector(":scope > a")?.textContent.trim();
    if (title) {
      nav.removeAttribute("aria-labelledby");
      nav.setAttribute("aria-label", title);
    }
  }
}

// With instant navigation, pages swap without a full load; document$ emits on
// each one.
if (typeof document$ !== "undefined") {
  document$.subscribe(nameNavSections);
} else {
  document.addEventListener("DOMContentLoaded", nameNavSections);
}
