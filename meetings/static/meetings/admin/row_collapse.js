// Click a MeetingRole inline row's <h3> to toggle collapse/expand.
//
// The custom inline template (meetings/templates/admin/edit_inline/
// meetings_meetingrole_stacked.html) renders every existing row with the
// .is-collapsed class; the accompanying CSS hides everything but the
// <h3>. This script:
//
//  - Uses event delegation so newly-added rows (cloned by Django admin's
//    "Add another" handler) also collapse on click without extra wiring.
//  - Ignores clicks on form controls or links inside the header so they
//    keep working (delete checkbox, change link, etc.).
//  - Auto-expands any row that contains validation errors after a save,
//    so officers can see what's wrong without hunting.
(function () {
    "use strict";

    var INLINE_ROW = ".inline-related";
    var INTERACTIVE_IN_HEADER = "input, label, a";

    function onClick(event) {
        var header = event.target.closest(INLINE_ROW + " > h3");
        if (!header) { return; }
        if (event.target.closest(INTERACTIVE_IN_HEADER)) { return; }
        var row = header.closest(INLINE_ROW);
        if (!row || row.classList.contains("empty-form")) { return; }
        row.classList.toggle("is-collapsed");
    }

    function autoExpandErrors() {
        document.querySelectorAll(INLINE_ROW).forEach(function (row) {
            if (row.classList.contains("empty-form")) { return; }
            if (row.querySelector(".errorlist, .errornote")) {
                row.classList.remove("is-collapsed");
            }
        });
    }

    function initialize() {
        document.addEventListener("click", onClick);
        autoExpandErrors();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        initialize();
    }
})();
