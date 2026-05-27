// Live-toggle the `evaluates` field row on MeetingRole inlines.
//
// The Django template renders an inline JSON script tag with the IDs of
// Roles flagged is_evaluator_role=True (see MeetingAdmin.change_view +
// meetings/templates/meetings/admin/meeting_change_form.html). For every
// MeetingRole inline row we watch its `role` <select>; when the selected
// value is in that set, we add `.is-evaluator-row` to the row's
// `.inline-related` container so the accompanying CSS reveals the
// `evaluates` field. The reverse hides it.
//
// Server-side MeetingRole.clean() still enforces the rule, so a JS-
// disabled client can't sneak a bad value through a save.
(function () {
    "use strict";

    function readEvaluatorRoleIds() {
        var node = document.getElementById("evaluator-role-ids");
        if (!node) { return null; }
        try {
            return new Set(JSON.parse(node.textContent));
        } catch (e) {
            return null;
        }
    }

    function syncRow(roleSelect, evaluatorRoleIds) {
        var row = roleSelect.closest(".inline-related");
        if (!row) { return; }
        var selected = parseInt(roleSelect.value, 10);
        var isEvaluator = !isNaN(selected) && evaluatorRoleIds.has(selected);
        row.classList.toggle("is-evaluator-row", isEvaluator);
    }

    function initialize() {
        var evaluatorRoleIds = readEvaluatorRoleIds();
        if (!evaluatorRoleIds) { return; }
        document.querySelectorAll(".inline-related select[name$='-role']")
            .forEach(function (select) {
                syncRow(select, evaluatorRoleIds);
                select.addEventListener("change", function () {
                    syncRow(select, evaluatorRoleIds);
                });
            });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        initialize();
    }
})();
