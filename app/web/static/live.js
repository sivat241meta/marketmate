"use strict";
/* Live prices: camera preview + mic PCM relay over our WebSocket. */

function firstGrapheme(name) {
  const text = (name || "").trim();
  if (!text) {
    return "";
  }
  if (typeof Intl !== "undefined" && Intl.Segmenter) {
    const parts = new Intl.Segmenter(
      undefined, { granularity: "grapheme" }).segment(text);
    for (const part of parts) {
      return part.segment.toUpperCase();
    }
  }
  const match = /^\P{Mark}\p{Mark}*/u.exec(text);
  return (match ? match[0] : text[0]).toUpperCase();
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("[data-live]");
  if (!root) {
    return;
  }
  const token = root.dataset.token;
  const video = root.querySelector("[data-live-video]");
  const canvas = root.querySelector("[data-live-canvas]");
  const micBtn = root.querySelector("[data-live-mic]");
  const hint = root.querySelector("[data-live-hint]");
  const badge = root.querySelector("[data-live-badge]");
  const readyEl = root.querySelector("[data-live-ready]");
  const timerEl = root.querySelector("[data-live-timer]");
  const lastEl = root.querySelector("[data-live-last]");
  const partialEl = root.querySelector("[data-live-partial]");
  const errorBox = root.querySelector("[data-live-error]");
  const finishBox = root.querySelector("[data-live-finish]");
  const elapsedEl = root.querySelector("[data-live-elapsed]");
  const offlineBox = root.querySelector("[data-live-offline]");
  const cardsBox = root.querySelector("[data-live-cards]");
  const emptyNote = root.querySelector("[data-live-empty]");
  const countEl = root.querySelector("[data-live-count]");
  const micIcon = root.querySelector("[data-live-mic-icon]");
  const stopIcon = root.querySelector("[data-live-stop-icon]");
  const stopLabel = root.querySelector("[data-live-stop-label]");
  const fallback = root.querySelector("[data-live-fallback]");
  const mainCols = root.querySelector(".live-columns");
  const speakSelect = root.querySelector("[data-live-speak]");
  const scriptBox = root.querySelector("[data-live-script]");
  const scriptText = root.querySelector("[data-live-script-text]");
  const scriptSpeak = root.querySelector("[data-live-script-speak]");

  function showFallback() {
    if (fallback) {
      fallback.hidden = false;
    }
    if (mainCols) {
      mainCols.hidden = true;
    }
  }

  if (!window.WebSocket || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showFallback();
    return;
  }

  let ws = null;
  let stream = null;
  let audioCtx = null;
  let workletNode = null;
  let recording = false;
  let stopping = false;
  let sessionId = null;
  let timerId = null;
  let startedAt = 0;
  let finishTimerId = null;
  let finishStartedAt = 0;
  const cards = new Map();

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function clearError() {
    errorBox.textContent = "";
    errorBox.hidden = true;
  }

  function fmtTime(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    return Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0");
  }

  function startTimer() {
    startedAt = Date.now();
    timerEl.textContent = "0:00";
    timerId = window.setInterval(() => {
      timerEl.textContent = fmtTime(Date.now() - startedAt);
    }, 500);
  }

  function stopTimer() {
    if (timerId) {
      window.clearInterval(timerId);
      timerId = null;
    }
  }

  function wsUrl() {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    return scheme + "://" + window.location.host + "/e/" + token + "/live/ws";
  }

  function grabFrame(turn, at) {
    try {
      if (!video || !video.videoWidth) {
        return;
      }
      const maxW = 960;
      const scale = Math.min(1, maxW / video.videoWidth);
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      const ctx = canvas.getContext("2d");
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const url = canvas.toDataURL("image/jpeg", 0.7);
      const jpeg = url.split(",", 2)[1] || "";
      if (jpeg && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "frame", turn: turn, at: at, jpeg: jpeg }));
      }
    } catch (err) {
      /* a missed frame must not stop the session */
    }
  }

  function priceText(line) {
    const price = line.price === null || line.price === undefined ? "—" : "₹" + line.price;
    if (line.per_amount && line.unit) {
      return price + " / " + line.per_amount + " " + line.unit;
    }
    if (line.unit) {
      return price + " / " + line.unit;
    }
    return price;
  }

  function escHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function setCaption(el, text) {
    if (!el) {
      return;
    }
    const clean = (text || "").trim();
    if (!clean) {
      el.textContent = "";
      return;
    }
    const words = clean.split(/(\s+)/);
    let idx = words.length - 1;
    while (idx >= 0 && /^\s*$/.test(words[idx])) {
      idx -= 1;
    }
    el.innerHTML = words.map((word, at) =>
      (at === idx ? "<mark>" + escHtml(word) + "</mark>" : escHtml(word))
    ).join("");
  }

  function renderCards(items) {
    if (!items) {
      return;
    }
    if (emptyNote) {
      emptyNote.hidden = items.length > 0;
    }
    if (countEl) {
      countEl.textContent = String(items.length);
    }
    const seen = new Set();
    items.forEach((item) => {
      seen.add(item.key);
      let card = cards.get(item.key);
      if (!card) {
        card = document.createElement("div");
        card.className = "heard live-card";
        card.dataset.key = item.key;
        cardsBox.appendChild(card);
        cards.set(item.key, card);
      }
      card.className = item.needs_check ? "heard need live-card" : "heard live-card";
      card.innerHTML = "";
      if (item.photo_url) {
        const img = document.createElement("img");
        img.src = item.photo_url;
        img.alt = "";
        card.appendChild(img);
      } else {
        const span = document.createElement("span");
        span.className = "nophoto";
        const grapheme = document.createElement("span");
        grapheme.className = "til-g";
        grapheme.textContent = firstGrapheme(
          item.name_local || item.name_en || "?");
        span.appendChild(grapheme);
        if (item.variety) {
          const sub = document.createElement("span");
          sub.className = "til-v";
          sub.textContent = item.variety;
          span.appendChild(sub);
        }
        card.appendChild(span);
      }
      const main = document.createElement("div");
      main.className = "n";
      const name = document.createElement("b");
      name.textContent = item.name_local || item.name_en;
      main.appendChild(name);
      const sub = document.createElement("small");
      const first = (item.price_lines || [])[0] || {};
      let detail = item.variety ? item.name_en + " (" + item.variety + ")" : item.name_en;
      if (first.unit) {
        detail += " · per " + first.unit;
      }
      sub.textContent = detail;
      main.appendChild(sub);
      card.appendChild(main);
      const price = document.createElement("span");
      price.className = "p";
      price.textContent = (item.price_lines || []).length
        ? priceText((item.price_lines || [])[0]) : "—";
      card.appendChild(price);
      const mark = document.createElement("span");
      if (item.needs_check) {
        mark.className = "ask";
        mark.textContent = "?";
      } else {
        mark.className = "ok";
        mark.textContent = "✓";
      }
      card.appendChild(mark);
    });
    cards.forEach((card, key) => {
      if (!seen.has(key)) {
        card.remove();
        cards.delete(key);
      }
    });
  }

  function cleanupMedia() {
    if (workletNode) {
      try {
        workletNode.disconnect();
      } catch (err) { /* ignore */ }
      workletNode = null;
    }
    if (audioCtx) {
      audioCtx.close().catch(() => {});
      audioCtx = null;
    }
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }
    if (video) {
      video.srcObject = null;
    }
  }

  function setRecording(on) {
    recording = on;
    if (speakSelect) {
      speakSelect.disabled = on;
    }
    micBtn.classList.toggle("is-recording", on);
    micBtn.setAttribute("aria-label", on ? "Stop live prices" : "Start live prices");
    badge.hidden = !on;
    if (micIcon) {
      micIcon.hidden = on;
    }
    if (stopIcon) {
      stopIcon.hidden = !on;
    }
    if (stopLabel) {
      stopLabel.hidden = !on;
    }
    if (readyEl) {
      readyEl.hidden = on;
    }
    hint.textContent = on
      ? "Listening… say each item and its price, then tap to stop."
      : "Tap to start. Point at your stall and say each price.";
  }

  function showFinishing() {
    badge.hidden = true;
    stopTimer();
    finishBox.hidden = false;
    hint.textContent = "Finishing – checking every price…";
    if (elapsedEl) {
      finishStartedAt = Date.now();
      elapsedEl.hidden = false;
      elapsedEl.textContent = "0 s";
      if (finishTimerId) {
        window.clearInterval(finishTimerId);
      }
      finishTimerId = window.setInterval(() => {
        const secs = Math.max(0, Math.floor((Date.now() - finishStartedAt) / 1000));
        elapsedEl.textContent = secs + " s";
      }, 500);
    }
  }

  async function startAudio(wsSocket, mediaStream) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const workletUrl = root.dataset.worklet || "/static/pcm-worklet.js";
    await audioCtx.audioWorklet.addModule(workletUrl);
    const source = audioCtx.createMediaStreamSource(mediaStream);
    workletNode = new AudioWorkletNode(audioCtx, "live-pcm", {
      numberOfInputs: 1,
      numberOfOutputs: 0,
    });
    workletNode.port.onmessage = (event) => {
      if (wsSocket.readyState === WebSocket.OPEN && !stopping) {
        wsSocket.send(event.data);
      }
    };
    source.connect(workletNode);
    if (audioCtx.state === "suspended") {
      await audioCtx.resume();
    }
  }

  function onSocketMessage(event) {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (err) {
      return;
    }
    if (data.type === "ready") {
      sessionId = data.session_id;
      startAudio(ws, stream).catch(() => {
        showError("Microphone audio failed to start. Please reload and try again.");
      });
      startTimer();
    } else if (data.type === "partial") {
      setCaption(partialEl, data.text || "");
    } else if (data.type === "speech_start") {
      grabFrame(data.turn_id, "start");
    } else if (data.type === "turn") {
      setCaption(lastEl, data.text || "");
      setCaption(partialEl, "");
      grabFrame(data.turn_id, "end");
    } else if (data.type === "items") {
      renderCards(data.items || []);
    } else if (data.type === "script_warn") {
      if (scriptBox) {
        if (scriptText) {
          scriptText.textContent = data.message || "";
        }
        scriptBox.hidden = false;
      }
    } else if (data.type === "relang_ok") {
      if (scriptBox) {
        scriptBox.hidden = true;
      }
      if (data.language) {
        if (speakSelect) {
          speakSelect.value = data.language;
        }
        if (scriptSpeak) {
          scriptSpeak.value = data.language;
        }
      }
    } else if (data.type === "timeout") {
      if (!stopping) {
        stopping = true;
        micBtn.disabled = true;
        showFinishing();
      }
    } else if (data.type === "done") {
      stopTimer();
      if (finishTimerId) {
        window.clearInterval(finishTimerId);
        finishTimerId = null;
      }
      cleanupMedia();
      window.location.href = data.review_url;
    } else if (data.type === "error") {
      showError(data.message || "Live mode stopped. Please try again.");
      if (!stopping) {
        offlineBox.hidden = false;
      }
    }
  }

  async function start() {
    clearError();
    offlineBox.hidden = true;
    if (scriptBox) {
      scriptBox.hidden = true;
    }
    micBtn.disabled = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
        audio: true,
      });
    } catch (err) {
      micBtn.disabled = false;
      if (err && (err.name === "NotAllowedError" || err.name === "SecurityError")) {
        showError("Camera or microphone is blocked. Tap the lock icon in the address bar, allow camera and microphone for this site, then reload and try again.");
      } else if (err && err.name === "NotFoundError") {
        showError("No camera or microphone was found on this device. You can upload a video instead.");
        offlineBox.hidden = false;
      } else {
        showError("Could not open the camera or microphone. Please check they are connected, then try again.");
      }
      return;
    }
    video.srcObject = stream;
    video.play().catch(() => {});
    const socket = new WebSocket(wsUrl());
    ws = socket;
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      socket.send(JSON.stringify({
        type: "start",
        kind: "prices",
        speak_lang: speakSelect ? speakSelect.value : "",
      }));
      setRecording(true);
      micBtn.disabled = false;
    };
    socket.onmessage = onSocketMessage;
    socket.onerror = () => {
      if (!stopping) {
        showError("Connection lost. Check your network, then try again.");
        offlineBox.hidden = false;
      }
    };
    socket.onclose = () => {
      if (recording && !stopping) {
        showError("Connection lost. Check your network, then try again.");
        offlineBox.hidden = false;
        setRecording(false);
        stopTimer();
        cleanupMedia();
      }
    };
  }

  async function stop() {
    if (!recording || stopping) {
      return;
    }
    stopping = true;
    micBtn.disabled = true;
    try {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "stop" }));
      }
    } catch (err) { /* ignore */ }
    showFinishing();
    window.setTimeout(() => {
      if (stopping) {
        cleanupMedia();
      }
    }, 20000);
  }

  if (scriptSpeak) {
    scriptSpeak.addEventListener("change", () => {
      if (speakSelect) {
        speakSelect.value = scriptSpeak.value;
      }
      if (ws && ws.readyState === WebSocket.OPEN && recording && !stopping) {
        ws.send(JSON.stringify({
          type: "relang",
          speak_lang: scriptSpeak.value,
        }));
      }
      if (scriptBox) {
        scriptBox.hidden = true;
      }
    });
  }

  micBtn.addEventListener("click", () => {
    if (recording) {
      stop();
    } else {
      stopping = false;
      start();
    }
  });
});
