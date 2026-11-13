// Filter boxes on the generated Datasets and Boundaries index pages
// (backend/datasets/docs/render.py emits the .gq-filter markup). Typing hides
// the table rows that don't contain every word typed, across all of the
// page's tables.
function initTableFilters() {
  for (const box of document.querySelectorAll(".gq-filter:not([data-ready])")) {
    box.dataset.ready = "";
    const input = box.querySelector("input");
    const status = box.querySelector(".gq-filter-count");
    const scope = box.closest("article") || document;
    const rows = [...scope.querySelectorAll("table tbody tr")];
    const noun = box.dataset.noun || "rows";

    input.addEventListener("input", () => {
      const terms = input.value.toLowerCase().split(/\s+/).filter(Boolean);
      let shown = 0;
      for (const row of rows) {
        const text = row.textContent.toLowerCase();
        row.hidden = !terms.every((t) => text.includes(t));
        if (!row.hidden) shown++;
      }
      status.textContent = terms.length ? `${shown} of ${rows.length} ${noun}` : "";
    });
  }
}

// With instant navigation, pages swap without a full load; document$ emits on
// each one.
if (typeof document$ !== "undefined") {
  document$.subscribe(initTableFilters);
} else {
  document.addEventListener("DOMContentLoaded", initTableFilters);
}
