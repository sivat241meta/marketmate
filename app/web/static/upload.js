"use strict";
/* Upload with a real progress bar. Uses XMLHttpRequest so bytes-sent progress
   is visible; without JS the plain form still posts to the same endpoint. */

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-upload-form]").forEach((form) => {
    const input = form.querySelector('input[type="file"]');
    const nameEl = form.querySelector("[data-upload-name]");
    const nameDefault = nameEl ? nameEl.textContent : "";
    const fileLine = form.querySelector("[data-upload-file]");
    const errorLine = form.querySelector("[data-upload-error]");
    const progressWrap = form.querySelector("[data-upload-progress]");
    const bar = form.querySelector("[data-upload-bar]");
    const meta = form.querySelector("[data-upload-meta]");
    const cancelBtn = form.querySelector("[data-upload-cancel]");
    const submitBtn = form.querySelector('[type="submit"]');
    if (!input || !progressWrap || !bar || !meta) {
      return;
    }
    const maxBytes = parseInt(form.dataset.maxBytes || "0", 10) || 0;
    let xhr = null;

    function fmtMB(bytes) {
      return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    }

    function tooBig(file) {
      return maxBytes > 0 && file.size > maxBytes;
    }

    function bigMessage(file) {
      return (
        "That file is " + fmtMB(file.size) + ", which is too big to upload. " +
        "Please choose a file under " + fmtMB(maxBytes) + "."
      );
    }

    function showError(message) {
      if (errorLine) {
        errorLine.textContent = message;
        errorLine.hidden = false;
      }
    }

    /* Task 131: a 4xx/5xx answer renders the error page — pull its
       message out so the failure is never silent or generic. */
    function extractError(html, fallback) {
      try {
        const doc = new DOMParser().parseFromString(html || "", "text/html");
        const el = doc.querySelector(
          ".alert, .field-error, .error-summary, .form-error");
        if (el && el.textContent.trim()) {
          return el.textContent.trim().slice(0, 200);
        }
        const head = doc.querySelector("h1");
        if (head && head.textContent.trim()) {
          return head.textContent.trim().slice(0, 200);
        }
      } catch (err) {
        /* fall through to the generic message */
      }
      return fallback;
    }

    function clearError() {
      if (errorLine) {
        errorLine.textContent = "";
        errorLine.hidden = true;
      }
    }

    function reset(file) {
      xhr = null;
      progressWrap.hidden = true;
      if (submitBtn) {
        submitBtn.disabled = false;
      }
      if (file) {
        fileLine.hidden = false;
        fileLine.textContent = file.name + " · " + fmtMB(file.size);
        if (nameEl) {
          nameEl.textContent = file.name;
        }
      }
    }

    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      clearError();
      if (!file) {
        fileLine.hidden = true;
        if (nameEl) {
          nameEl.textContent = nameDefault;
        }
        return;
      }
      reset(file);
      if (tooBig(file)) {
        showError(bigMessage(file));
      }
    });

    if (cancelBtn) {
      cancelBtn.addEventListener("click", () => {
        if (xhr) {
          xhr.abort();
        }
      });
    }

    form.addEventListener("submit", (event) => {
      const file = input.files && input.files[0];
      if (!file) {
        return; // No file chosen: let the browser enforce `required`.
      }
      if (tooBig(file)) {
        event.preventDefault();
        showError(bigMessage(file));
        return;
      }
      event.preventDefault();
      clearError();
      reset(file);
      progressWrap.hidden = false;
      bar.value = 0;
      meta.textContent = "Starting upload…";
      if (submitBtn) {
        submitBtn.disabled = true;
      }
      const data = new FormData(form);
      data.set(input.name, file, file.name);
      xhr = new XMLHttpRequest();
      xhr.open("POST", form.action);
      xhr.upload.addEventListener("progress", (progressEvent) => {
        if (!progressEvent.lengthComputable) {
          return;
        }
        const percent = Math.round(
          (progressEvent.loaded / progressEvent.total) * 100
        );
        bar.value = percent;
        meta.textContent =
          fmtMB(progressEvent.loaded) + " of " + fmtMB(progressEvent.total) +
          " · " + percent + "%";
      });
      xhr.addEventListener("load", () => {
        if (xhr.status < 200 || xhr.status >= 300) {
          showError(extractError(xhr.responseText,
            "Upload failed — try again."));
          reset(file);
          return;
        }
        const target = xhr.responseURL || "";
        const same = target &&
          new URL(target, window.location.href).href ===
            new URL(form.action, window.location.href).href;
        if (target && !same) {
          // The server answered with a redirect (video upload): the XHR
          // followed the 303 Location, so go to the session page.
          window.location.assign(target);
          return;
        }
        // Same-URL answer (voice update): show the confirm page it returned.
        document.open();
        document.write(xhr.responseText);
        document.close();
      });
      xhr.addEventListener("error", () => {
        showError("Upload failed — check your connection and try again.");
        reset(file);
      });
      xhr.addEventListener("abort", () => {
        showError("Upload cancelled.");
        reset(file);
      });
      xhr.send(data);
    });
  });
});
