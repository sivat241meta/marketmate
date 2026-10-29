/* Task 68: shared rename dialog for seller lists and the check page.
 *
 * Seller rows render a <details data-rename-sheet> so the rename form
 * works without JS (the open form drops to its own full-width line via
 * CSS). With JS, the summary click opens this modal instead: a centred
 * dialog on laptop, a bottom sheet on phones (see .rdlg-* in app.css).
 * The check page reuses the same dialog for its draft rename sheet;
 * review.js calls window.MMRenameDialog.open/close around its own
 * reset/save logic. Focus is trapped, Esc/backdrop/Cancel close the
 * dialog, and focus returns to the opener.
 *
 * No dependencies. Exposes window.MMRenameDialog = {open, close, isOpen}.
 */
(function () {
  "use strict";

  var state = null; // {sheet, opener, home, wrap, box, onKey}

  function focusables(box) {
    var nodes = box.querySelectorAll(
      "button, [href], input, select, textarea," +
      '[tabindex]:not([tabindex="-1"])');
    var out = [];
    Array.prototype.forEach.call(nodes, function (node) {
      if (!node.disabled && node.type !== "hidden") {
        out.push(node);
      }
    });
    return out;
  }

  function isOpen() {
    return state !== null;
  }

  function open(sheet, opener) {
    if (!sheet || typeof document === "undefined") {
      return false;
    }
    if (state && state.sheet === sheet) {
      return true;
    }
    close(true);
    var wrap = document.createElement("div");
    wrap.className = "rdlg-wrap";
    wrap.setAttribute("data-rename-dialog", "");
    var backdrop = document.createElement("div");
    backdrop.className = "rdlg-backdrop";
    backdrop.setAttribute("data-rename-backdrop", "");
    var box = document.createElement("div");
    box.className = "rdlg";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    var title = sheet.querySelector("h3");
    box.setAttribute("aria-label", title ? title.textContent.trim()
      : "Rename");
    wrap.appendChild(backdrop);
    wrap.appendChild(box);
    document.body.appendChild(wrap);
    var home = document.createComment("rename-home");
    sheet.parentNode.insertBefore(home, sheet);
    box.appendChild(sheet);
    sheet.hidden = false;
    // A no-JS-open <details> must not stay open behind the dialog.
    var details = home.parentNode && home.parentNode.closest
      ? home.parentNode.closest("details[data-rename-sheet]")
      : null;
    if (details) {
      details.removeAttribute("open");
    }
    state = { sheet: sheet, opener: opener || null, home: home,
      wrap: wrap, box: box, onKey: onKey };
    document.addEventListener("keydown", onKey);
    backdrop.addEventListener("click", function () { close(); });
    document.body.classList.add("rdlg-open");
    var first = sheet.querySelector('input[name="name_local"]')
      || focusables(box)[0];
    if (first && first.focus) {
      first.focus();
    }
    return true;
  }

  function onKey(event) {
    if (!state) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }
    var items = focusables(state.box);
    if (!items.length) {
      event.preventDefault();
      return;
    }
    var first = items[0];
    var last = items[items.length - 1];
    var active = document.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function close(silent) {
    if (!state) {
      return false;
    }
    var current = state;
    state = null;
    document.removeEventListener("keydown", current.onKey);
    current.sheet.hidden = true;
    if (current.home.parentNode) {
      current.home.parentNode.insertBefore(current.sheet, current.home);
      current.home.parentNode.removeChild(current.home);
    }
    if (current.wrap.parentNode) {
      current.wrap.parentNode.removeChild(current.wrap);
    }
    document.body.classList.remove("rdlg-open");
    if (!silent && current.opener && current.opener.focus) {
      current.opener.focus();
    }
    return true;
  }

  function wireSellerSheet(sheet) {
    var summary = sheet.querySelector(
      "summary[data-rename-open]");
    if (!summary) {
      return;
    }
    summary.addEventListener("click", function (event) {
      event.preventDefault();
      var form = sheet.querySelector("[data-rename-form]");
      open(form || sheet, summary);
    });
    var cancel = sheet.querySelector("[data-rename-cancel]");
    if (cancel) {
      cancel.addEventListener("click", function (event) {
        event.preventDefault();
        close();
      });
    }
    var form = sheet.querySelector("form[data-rename-form]");
    if (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        submitRename(form);
      });
    }
  }

  function submitRename(form) {
    var error = form.querySelector("[data-rename-error]");
    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: { Accept: "application/json" },
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(
        function (data) {
          if (!response.ok) {
            if (error) {
              error.textContent = (data && data.detail) || "";
              error.hidden = !(data && data.detail);
            }
            return;
          }
          window.location = form.action.split("/item/")[0] + "?renamed=1";
        });
    }).catch(function () {
      // Offline or failed: fall back to a plain post.
      form.submit();
    });
  }

  function wireAll() {
    if (typeof document === "undefined") {
      return;
    }
    var sheets = document.querySelectorAll("details[data-rename-sheet]");
    Array.prototype.forEach.call(sheets, wireSellerSheet);
  }

  if (typeof window !== "undefined" && window) {
    window.MMRenameDialog = { open: open, close: close, isOpen: isOpen,
      submitRename: submitRename };
  }
  if (typeof document !== "undefined" && document) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", wireAll);
    } else {
      wireAll();
    }
  }
})();
