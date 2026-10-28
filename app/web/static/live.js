"use strict";
/* Live prices: camera preview + mic PCM relay over our WebSocket. */

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
  const fallback = root.querySelector("[data-live-fallback]");
  const mainCols = root.querySelector(".live-columns");

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

  function renderCards(items) {
    if (!items) {
      return;
    }
    if (emptyNote) {
      emptyNote.hidden = items.length > 0;
    }
    const seen = new Set();
    items.forEach((item) => {
      seen.add(item.key);
      let card = cards.get(item.key);
      if (!card) {
        card = document.createElement("div");
        card.className = "list-row live-card";
        card.dataset.key = item.key;
        cardsBox.appendChild(card);
        cards.set(item.key, card);
      }
      card.innerHTML = "";
      if (item.photo_url) {
        const img = document.createElement("img");
        img.className = "list-thumb";
        img.src = item.photo_url;
        img.alt = "";
        card.appendChild(img);
      } else {
        const span = document.createElement("span");
        span.className = "list-thumb";
        span.textContent = "•";
        card.appendChild(span);
      }
      const main = document.createElement("div");
      main.className = "list-main";
      const name = document.createElement("span");
      name.className = "list-name";
      name.textContent = item.name_local || item.name_en;
      main.appendChild(name);
      const sub = document.createElement("span");
      sub.className = "list-sub";
      sub.textContent = item.variety ? item.name_en + " (" + item.variety + ")" : item.name_en;
      main.appendChild(sub);
      if (item.needs_check) {
        const pill = document.createElement("span");
        pill.className = "pill pill-check";
        pill.textContent = "check";
        main.appendChild(pill);
      }
      card.appendChild(main);
      const price = document.createElement("div");
      price.className = "list-price";
      (item.price_lines || []).forEach((line) => {
        const row = document.createElement("span");
        row.textContent = priceText(line);
        price.appendChild(row);
      });
      card.appendChild(price);
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
    micBtn.classList.toggle("is-recording", on);
    micBtn.setAttribute("aria-label", on ? "Stop live prices" : "Start live prices");
    badge.hidden = !on;
    timerEl.hidden = !on;
    if (readyEl) {
      readyEl.hidden = on;
    }
    hint.textContent = on
      ? "Listening… say each item and its price, then tap to stop."
      : "Tap to start. Point at your stall and say each price.";
  }

  function showFinishing() {
    badge.hidden = true;
    timerEl.hidden = true;
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
      partialEl.textContent = data.text || "";
    } else if (data.type === "speech_start") {
      grabFrame(data.turn_id, "start");
    } else if (data.type === "turn") {
      lastEl.textContent = data.text || "";
      partialEl.textContent = "";
      grabFrame(data.turn_id, "end");
    } else if (data.type === "items") {
      renderCards(data.items || []);
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
      socket.send(JSON.stringify({ type: "start", kind: "prices" }));
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

  micBtn.addEventListener("click", () => {
    if (recording) {
      stop();
    } else {
      stopping = false;
      start();
    }
  });
});
