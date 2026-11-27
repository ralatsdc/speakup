/* "Start from template" on the announcement form: copy the chosen template's
 * subject and body into the form. Asks first if that would replace text that
 * didn't come from the previously chosen template unchanged. */
(function () {
  "use strict";

  // Textareas normalize line endings to \n; saved templates may carry \r\n.
  function normalize(text) {
    return (text || "").replace(/\r\n?/g, "\n");
  }

  function init() {
    var picker = document.querySelector("select[data-email-templates]");
    var subject = document.getElementById("id_subject");
    var body = document.getElementById("id_body");
    if (!picker || !subject || !body) { return; }

    var templates = JSON.parse(picker.dataset.emailTemplates);
    var previous = picker.value;
    var copied = null;  // what the picker itself last put in the fields

    function isSafeToReplace() {
      if (!subject.value.trim() && !body.value.trim()) { return true; }
      return copied !== null && subject.value === copied.subject &&
        body.value === copied.body;
    }

    function fill(field, value) {
      field.value = value;
      field.dispatchEvent(new Event("input", { bubbles: true }));
      field.dispatchEvent(new Event("change", { bubbles: true }));
    }

    picker.addEventListener("change", function () {
      var template = templates[picker.value];
      if (template && !isSafeToReplace() &&
          !window.confirm("Replace the current subject and body with this template?")) {
        picker.value = previous;
        return;
      }
      previous = picker.value;
      if (!template) { return; }  // blank choice: leave the text alone
      copied = {
        subject: normalize(template.subject),
        body: normalize(template.body)
      };
      fill(subject, copied.subject);
      fill(body, copied.body);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
