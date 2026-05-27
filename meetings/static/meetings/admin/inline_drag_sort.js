// Drag-to-reorder for the MeetingRole inline. Uses SortableJS (loaded via
// CDN by MeetingRoleInline.Media). On drop the JS:
//   1. Rewrites every row's sort_order hidden input to its new index, so
//      the form submission persists the new order.
//   2. If the dragged row crossed a session-group header, updates the
//      row's session <select> to match the destination group (read from
//      the preceding session header's data-session-id).
//
// Only the MeetingRole inline-group is targeted; we detect it by the
// presence of the filter bar that the custom inline template renders.
(function () {
    "use strict";

    if (typeof Sortable === "undefined") {
        return;  // SortableJS failed to load — degrade gracefully.
    }

    var ROW = ".inline-related";

    function findSessionIdForRow(row) {
        var sibling = row.previousElementSibling;
        while (sibling) {
            if (sibling.classList.contains("meeting-role-session-header")) {
                return sibling.dataset.sessionId || "";
            }
            sibling = sibling.previousElementSibling;
        }
        return "";
    }

    function recomputeSortOrders(group) {
        var index = 0;
        group.querySelectorAll(ROW).forEach(function (row) {
            if (row.classList.contains("empty-form")) { return; }
            var input = row.querySelector("input[name$='-sort_order']");
            if (input) {
                input.value = String(index);
                index++;
            }
        });
    }

    function maybeUpdateSession(row) {
        var newSessionId = findSessionIdForRow(row);
        var select = row.querySelector("select[name$='-session']");
        if (!select) { return; }
        // Set the select's value if it differs. The empty string maps to
        // Django's "---------" option for the nullable session FK.
        if (select.value !== newSessionId) {
            select.value = newSessionId;
        }
    }

    function initialize() {
        document.querySelectorAll(".inline-group").forEach(function (group) {
            // Filter bar = MeetingRole inline (skip MeetingSession inline).
            if (!group.querySelector(".meetingrole-filter-bar")) { return; }

            // SortableJS only reorders DIRECT children of its container,
            // but .inline-related rows sit inside the <fieldset> that the
            // stacked-inline template wraps around them. Target the
            // fieldset (the rows' actual parent), not the .inline-group
            // div one level up.
            var fieldset = group.querySelector("fieldset.module");
            if (!fieldset) { return; }

            new Sortable(fieldset, {
                handle: ".meetingrole-drag-handle",
                draggable: ROW,
                filter: ".empty-form",
                animation: 150,
                ghostClass: "meetingrole-drag-ghost",
                onEnd: function (evt) {
                    recomputeSortOrders(group);
                    maybeUpdateSession(evt.item);
                },
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        initialize();
    }
})();
