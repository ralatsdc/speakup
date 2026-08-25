/* Emoji picker for the admin compose fields.
 *
 * Attaches an "Emoji" button to every [data-emoji] input/textarea. The
 * vendored emoji-picker-element is ~100 KB gzipped including its dataset, so
 * it is imported lazily on first open rather than on page load -- an officer
 * who never reaches for an emoji never downloads it.
 *
 * Both asset URLs arrive as data attributes on the field. They cannot be
 * hardcoded here: ManifestStaticFilesStorage hashes them in production, so
 * only the template knows the real paths.
 */
(function () {
  "use strict";

  // Where available, the Popover API gives us the top layer (escaping admin's
  // stacking contexts), light dismiss, Escape-to-close, and correct toggling
  // from the trigger button -- all of which we would otherwise hand-roll.
  var SUPPORTS_POPOVER = typeof HTMLElement !== "undefined" &&
    Object.prototype.hasOwnProperty.call(HTMLElement.prototype, "popover");

  // Roughly the picker's own footprint; used only to keep the panel on screen.
  var PANEL_WIDTH = 350;
  var PANEL_HEIGHT = 410;

  var uid = 0;
  var fallbackOpen = null;  // only used when SUPPORTS_POPOVER is false

  // --- insertion ---------------------------------------------------------

  function insertAtCursor(field, text) {
    field.focus();
    var inserted = false;
    try {
      // Preferred: keeps the browser's native undo stack intact (a manual
      // splice into .value wipes it) and fires "input" on its own.
      inserted = !!(document.execCommand &&
                    document.execCommand("insertText", false, text));
    } catch (e) {
      inserted = false;
    }
    if (!inserted) {
      var start = field.selectionStart == null ? field.value.length : field.selectionStart;
      var end = field.selectionEnd == null ? field.value.length : field.selectionEnd;
      field.setRangeText(text, start, end, "end");
      // Programmatic edits fire nothing. The review page's live preview is
      // driven by "input", so without this the preview silently goes stale
      // and shows the officer something other than what will send.
      field.dispatchEvent(new Event("input", { bubbles: true }));
      field.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  // --- placement ---------------------------------------------------------

  // Fixed positioning, computed here. Django admin's .form-row is a clearfix
  // with overflow:hidden, which clips an absolutely-positioned child to the
  // height of the row -- the picker rendered at full size with only ~12px of
  // it visible. overflow:hidden does not clip fixed descendants.
  function position(popover, button) {
    var rect = button.getBoundingClientRect();
    var left = Math.max(8, Math.min(rect.left, window.innerWidth - PANEL_WIDTH - 8));
    var top = rect.bottom + 4;
    if (top + PANEL_HEIGHT > window.innerHeight) {
      // Not enough room below -- flip above the button, but never off the top.
      top = Math.max(8, rect.top - PANEL_HEIGHT - 4);
    }
    popover.style.left = Math.round(left) + "px";
    popover.style.top = Math.round(top) + "px";
  }

  // --- theme -------------------------------------------------------------

  // The picker lives in a shadow root, so admin CSS cannot reach inside it.
  // Django's admin theme toggle writes html[data-theme]; mirror it onto the
  // element, and leave both classes off for "auto" so the picker falls back
  // to prefers-color-scheme like the rest of the page.
  function syncTheme(picker) {
    var theme = document.documentElement.dataset.theme;
    picker.classList.toggle("dark", theme === "dark");
    picker.classList.toggle("light", theme === "light");
  }

  function watchTheme(picker) {
    new MutationObserver(function () { syncTheme(picker); }).observe(
      document.documentElement,
      { attributes: true, attributeFilter: ["data-theme"] }
    );
  }

  // --- picker ------------------------------------------------------------

  function buildPicker(popover, field) {
    var pickerSrc = field.dataset.emojiPickerSrc;
    var dataSrc = field.dataset.emojiDataSrc;

    if (!pickerSrc || !dataSrc) {
      // Loud on purpose. A missing data-source silently falls back to the
      // library's jsdelivr default, which would reintroduce the third-party
      // CDN dependency this project deliberately removed -- and it would fail
      // invisibly, as an empty picker, on exactly the networks that matter.
      console.error("emoji-field: missing data-emoji-picker-src/data-emoji-data-src");
      popover.textContent = "Emoji picker unavailable.";
      return;
    }

    import(pickerSrc).then(function () {
      var picker = document.createElement("emoji-picker");
      picker.setAttribute("data-source", dataSrc);
      syncTheme(picker);
      watchTheme(picker);
      picker.addEventListener("emoji-click", function (event) {
        insertAtCursor(field, event.detail.unicode);
      });
      popover.textContent = "";
      popover.appendChild(picker);
    }).catch(function (err) {
      // The library requires IndexedDB, which is unavailable or throws in
      // some private-browsing configurations. Degrade to a message instead of
      // breaking the compose form around it.
      console.error("emoji-field: picker failed to load", err);
      popover.textContent = "Emoji picker unavailable.";
    });
  }

  // --- wiring ------------------------------------------------------------

  function attach(field) {
    uid += 1;

    var wrapper = document.createElement("div");
    wrapper.className = "emoji-field";

    var button = document.createElement("button");
    button.type = "button";
    button.className = "emoji-field-button";
    button.textContent = "😀 Emoji";
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", "Insert an emoji");

    var popover = document.createElement("div");
    popover.className = "emoji-field-popover";
    popover.id = "emoji-popover-" + uid;
    popover.textContent = "Loading…";

    var loaded = false;
    function loadOnce() {
      if (!loaded) {
        loaded = true;
        buildPicker(popover, field);
      }
    }

    if (SUPPORTS_POPOVER) {
      popover.setAttribute("popover", "auto");
      // Let the browser own the toggle. Wiring our own click handler instead
      // double-fires: light dismiss closes on pointerdown, then the click
      // reopens, so the panel never appears to close.
      button.setAttribute("popovertarget", popover.id);
      popover.addEventListener("beforetoggle", function (event) {
        if (event.newState === "open") {
          loadOnce();
          position(popover, button);
        }
      });
      popover.addEventListener("toggle", function (event) {
        button.setAttribute("aria-expanded", String(event.newState === "open"));
      });
    } else {
      popover.hidden = true;
      popover.emojiButton = button;  // closeFallback() resets the trigger
      button.addEventListener("click", function (event) {
        event.preventDefault();
        if (fallbackOpen === popover) {
          closeFallback();
          return;
        }
        closeFallback();
        loadOnce();
        position(popover, button);
        popover.hidden = false;
        fallbackOpen = popover;
        button.setAttribute("aria-expanded", "true");
      });
    }

    wrapper.appendChild(button);
    wrapper.appendChild(popover);
    field.insertAdjacentElement("afterend", wrapper);
  }

  function closeFallback() {
    if (!fallbackOpen) { return; }
    fallbackOpen.hidden = true;
    fallbackOpen.emojiButton.setAttribute("aria-expanded", "false");
    fallbackOpen = null;
  }

  function init() {
    document.querySelectorAll("[data-emoji]").forEach(function (field) {
      attach(field);
    });

    if (!SUPPORTS_POPOVER) {
      document.addEventListener("click", function (event) {
        if (fallbackOpen && !event.target.closest(".emoji-field")) {
          closeFallback();
        }
      });
      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") { closeFallback(); }
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
