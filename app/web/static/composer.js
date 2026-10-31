"use strict";
/* Task 123: ChatGPT-style voice/text composer.
 *
 * One enhanced pill per [data-composer]: tap mic to record (live waveform +
 * timer, Cancel discards, Send stops and sends), type to morph mic into Send,
 * "+" offers recording/video uploads. Sending posts the same action, method
 * and field names as the plain form, then polls the page's existing status
 * endpoint and shows the result in chat bubbles. Without JS the plain form
 * (textarea and/or file input + Send) still posts as before.
 *
 * Exposes exactly one global: window.initComposer.
 */

(function () {
  var LISTEN_STAGES = ["received", "uploaded", "listening", "looking",
    "transcribing"];
  var UNDERSTAND_STAGES = ["matching", "items", "counting", "checking",
    "suggesting", "ready"];
  var DONE_STATUSES = ["review", "approved", "done", "complete", "completed"];
  /* Task 131: stages where the seller must answer a question before the
     pipeline can continue (see seller.py + language_check.html). While a
     session sits in one of these the composer stops polling and shows the
     question instead of "Listening…" forever. */
  var NEEDS_ACTION_STAGES = ["language_check"];
  var LANG_STORE_KEY = "mm_speak_lang";
  var WAVE_BARS = 24;
  var POLL_MS = 1500;
  var POLL_MAX = 40;
  var WARN_LEFT_S = 10;
  var DONE_REDIRECT_MS = 1600;

  function pickMime() {
    if (typeof window.MediaRecorder === "undefined" ||
        !window.MediaRecorder.isTypeSupported) {
      return "";
    }
    if (window.MediaRecorder.isTypeSupported("audio/webm")) {
      return "audio/webm";
    }
    if (window.MediaRecorder.isTypeSupported("audio/mp4")) {
      return "audio/mp4";
    }
    return "";
  }

  function fmtTime(totalSeconds) {
    var total = Math.max(0, Math.floor(totalSeconds || 0));
    var minutes = Math.floor(total / 60);
    var seconds = total % 60;
    return minutes + ":" + (seconds < 10 ? "0" : "") + seconds;
  }

  function reducedMotion() {
    return typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  /* Session-page URL -> its existing JSON status endpoint, else null. */
  function statusUrlFor(pageUrl) {
    var path = "";
    try {
      path = new URL(pageUrl, window.location.href).pathname;
    } catch (err) {
      return null;
    }
    if (/\/s\/[^/]+\/quote\/\d+$/.test(path) ||
        /\/e\/[^/]+\/bills\/new\/\d+$/.test(path) ||
        /\/e\/[^/]+\/s\/\d+$/.test(path)) {
      return path + "/status";
    }
    return null;
  }

  /* Task 131: pure read of one status poll. "done" only for done
     statuses (or the page's own done marker: a created bill/quote).
     Steps follow the real stage: listening step 1, understanding 2. */
  function statusOf(data) {
    return String((data && data.status) || "").toLowerCase();
  }

  function stageOf(data) {
    return String((data && data.stage) || "").toLowerCase();
  }

  function isDoneData(data) {
    if (!data) {
      return false;
    }
    return DONE_STATUSES.indexOf(statusOf(data)) >= 0 ||
      !!(data.bill_id || data.quote_token);
  }

  function isFailedData(data) {
    var status = statusOf(data);
    return status === "failed" || status === "error";
  }

  function isNeedsAction(data) {
    if (!data) {
      return false;
    }
    if (data.needs_action === true || data.needsAction === true) {
      return true;
    }
    return NEEDS_ACTION_STAGES.indexOf(stageOf(data)) >= 0;
  }

  function stepForStage(stage) {
    return UNDERSTAND_STAGES.indexOf(
      String(stage || "").toLowerCase()) >= 0 ? 2 : 1;
  }

  function statusView(data) {
    if (isFailedData(data)) {
      return { kind: "failed", step: 1 };
    }
    if (isNeedsAction(data)) {
      return { kind: "needs_action", step: 1 };
    }
    if (isDoneData(data)) {
      return { kind: "done", step: 3 };
    }
    return { kind: "pending", step: stepForStage(stageOf(data)) };
  }

  function languagePostUrl(statusUrl) {
    var url = String(statusUrl || "");
    if (!/\/status\/?$/.test(url)) {
      return "";
    }
    return url.replace(/\/status\/?$/, "/language");
  }

  function extractError(html, fallback) {
    try {
      var doc = new DOMParser().parseFromString(html || "", "text/html");
      var el = doc.querySelector(
        ".alert, .field-error, .error-summary, .form-error");
      if (el && el.textContent.trim()) {
        return el.textContent.trim().slice(0, 200);
      }
      var head = doc.querySelector("h1");
      if (head && head.textContent.trim()) {
        return head.textContent.trim().slice(0, 200);
      }
    } catch (err) {
      /* fall through to the generic message */
    }
    return fallback;
  }

  function makeEl(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) {
      el.className = cls;
    }
    if (text !== undefined && text !== null) {
      el.textContent = text;
    }
    return el;
  }

  function announce(ctx, message) {
    if (!ctx.live) {
      return;
    }
    ctx.live.textContent = "";
    window.setTimeout(function () {
      ctx.live.textContent = message;
    }, 30);
  }

  function showHint(ctx, message) {
    if (!ctx.hint) {
      return;
    }
    ctx.hint.textContent = message;
    ctx.hint.hidden = !message;
  }

  function setState(ctx, state) {
    ctx.state = state;
    ctx.root.dataset.state = state;
    var recording = state === "recording" || state === "ready";
    var busy = state === "sending" || state === "done";
    if (ctx.plus) {
      ctx.plus.hidden = recording || busy;
    }
    if (ctx.menu) {
      ctx.menu.hidden = true;
    }
    if (ctx.plus) {
      ctx.plus.setAttribute("aria-expanded", "false");
    }
    if (ctx.mic) {
      ctx.mic.hidden = recording || busy || ctx.hasText;
    }
    if (ctx.send) {
      ctx.send.hidden = busy || (!recording && !ctx.hasText);
      ctx.send.disabled = busy;
    }
    if (ctx.cancel) {
      ctx.cancel.hidden = !recording;
      ctx.cancel.disabled = busy;
    }
    if (ctx.textarea) {
      ctx.textarea.hidden = recording;
      ctx.textarea.disabled = busy;
    }
    if (ctx.wave) {
      ctx.wave.hidden = !recording;
    }
    if (ctx.timer) {
      ctx.timer.hidden = !recording;
    }
    if (ctx.mic) {
      ctx.mic.disabled = busy;
    }
    if (ctx.plus) {
      ctx.plus.disabled = busy;
    }
    if (ctx.langMenu) {
      closeLangMenu(ctx);
    }
    if (ctx.langChip) {
      ctx.langChip.disabled = busy;
    }
  }

  function updateSendToggle(ctx) {
    if (!ctx.textarea || ctx.state === "recording" || ctx.state === "ready" ||
        ctx.state === "sending" || ctx.state === "done") {
      return;
    }
    ctx.hasText = ctx.textarea.value.trim().length > 0;
    setState(ctx, "idle");
  }

  function autogrow(ctx) {
    if (!ctx.textarea) {
      return;
    }
    ctx.textarea.style.height = "auto";
    var max = 120;
    ctx.textarea.style.height =
      Math.min(ctx.textarea.scrollHeight, max) + "px";
  }

  function openMenu(ctx) {
    if (!ctx.menu || !ctx.plus) {
      return;
    }
    ctx.menu.hidden = false;
    ctx.plus.setAttribute("aria-expanded", "true");
  }

  function closeMenu(ctx) {
    if (!ctx.menu || !ctx.plus) {
      return;
    }
    ctx.menu.hidden = true;
    ctx.plus.setAttribute("aria-expanded", "false");
  }

  function toggleMenu(ctx) {
    if (!ctx.menu || ctx.menu.hidden) {
      openMenu(ctx);
    } else {
      closeMenu(ctx);
    }
  }

  function noMic(ctx) {
    showHint(ctx, ctx.str.httpsHint);
    announce(ctx, ctx.str.httpsHint);
    openMenu(ctx);
  }

  function stopTracks(ctx) {
    if (ctx.stream) {
      ctx.stream.getTracks().forEach(function (track) {
        try {
          track.stop();
        } catch (err) {
          /* already stopped */
        }
      });
      ctx.stream = null;
    }
    if (ctx.audioCtx) {
      try {
        ctx.audioCtx.close();
      } catch (err) {
        /* already closed */
      }
      ctx.audioCtx = null;
    }
    ctx.analyser = null;
    if (ctx.waveRaf) {
      cancelAnimationFrame(ctx.waveRaf);
      ctx.waveRaf = 0;
    }
    if (ctx.timerId) {
      window.clearInterval(ctx.timerId);
      ctx.timerId = 0;
    }
  }

  function elapsedSeconds(ctx) {
    return (Date.now() - ctx.startedAt) / 1000;
  }

  function buildWave(ctx) {
    if (!ctx.wave) {
      return;
    }
    ctx.wave.textContent = "";
    ctx.waveBars = [];
    if (reducedMotion()) {
      var level = makeEl("span", "composer-level");
      ctx.wave.appendChild(level);
      ctx.waveBars.push(level);
      return;
    }
    for (var i = 0; i < WAVE_BARS; i++) {
      var bar = makeEl("span", "composer-bar");
      ctx.wave.appendChild(bar);
      ctx.waveBars.push(bar);
    }
  }

  function paintWave(ctx) {
    if (!ctx.analyser || !ctx.waveBars || !ctx.waveBars.length) {
      return;
    }
    var data = new Uint8Array(ctx.analyser.frequencyBinCount);
    ctx.analyser.getByteFrequencyData(data);
    if (ctx.waveBars.length === 1) {
      var sum = 0;
      for (var i = 0; i < data.length; i++) {
        sum += data[i];
      }
      var avg = data.length ? sum / data.length / 255 : 0;
      ctx.waveBars[0].style.width = Math.round(avg * 100) + "%";
      return;
    }
    for (var b = 0; b < ctx.waveBars.length; b++) {
      var value = data[Math.floor(b * data.length / ctx.waveBars.length)] || 0;
      var pct = 8 + Math.round((value / 255) * 92);
      ctx.waveBars[b].style.height = pct + "%";
    }
  }

  function startTimer(ctx) {
    var warned = false;
    ctx.timerId = window.setInterval(function () {
      var elapsed = elapsedSeconds(ctx);
      var left = ctx.maxSeconds - elapsed;
      if (ctx.timer) {
        ctx.timer.textContent = fmtTime(elapsed);
      }
      if (!warned && left <= WARN_LEFT_S && left > 0) {
        warned = true;
        var msg = ctx.str.secondsLeft.replace("{n}", String(Math.ceil(left)));
        showHint(ctx, msg);
      }
      if (left <= 0) {
        autoStop(ctx);
      }
    }, 250);
    function loop() {
      if (ctx.state !== "recording") {
        return;
      }
      paintWave(ctx);
      ctx.waveRaf = requestAnimationFrame(loop);
    }
    if (typeof requestAnimationFrame === "function") {
      ctx.waveRaf = requestAnimationFrame(loop);
    }
  }

  function startRecording(ctx) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia ||
        typeof window.MediaRecorder === "undefined") {
      noMic(ctx);
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var mime = pickMime();
      var recorder = null;
      try {
        recorder = mime ? new window.MediaRecorder(stream, { mimeType: mime })
          : new window.MediaRecorder(stream);
      } catch (err) {
        stream.getTracks().forEach(function (track) {
          track.stop();
        });
        noMic(ctx);
        return;
      }
      ctx.stream = stream;
      ctx.recorder = recorder;
      ctx.chunks = [];
      ctx.cancelled = false;
      ctx.autoStopped = false;
      recorder.ondataavailable = function (event) {
        if (event.data && event.data.size) {
          ctx.chunks.push(event.data);
        }
      };
      recorder.onstop = function () {
        onRecorderStop(ctx);
      };
      try {
        var AC = window.AudioContext || window.webkitAudioContext;
        if (AC) {
          ctx.audioCtx = new AC();
          var src = ctx.audioCtx.createMediaStreamSource(stream);
          ctx.analyser = ctx.audioCtx.createAnalyser();
          ctx.analyser.fftSize = 64;
          src.connect(ctx.analyser);
        }
      } catch (err) {
        ctx.analyser = null;
      }
      ctx.startedAt = Date.now();
      ctx.hasText = false;
      buildWave(ctx);
      if (ctx.timer) {
        ctx.timer.textContent = "0:00";
      }
      showHint(ctx, "");
      try {
        recorder.start();
      } catch (err) {
        stopTracks(ctx);
        noMic(ctx);
        return;
      }
      setState(ctx, "recording");
      announce(ctx, ctx.str.recording);
      startTimer(ctx);
    }).catch(function () {
      noMic(ctx);
    });
  }

  function recordedBlob(ctx) {
    var type = (ctx.recorder && ctx.recorder.mimeType) || pickMime() ||
      "audio/webm";
    try {
      return new Blob(ctx.chunks, { type: type });
    } catch (err) {
      return null;
    }
  }

  function onRecorderStop(ctx) {
    var seconds = ctx.startedAt ? elapsedSeconds(ctx) : 0;
    stopTracks(ctx);
    if (ctx.cancelled) {
      ctx.pendingBlob = null;
      ctx.hasText = false;
      if (ctx.textarea) {
        updateSendToggle(ctx);
      }
      setState(ctx, "idle");
      showHint(ctx, "");
      return;
    }
    var blob = recordedBlob(ctx);
    if (!blob || !blob.size) {
      setState(ctx, "idle");
      showHint(ctx, ctx.str.failed);
      return;
    }
    ctx.pendingBlob = blob;
    ctx.pendingSeconds = seconds;
    if (ctx.autoStopped) {
      /* Max length: hold the take for an explicit Send instead of sending. */
      if (ctx.timer) {
        ctx.timer.textContent = fmtTime(seconds);
      }
      setState(ctx, "ready");
      showHint(ctx, ctx.str.limitReached);
      return;
    }
    sendPending(ctx);
  }

  function autoStop(ctx) {
    if (ctx.state !== "recording" || !ctx.recorder ||
        ctx.recorder.state === "inactive") {
      return;
    }
    ctx.autoStopped = true;
    try {
      ctx.recorder.stop();
    } catch (err) {
      /* onstop still fires */
    }
  }

  function stopAndSend(ctx) {
    if (!ctx.recorder || ctx.recorder.state === "inactive") {
      return;
    }
    try {
      ctx.recorder.stop();
    } catch (err) {
      /* onstop still fires */
    }
  }

  function cancelRecording(ctx) {
    ctx.cancelled = true;
    if (ctx.recorder && ctx.recorder.state !== "inactive") {
      try {
        ctx.recorder.stop();
      } catch (err) {
        onRecorderStop(ctx);
      }
      return;
    }
    onRecorderStop(ctx);
  }

  /* FormData with the recorded blob/file under the page's existing file
     field, plus the page's other fields (never empty file parts). */
  function collectFields(ctx, form, text) {
    var controls = ctx.form.querySelectorAll("input, select, textarea");
    Array.prototype.forEach.call(controls, function (el) {
      if (el.disabled || !el.name || el.type === "file" ||
          el === ctx.textarea) {
        return;
      }
      if ((el.type === "checkbox" || el.type === "radio") && !el.checked) {
        return;
      }
      form.append(el.name, el.value);
    });
    var value = text !== undefined ? text
      : (ctx.textarea ? ctx.textarea.value.trim() : "");
    if (value && ctx.textField) {
      form.append(ctx.textField, value);
    }
  }

  function blobExt(blob) {
    var type = (blob && blob.type) || "";
    if (type.indexOf("mp4") >= 0 || type.indexOf("m4a") >= 0) {
      return "m4a";
    }
    return "webm";
  }

  function scrollTo(el) {
    try {
      el.scrollIntoView({ block: "nearest",
        behavior: reducedMotion() ? "auto" : "smooth" });
    } catch (err) {
      /* old browsers: no smooth scroll */
    }
  }

  function addUserTextBubble(ctx, text) {
    var bubble = makeEl("div", "composer-bubble composer-bubble-user", text);
    ctx.thread.appendChild(bubble);
    scrollTo(bubble);
    return bubble;
  }

  function addUserAudioBubble(ctx, blob, seconds) {
    var bubble = makeEl("div", "composer-bubble composer-bubble-user");
    var pill = makeEl("span", "composer-audio-pill");
    var url = "";
    try {
      url = URL.createObjectURL(blob);
    } catch (err) {
      url = "";
    }
    var audio = document.createElement("audio");
    audio.preload = "metadata";
    if (url) {
      audio.src = url;
    }
    var play = makeEl("button", "composer-play", "▶");
    play.type = "button";
    play.setAttribute("aria-label", ctx.str.play);
    var meta = makeEl("span", "composer-audio-meta",
      "🎙 " + fmtTime(seconds));
    play.addEventListener("click", function () {
      if (audio.paused) {
        var pending = audio.play();
        if (pending && pending.catch) {
          pending.catch(function () { /* no audio device */ });
        }
      } else {
        audio.pause();
      }
    });
    audio.addEventListener("play", function () {
      play.textContent = "⏸";
      play.setAttribute("aria-label", ctx.str.pause);
    });
    function toPlay() {
      play.textContent = "▶";
      play.setAttribute("aria-label", ctx.str.play);
    }
    audio.addEventListener("pause", toPlay);
    audio.addEventListener("ended", toPlay);
    pill.appendChild(audio);
    pill.appendChild(meta);
    pill.appendChild(play);
    bubble.appendChild(pill);
    ctx.thread.appendChild(bubble);
    scrollTo(bubble);
    return bubble;
  }

  function addStatusBubble(ctx) {
    var bubble = makeEl("div", "composer-bubble composer-bubble-status");
    var steps = makeEl("ol", "composer-steps");
    var labels = [ctx.str.sending, ctx.str.listening, ctx.str.understanding,
      ctx.str.done];
    labels.forEach(function (label, index) {
      var li = makeEl("li", "composer-step");
      li.dataset.step = String(index);
      li.appendChild(makeEl("span", "composer-dot"));
      li.appendChild(makeEl("span", "composer-step-label", label));
      steps.appendChild(li);
    });
    bubble.appendChild(steps);
    ctx.thread.appendChild(bubble);
    scrollTo(bubble);
    setStep(bubble, 0);
    return bubble;
  }

  function setStep(bubble, active) {
    var items = bubble.querySelectorAll("[data-step]");
    Array.prototype.forEach.call(items, function (li) {
      var index = parseInt(li.dataset.step || "0", 10);
      li.classList.toggle("is-done", index < active);
      li.classList.toggle("is-active", index === active);
      li.classList.toggle("is-todo", index > active);
    });
  }

  function replaceBubble(bubble, nodes) {
    bubble.textContent = "";
    nodes.forEach(function (node) {
      bubble.appendChild(node);
    });
  }

  function showDone(ctx, bubble, data, finalUrl) {
    setStep(bubble, 3);
    var summary = (data && (data.message || data.friendly)) || ctx.str.done;
    var line = makeEl("p", "composer-result", "✓ " + summary);
    var cta = makeEl("a", "composer-cta", ctx.doneLabel);
    cta.href = finalUrl;
    replaceBubble(bubble, [line, cta]);
    announce(ctx, summary);
    window.setTimeout(function () {
      window.location.href = finalUrl;
    }, DONE_REDIRECT_MS);
  }

  function showOpenLink(ctx, bubble, finalUrl) {
    /* Task 131: polling gave up, but the session is not done — never
       print "Done" here, just link to the result page. */
    var line = makeEl("p", "composer-result", ctx.str.stillWorking);
    var cta = makeEl("a", "composer-cta", ctx.doneLabel);
    cta.href = finalUrl;
    replaceBubble(bubble, [line, cta]);
    announce(ctx, ctx.str.stillWorking);
    setState(ctx, "idle");
    updateSendToggle(ctx);
  }

  function langOptions(ctx) {
    var out = [];
    if (!ctx.langMenu || !ctx.langMenu.querySelectorAll) {
      return out;
    }
    var opts = ctx.langMenu.querySelectorAll("[data-composer-lang-option]");
    Array.prototype.forEach.call(opts, function (el) {
      var code = el.getAttribute ? el.getAttribute("data-code")
        : (el.dataset && el.dataset.code);
      if (code) {
        out.push({ code: code, label: el.textContent || code });
      }
    });
    return out;
  }

  /* Task 131: the session paused with a question for the seller
     (language_check). Polling STOPS here; the bubble shows the server's
     message, the transcript snippet when present, and the language
     buttons inline (or a "Choose language" link to the session page). */
  function showNeedsAction(ctx, bubble, data, finalUrl, statusUrl) {
    var msg = (data && (data.message || data.friendly)) || ctx.str.failed;
    var nodes = [makeEl("p", "composer-result", msg)];
    var quote = data && (data.quote || data.transcript);
    if (quote) {
      if (ctx.str.heard) {
        nodes.push(makeEl("p", "composer-heard-label", ctx.str.heard));
      }
      nodes.push(makeEl("blockquote", "composer-quote",
        String(quote).slice(0, 160)));
    }
    var postUrl = languagePostUrl(statusUrl);
    var options = postUrl ? langOptions(ctx) : [];
    if (options.length) {
      var row = makeEl("div", "composer-lang-row");
      options.forEach(function (opt) {
        var btn = makeEl("button", "composer-lang-pick", opt.label);
        btn.type = "button";
        btn.addEventListener("click", function () {
          answerLanguage(ctx, bubble, row, postUrl, statusUrl, finalUrl,
            opt.code);
        });
        row.appendChild(btn);
      });
      nodes.push(row);
    }
    var open = makeEl("a", "composer-cta", ctx.str.chooseLanguage);
    open.href = finalUrl;
    nodes.push(open);
    replaceBubble(bubble, nodes);
    announce(ctx, msg);
    setState(ctx, "idle");
    updateSendToggle(ctx);
  }

  function answerLanguage(ctx, bubble, row, postUrl, statusUrl, finalUrl,
      code) {
    var btns = row.querySelectorAll ? row.querySelectorAll("button") : [];
    Array.prototype.forEach.call(btns, function (btn) {
      btn.disabled = true;
    });
    applyLang(ctx, code);
    var form = new FormData();
    form.append("speak_lang", code);
    fetch(postUrl, {
      method: "POST",
      body: form,
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    }).then(function (response) {
      if (!response.ok) {
        throw new Error("language post failed");
      }
    }).then(function () {
      showHint(ctx, "");
      var fresh = addStatusBubble(ctx);
      var steps = fresh.firstChild;
      fresh.parentNode.removeChild(fresh);
      bubble.textContent = "";
      bubble.appendChild(steps);
      setState(ctx, "sending");
      pollStatus(ctx, bubble, statusUrl, finalUrl, 0);
    }).catch(function () {
      Array.prototype.forEach.call(btns, function (btn) {
        btn.disabled = false;
      });
      showHint(ctx, ctx.str.failed);
      announce(ctx, ctx.str.failed);
    });
  }

  function showFailed(ctx, bubble, message) {
    var line = makeEl("p", "composer-result",
      "⚠ " + (message || ctx.str.failed));
    var row = makeEl("div", "composer-retry-row");
    var retry = makeEl("button", "composer-retry", ctx.str.tryAgain);
    retry.type = "button";
    retry.addEventListener("click", function () {
      resend(ctx, bubble);
    });
    row.appendChild(retry);
    if (!ctx.lastSend || ctx.lastSend.kind !== "text") {
      var again = makeEl("button", "composer-retry", ctx.str.recordAgain);
      again.type = "button";
      again.addEventListener("click", function () {
        resetComposer(ctx);
      });
      row.appendChild(again);
    }
    replaceBubble(bubble, [line, row]);
    announce(ctx, message || ctx.str.failed);
    setState(ctx, "idle");
    updateSendToggle(ctx);
  }

  function resetComposer(ctx) {
    ctx.thread.textContent = "";
    ctx.lastSend = null;
    ctx.pendingBlob = null;
    ctx.hasText = false;
    if (ctx.textarea) {
      ctx.textarea.value = "";
      autogrow(ctx);
    }
    showHint(ctx, "");
    setState(ctx, "idle");
    if (ctx.mic && !ctx.mic.hidden) {
      ctx.mic.focus();
    } else if (ctx.textarea) {
      ctx.textarea.focus();
    }
  }

  function resend(ctx, bubble) {
    var last = ctx.lastSend;
    if (!last) {
      resetComposer(ctx);
      return;
    }
    setState(ctx, "sending");
    var fresh = addStatusBubble(ctx);
    var steps = fresh.firstChild;
    fresh.parentNode.removeChild(fresh);
    bubble.textContent = "";
    bubble.appendChild(steps);
    var form = new FormData();
    if (last.kind === "text") {
      collectFields(ctx, form, last.text);
    } else {
      collectFields(ctx, form);
      var blob = last.blob;
      var name = last.filename ||
        ("recording." + blobExt(blob));
      form.append(ctx.field, blob, name);
    }
    postForm(ctx, form, bubble);
  }

  function pollStatus(ctx, bubble, statusUrl, finalUrl, count) {
    if (count >= POLL_MAX) {
      showOpenLink(ctx, bubble, finalUrl);
      return;
    }
    fetch(statusUrl, { headers: { Accept: "application/json" },
      credentials: "same-origin" }).then(function (response) {
      if (!response.ok) {
        throw new Error("poll failed");
      }
      return response.json();
    }).then(function (data) {
      var view = statusView(data);
      if (view.kind === "failed") {
        showFailed(ctx, bubble, (data && data.message) || ctx.str.failed);
        return;
      }
      if (view.kind === "needs_action") {
        showNeedsAction(ctx, bubble, data, finalUrl, statusUrl);
        return;
      }
      if (view.kind === "done") {
        showDone(ctx, bubble, data, finalUrl);
        return;
      }
      setStep(bubble, view.step);
      window.setTimeout(function () {
        pollStatus(ctx, bubble, statusUrl, finalUrl, count + 1);
      }, POLL_MS);
    }).catch(function () {
      /* Status endpoint gone (or finished page): continue where we landed. */
      window.location.href = finalUrl;
    });
  }

  function postForm(ctx, form, bubble) {
    setStep(bubble, 0);
    fetch(ctx.form.action, {
      method: "POST",
      body: form,
      headers: { Accept: "text/html,application/json" },
      credentials: "same-origin",
    }).then(function (response) {
      var ctype = response.headers.get("content-type") || "";
      if (!response.ok) {
        return response.text().then(function (html) {
          throw { html: html }; // eslint-disable-line no-throw-literal
        });
      }
      if (ctype.indexOf("application/json") >= 0) {
        return response.json().then(function (data) {
          return { json: data, response: response };
        });
      }
      return response.text().then(function (html) {
        return { html: html, response: response };
      });
    }).then(function (out) {
      if (out.json) {
        var data = out.json || {};
        var target = data.url || data.redirect || out.response.url;
        var view = statusView(data);
        if (view.kind === "failed") {
          showFailed(ctx, bubble, data.message || ctx.str.failed);
        } else if (target && target !== window.location.href) {
          var statusUrl = statusUrlFor(target);
          if (statusUrl) {
            pollStatus(ctx, bubble, statusUrl, target, 0);
          } else {
            window.location.href = target;
          }
        } else if (view.kind === "done") {
          showDone(ctx, bubble, data, out.response.url);
        } else if (view.kind === "needs_action") {
          showNeedsAction(ctx, bubble, data, target || out.response.url,
            null);
        } else {
          /* Same-page JSON answer that is still working: poll it when
             possible, else link out — never print "Done" for it. */
          var sameUrl = statusUrlFor(target || out.response.url);
          if (sameUrl) {
            pollStatus(ctx, bubble, sameUrl, target || out.response.url, 0);
          } else {
            showOpenLink(ctx, bubble, target || out.response.url);
          }
        }
        return;
      }
      var finalUrl = out.response.url || ctx.form.action;
      var pollUrl = statusUrlFor(finalUrl);
      if (out.response.redirected && pollUrl) {
        pollStatus(ctx, bubble, pollUrl, finalUrl, 0);
      } else if (out.response.redirected) {
        /* Landed straight on the result (e.g. a typed quote): go there. */
        window.location.href = finalUrl;
      } else {
        /* Same-page answer (e.g. the price-update check screen): show it. */
        document.open();
        document.write(out.html);
        document.close();
      }
    }).catch(function (err) {
      var html = err && err.html;
      showFailed(ctx, bubble,
        html ? extractError(html, ctx.str.failed) : ctx.str.failed);
    });
  }

  function sendPending(ctx) {
    if (!ctx.pendingBlob) {
      setState(ctx, "idle");
      return;
    }
    if (!ctx.form.checkValidity()) {
      /* Keep the take; the browser points at the missing field. */
      ctx.form.reportValidity();
      setState(ctx, "ready");
      return;
    }
    var blob = ctx.pendingBlob;
    var seconds = ctx.pendingSeconds || 0;
    ctx.pendingBlob = null;
    setState(ctx, "sending");
    addUserAudioBubble(ctx, blob, seconds);
    announce(ctx, ctx.str.sent);
    var bubble = addStatusBubble(ctx);
    var form = new FormData();
    collectFields(ctx, form);
    form.append(ctx.field, blob, "recording." + blobExt(blob));
    ctx.lastSend = { kind: "audio", blob: blob, seconds: seconds };
    postForm(ctx, form, bubble);
  }

  function sendText(ctx) {
    if (!ctx.textarea) {
      return;
    }
    var value = ctx.textarea.value.trim();
    if (!value) {
      showHint(ctx, ctx.str.typeFirst);
      ctx.textarea.focus();
      return;
    }
    if (!ctx.form.checkValidity()) {
      ctx.form.reportValidity();
      return;
    }
    setState(ctx, "sending");
    addUserTextBubble(ctx, value);
    announce(ctx, ctx.str.sent);
    ctx.textarea.value = "";
    autogrow(ctx);
    ctx.hasText = false;
    var bubble = addStatusBubble(ctx);
    var form = new FormData();
    collectFields(ctx, form, value);
    ctx.lastSend = { kind: "text", text: value };
    postForm(ctx, form, bubble);
  }

  function fileTooBig(ctx, file) {
    return !!file && ctx.maxBytes > 0 && file.size > ctx.maxBytes;
  }

  /* Task 131: a blocked file (over data-max-bytes) shows its message in
     the thread with a way to pick another file — never fails silently. */
  function showBlocked(ctx, message) {
    var bubble = makeEl("div", "composer-bubble composer-bubble-status");
    bubble.appendChild(makeEl("p", "composer-result",
      "⚠ " + (message || ctx.str.failed)));
    var row = makeEl("div", "composer-retry-row");
    var again = makeEl("button", "composer-retry", ctx.str.tryAgain);
    again.type = "button";
    again.addEventListener("click", function () {
      bubble.parentNode.removeChild(bubble);
      openMenu(ctx);
    });
    row.appendChild(again);
    bubble.appendChild(row);
    ctx.thread.appendChild(bubble);
    scrollTo(bubble);
    announce(ctx, message || ctx.str.failed);
    setState(ctx, "idle");
    updateSendToggle(ctx);
  }

  function sendFile(ctx, file) {
    if (!file || !file.size) {
      return;
    }
    if (fileTooBig(ctx, file)) {
      closeMenu(ctx);
      showBlocked(ctx, ctx.str.tooBig);
      return;
    }
    if (!ctx.form.checkValidity()) {
      ctx.form.reportValidity();
      return;
    }
    closeMenu(ctx);
    setState(ctx, "sending");
    if (file.type.indexOf("audio/") === 0) {
      addUserAudioBubble(ctx, file, 0);
    } else {
      addUserTextBubble(ctx, file.name || ctx.str.sent);
    }
    announce(ctx, ctx.str.sent);
    var bubble = addStatusBubble(ctx);
    var form = new FormData();
    collectFields(ctx, form);
    form.append(ctx.field, file, file.name || ("upload." + blobExt(file)));
    ctx.lastSend = { kind: "file", blob: file, filename: file.name };
    postForm(ctx, form, bubble);
  }

  /* Task 131: spoken-language chip (seller pages). The hidden input
     carries speak_lang into every FormData via collectFields; the chip
     defaults to the shop language, else the last one used. */
  function storedLang() {
    try {
      if (window.localStorage) {
        return window.localStorage.getItem(LANG_STORE_KEY) || "";
      }
    } catch (err) {
      /* private mode: fall back to the shop default */
    }
    return "";
  }

  function rememberLang(code) {
    try {
      if (window.localStorage && code) {
        window.localStorage.setItem(LANG_STORE_KEY, code);
      }
    } catch (err) {
      /* private mode */
    }
  }

  function syncLangChip(ctx, code) {
    if (!ctx.langMenu || !ctx.langMenu.querySelectorAll) {
      return;
    }
    var opts = ctx.langMenu.querySelectorAll("[data-composer-lang-option]");
    Array.prototype.forEach.call(opts, function (el) {
      var elCode = el.getAttribute ? el.getAttribute("data-code")
        : (el.dataset && el.dataset.code);
      var on = elCode === code;
      if (el.setAttribute) {
        el.setAttribute("aria-selected", on ? "true" : "false");
      }
      if (on && ctx.langLabel) {
        ctx.langLabel.textContent = el.textContent;
      }
    });
  }

  function applyLang(ctx, code) {
    if (!code) {
      return;
    }
    if (ctx.langInput) {
      ctx.langInput.value = code;
    }
    syncLangChip(ctx, code);
    rememberLang(code);
  }

  function closeLangMenu(ctx) {
    if (!ctx.langMenu || !ctx.langChip) {
      return;
    }
    ctx.langMenu.hidden = true;
    ctx.langChip.setAttribute("aria-expanded", "false");
  }

  function initComposer(root) {
    if (!root || root.dataset.composerInit === "true") {
      return;
    }
    root.dataset.composerInit = "true";
    var form = root.querySelector("[data-composer-form]");
    if (!form) {
      return;
    }
    var data = root.dataset;
    var ctx = {
      root: root,
      form: form,
      thread: root.querySelector("[data-composer-thread]"),
      pill: root.querySelector("[data-composer-pill]"),
      plus: root.querySelector("[data-composer-plus]"),
      menu: root.querySelector("[data-composer-menu]"),
      langWrap: root.querySelector("[data-composer-lang]"),
      langChip: root.querySelector("[data-composer-lang-chip]"),
      langMenu: root.querySelector("[data-composer-lang-menu]"),
      langLabel: root.querySelector("[data-composer-lang-label]"),
      langInput: root.querySelector("[data-composer-lang-input]"),
      textarea: root.querySelector("[data-composer-text]"),
      wave: root.querySelector("[data-composer-wave]"),
      timer: root.querySelector("[data-composer-timer]"),
      mic: root.querySelector("[data-composer-mic]"),
      send: root.querySelector("[data-composer-send]"),
      cancel: root.querySelector("[data-composer-cancel]"),
      hint: root.querySelector("[data-composer-hint]"),
      live: root.querySelector("[data-composer-live]"),
      nojs: root.querySelector("[data-composer-nojs]"),
      field: data.field || "audio",
      textField: data.textField || "",
      maxSeconds: parseInt(data.maxSeconds || "120", 10) || 120,
      maxBytes: parseInt(data.maxBytes || "0", 10) || 0,
      doneLabel: data.doneLabel || "",
      str: {
        recording: data.strRecording || "Recording…",
        sending: data.strSending || "Sending…",
        listening: data.strListening || "Listening…",
        understanding: data.strUnderstanding || "Understanding…",
        done: data.strDone || "Done",
        tryAgain: data.strTryAgain || "Try again",
        recordAgain: data.strRecordAgain || "Record again",
        httpsHint: data.strHttpsHint || "",
        secondsLeft: data.strSecondsLeft || "{n} seconds left",
        limitReached: data.strLimitReached || "",
        typeFirst: data.strTypeFirst || "",
        failed: data.strFailed || "Something went wrong.",
        sent: data.strSent || "Sent",
        play: data.strPlay || "Play",
        pause: data.strPause || "Pause",
        chooseLanguage: data.strChooseLanguage || "Choose language",
        tooBig: data.strTooBig || "That file is too big to upload.",
        stillWorking: data.strStillWorking || "Still working.",
        heard: data.strHeard || "",
      },
      state: "idle",
      hasText: false,
      recorder: null,
      stream: null,
      audioCtx: null,
      analyser: null,
      chunks: [],
      timerId: 0,
      waveRaf: 0,
      waveBars: [],
      startedAt: 0,
      cancelled: false,
      autoStopped: false,
      pendingBlob: null,
      pendingSeconds: 0,
      lastSend: null,
    };

    /* JS is running: the dropdown replaces the static fallback row. */
    root.classList.add("is-js");
    if (ctx.nojs) {
      ctx.nojs.hidden = true;
    }
    if (ctx.menu) {
      ctx.menu.hidden = true;
    }
    if (ctx.plus) {
      ctx.plus.hidden = false;
    }
    if (ctx.mic) {
      ctx.mic.hidden = false;
    }
    var files = root.querySelectorAll("[data-composer-file]");
    Array.prototype.forEach.call(files, function (input) {
      input.disabled = false;
      input.required = false;
      input.addEventListener("change", function () {
        if (input.files && input.files[0]) {
          sendFile(ctx, input.files[0]);
          input.value = "";
        }
      });
    });
    var videoOnly = root.querySelectorAll("[data-composer-video-only]");
    Array.prototype.forEach.call(videoOnly, function (label) {
      label.hidden = false;
    });

    if (ctx.plus) {
      ctx.plus.addEventListener("click", function (event) {
        event.stopPropagation();
        closeLangMenu(ctx);
        toggleMenu(ctx);
      });
    }
    document.addEventListener("click", function (event) {
      if (ctx.menu && !ctx.menu.hidden && !root.contains(event.target)) {
        closeMenu(ctx);
      }
      if (ctx.langMenu && !ctx.langMenu.hidden && ctx.langWrap &&
          !ctx.langWrap.contains(event.target)) {
        closeLangMenu(ctx);
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeMenu(ctx);
        closeLangMenu(ctx);
      }
    });

    if (ctx.langChip && ctx.langMenu && ctx.langInput) {
      var saved = storedLang();
      if (saved) {
        var validCodes = langOptions(ctx).map(function (opt) {
          return opt.code;
        });
        if (validCodes.indexOf(saved) >= 0) {
          ctx.langInput.value = saved;
          syncLangChip(ctx, saved);
        }
      }
      ctx.langChip.addEventListener("click", function (event) {
        event.stopPropagation();
        closeMenu(ctx);
        var open = ctx.langMenu.hidden;
        ctx.langMenu.hidden = !open;
        ctx.langChip.setAttribute("aria-expanded", open ? "true" : "false");
      });
      var langOpts = ctx.langMenu.querySelectorAll(
        "[data-composer-lang-option]");
      Array.prototype.forEach.call(langOpts, function (el) {
        el.addEventListener("click", function (event) {
          event.stopPropagation();
          var code = el.getAttribute ? el.getAttribute("data-code")
            : (el.dataset && el.dataset.code);
          applyLang(ctx, code);
          closeLangMenu(ctx);
        });
      });
    }

    if (ctx.textarea) {
      autogrow(ctx);
      ctx.textarea.addEventListener("input", function () {
        autogrow(ctx);
        updateSendToggle(ctx);
      });
      ctx.textarea.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          if (ctx.state === "idle") {
            sendText(ctx);
          }
        }
      });
    }

    if (ctx.mic) {
      ctx.mic.addEventListener("click", function () {
        if (ctx.state === "idle") {
          startRecording(ctx);
        }
      });
    }
    if (ctx.cancel) {
      ctx.cancel.addEventListener("click", function () {
        if (ctx.state === "recording") {
          cancelRecording(ctx);
        } else if (ctx.state === "ready") {
          ctx.pendingBlob = null;
          setState(ctx, "idle");
          showHint(ctx, "");
          updateSendToggle(ctx);
        }
      });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (ctx.state === "recording") {
        stopAndSend(ctx);
      } else if (ctx.state === "ready") {
        sendPending(ctx);
      } else if (ctx.state === "idle") {
        sendText(ctx);
      }
    });

    setState(ctx, "idle");
  }

  function initAll() {
    var roots = document.querySelectorAll("[data-composer]");
    Array.prototype.forEach.call(roots, initComposer);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }

  window.initComposer = initComposer;
  /* Task 131: pure helpers for the node unit tests (still one global). */
  initComposer.testHooks = {
    statusView: statusView,
    stepForStage: stepForStage,
    isDoneData: isDoneData,
    isNeedsAction: isNeedsAction,
    languagePostUrl: languagePostUrl,
    collectFields: collectFields,
    fileTooBig: fileTooBig,
  };
})();
