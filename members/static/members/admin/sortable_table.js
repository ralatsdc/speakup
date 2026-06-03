/* Click-to-sort for any <table class="sortable-table">. Headers opt in with
 * class="sortable" and data-sort="text|number" (default text). Rows are sorted
 * on the cell's text content; ISO Y-m-d dates sort correctly as text. */
(function () {
    "use strict";

    function sortBy(table, th, index) {
        var tbody = table.tBodies[0];
        if (!tbody) return;
        var headers = table.querySelectorAll("th.sortable");
        var isAsc = th.classList.contains("sort-asc");
        var direction = isAsc ? -1 : 1;
        var type = th.dataset.sort || "text";

        headers.forEach(function (h) {
            h.classList.remove("sort-asc", "sort-desc");
        });
        th.classList.add(isAsc ? "sort-desc" : "sort-asc");

        var rows = Array.from(tbody.querySelectorAll("tr"));
        // A lone "empty" placeholder row (single colspan'd cell) shouldn't sort.
        if (rows.length <= 1) return;

        rows.sort(function (a, b) {
            var av = (a.children[index] || {}).textContent || "";
            var bv = (b.children[index] || {}).textContent || "";
            av = av.trim();
            bv = bv.trim();
            if (type === "number") {
                return direction * ((parseFloat(av) || 0) - (parseFloat(bv) || 0));
            }
            return direction * av.localeCompare(bv, undefined, {sensitivity: "base"});
        });
        rows.forEach(function (r) { tbody.appendChild(r); });
        // Re-apply admin alternating row classes after reorder.
        rows.forEach(function (r, i) {
            r.classList.remove("row1", "row2");
            r.classList.add(i % 2 === 0 ? "row1" : "row2");
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("table.sortable-table").forEach(function (table) {
            table.querySelectorAll("th.sortable").forEach(function (th, index) {
                th.addEventListener("click", function () {
                    sortBy(table, th, index);
                });
            });
        });
    });
})();
