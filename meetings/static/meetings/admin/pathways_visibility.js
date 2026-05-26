// Live-toggle the Pathways fields (path / level / project) on
// MeetingRole inlines. Mirrors evaluator_pairing.js, but watches the
// `shows_pathways_fields` flag and the `is-pathways-row` class. See
// MeetingAdmin.change_view + meeting_change_form.html for the JSON
// payload of pathways-role IDs.
(function () {
    "use strict";

    function readPathwaysRoleIds() {
        var node = document.getElementById("pathways-role-ids");
        if (!node) { return null; }
        try {
            return new Set(JSON.parse(node.textContent));
        } catch (e) {
            return null;
        }
    }

    function syncRow(roleSelect, pathwaysRoleIds) {
        var row = roleSelect.closest(".inline-related");
        if (!row) { return; }
        var selected = parseInt(roleSelect.value, 10);
        var isPathways = !isNaN(selected) && pathwaysRoleIds.has(selected);
        row.classList.toggle("is-pathways-row", isPathways);
    }

    function initialize() {
        var pathwaysRoleIds = readPathwaysRoleIds();
        if (!pathwaysRoleIds) { return; }
        document.querySelectorAll(".inline-related select[name$='-role']")
            .forEach(function (select) {
                syncRow(select, pathwaysRoleIds);
                select.addEventListener("change", function () {
                    syncRow(select, pathwaysRoleIds);
                });
            });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        initialize();
    }
})();
