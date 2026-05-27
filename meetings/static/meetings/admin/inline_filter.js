// Live filter for the MeetingRole inline.
//
// Matches the lowercased query against each row's collapsed-summary <h3>
// text (role name, assignee, "(open)", In Person / Remote chips, "evaluating
// X"). Hides non-matching rows by adding .filtered-out; hides session-group
// headers whose group has no visible rows.
(function () {
    "use strict";

    var INPUT_ID = "meetingrole-filter";
    var COUNT_SEL = ".meetingrole-filter-count";

    function isRowExempt(row) {
        // Don't filter the empty template row (already display:none via
        // stock admin) or rows that became visible due to a save-time
        // error (auto-expanded by row_collapse.js).
        return row.classList.contains("empty-form");
    }

    function applyFilter(query) {
        query = (query || "").trim().toLowerCase();
        var rows = document.querySelectorAll(".inline-related");
        var matched = 0;
        var total = 0;

        rows.forEach(function (row) {
            if (isRowExempt(row)) { return; }
            total++;
            if (!query) {
                row.classList.remove("filtered-out");
                matched++;
                return;
            }
            var header = row.querySelector("h3");
            var text = header ? header.textContent.toLowerCase() : "";
            if (text.indexOf(query) !== -1) {
                row.classList.remove("filtered-out");
                matched++;
            } else {
                row.classList.add("filtered-out");
            }
        });

        // Hide session headers whose group has no visible rows.
        document.querySelectorAll(".meeting-role-session-header").forEach(function (h) {
            var hasVisible = false;
            var sibling = h.nextElementSibling;
            while (sibling && !sibling.classList.contains("meeting-role-session-header")) {
                if (sibling.classList.contains("inline-related") &&
                    !isRowExempt(sibling) &&
                    !sibling.classList.contains("filtered-out")) {
                    hasVisible = true;
                    break;
                }
                sibling = sibling.nextElementSibling;
            }
            h.classList.toggle("filtered-out", !hasVisible);
        });

        var counter = document.querySelector(COUNT_SEL);
        if (counter) {
            counter.textContent = query ? matched + " of " + total : "";
        }
    }

    function initialize() {
        var input = document.getElementById(INPUT_ID);
        if (!input) { return; }
        input.addEventListener("input", function (event) {
            applyFilter(event.target.value);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        initialize();
    }
})();
