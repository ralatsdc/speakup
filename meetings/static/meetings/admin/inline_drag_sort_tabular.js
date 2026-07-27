// Drag-to-reorder for the MeetingType tabular inlines (sessions + items).
// Uses SortableJS (loaded via CDN by MeetingTypeAdmin.Media). Unlike the
// stacked MeetingRole inline (inline_drag_sort.js), these are TabularInlines,
// so rows are <tr class="form-row"> inside a <tbody>, the order field suffix
// is "-order", and there is no session-group logic — it's a flat list.
//
// On init a small drag handle is injected into each row's leading cell. On
// drop the JS renumbers every real row's `order` input to its new index so
// the form submission persists the order. Only inlines that expose an
// `order` column are wired up, so unrelated inlines are left alone.
(function () {
    "use strict";

    if (typeof Sortable === "undefined") {
        return;  // SortableJS failed to load — degrade gracefully.
    }

    var ROW = "tr.form-row";

    function isSkippable(row) {
        // The empty-form template row and the "Add another" row are not
        // real, orderable rows.
        return row.classList.contains("empty-form") ||
               row.classList.contains("add-row");
    }

    function renumber(tbody) {
        var index = 0;
        tbody.querySelectorAll(ROW).forEach(function (row) {
            if (isSkippable(row)) { return; }
            var input = row.querySelector("input[name$='-order']");
            if (input) {
                input.value = String(index);
                index++;
            }
        });
    }

    function addHandle(row) {
        if (isSkippable(row)) { return; }
        var cell = row.querySelector("td.original") || row.querySelector("td");
        if (!cell || cell.querySelector(".mtype-drag-handle")) { return; }
        var handle = document.createElement("span");
        handle.className = "mtype-drag-handle";
        handle.title = "Drag to reorder";
        handle.setAttribute("aria-hidden", "true");
        handle.textContent = "⠿";  // braille grip dots
        cell.insertBefore(handle, cell.firstChild);
    }

    function sortableGroups() {
        // A MeetingType inline is orderable iff its table has an order column.
        return Array.prototype.filter.call(
            document.querySelectorAll(".inline-group"),
            function (group) { return !!group.querySelector("th.column-order"); }
        );
    }

    function initGroup(group) {
        var tbody = group.querySelector("fieldset table tbody");
        if (!tbody) { return; }

        tbody.querySelectorAll(ROW).forEach(addHandle);

        new Sortable(tbody, {
            handle: ".mtype-drag-handle",
            draggable: ROW,
            filter: ".empty-form, .add-row",
            animation: 150,
            ghostClass: "mtype-drag-ghost",
            onMove: function (evt) {
                // Keep the empty-form / add-row pinned at the bottom.
                if (evt.related && isSkippable(evt.related)) {
                    return false;
                }
            },
            onEnd: function () { renumber(tbody); },
        });
    }

    function initialize() {
        sortableGroups().forEach(initGroup);

        // Rows added after load (via "Add another") need a handle too. Django
        // dispatches a bubbling `formset:added` event on the new row.
        document.addEventListener("formset:added", function (event) {
            var row = event.target;
            if (row && row.closest && row.closest(".inline-group") &&
                row.closest(".inline-group").querySelector("th.column-order")) {
                addHandle(row);
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        initialize();
    }
})();
