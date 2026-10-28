"use strict";
/* Live order billing (Task 36): mic PCM relay, captions, live bill/quote lines.
   Seller bills use kind "bill" on the Task 35 relay; customer quotes use
   kind "quote" on the public shop socket. No camera. */

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("[data-live-order]");
  if (!root) {
    return;
  }
  const wsPath = root.dataset.wsUrl || "";
  const kind = root.dataset.kind || "bill";
  const micBtn = root.querySelector("[data-live-order-mic]");
  const hint = root.querySelector("[data-live-order-hint]");
  const lastEl = root.querySelector("[data-live-order-last]");
  const partialEl = root.querySelector("[data-live-order-partial]");
  const errorBox = root.querySelector("[data-live-order-error]");
  const linesBox = root.querySelector("[data-live-order-lines]");
  const listEl = root.querySelector("[data-live-order-list]");
  const totalEl = root.querySelector("[data-live-order-total]");
  const doneBtn = root.querySelector("[data-live-order-done]");

  if (!window.WebSocket || !navigator.mediaDevices
      || !navigator.mediaDevices.getUserMedia) {
    if (hint) {
      hint.textContent = "Live mode is not supported in this browser — use the upload below.";
    }
    if (micBtn) {
      micBtn.disabled = true;
    }
    return;
  }

  let ws = null;
  let stream = null;
  let audioCtx = null;
  let workletNode = null;
  let recording = false;
  let stopping = false;

  function showError(message) {
    if (!errorBox) {
      return;
    }
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function clearError() {
    if (!errorBox) {
      return;
    }
    errorBox.textContent = "";
    errorBox.hidden = true;
  }

  function wsUrl() {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    return scheme + "://" + window.location.host + wsPath;
  }

  function money(value) {
    if (value === null || value === undefined || value === "") {
      return "—";
    }
    return "₹" + value;
  }

  function renderLines(lines, total) {
    if (!linesBox || !listEl) {
      return;
    }
    listEl.innerHTML = "";
    (lines || []).forEach((line) => {
      const row = document.createElement("div");
      row.className = "list-row";
      const main = document.createElement("div");
      main.className = "list-main";
      const name = document.createElement("span");
      name.className = "list-name";
      name.textContent = line.display || line.name_en;
      main.appendChild(name);
      const sub = document.createElement("span");
      sub.className = "list-sub";
      if (line.status === "sold_out") {
        sub.textContent = "sold out";
      } else if (line.status === "not_on_list") {
        sub.textContent = "not on list";
      } else if (line.note) {
        sub.textContent = line.note;
      } else {
        sub.textContent = (line.qty || "") + " " + (line.unit || "");
      }
      main.appendChild(sub);
      row.appendChild(main);
      const price = document.createElement("div");
      price.className = "list-price";
      price.textContent = money(line.line_total);
      row.appendChild(price);
      listEl.appendChild(row);
    });
    if (totalEl) {
      totalEl.textContent = money(total);
    }
    linesBox.hidden = !(lines && lines.length);
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
  }

  function setRecording(on) {
    recording = on;
    micBtn.classList.toggle("is-recording", on);
    micBtn.setAttribute("aria-label", on ? "Stop" : "Start live billing");
    if (doneBtn) {
      doneBtn.hidden = !on;
    }
    if (hint) {
      hint.textContent = on
        ? "Listening… say the order, then tap Done."
        : "Tap to start. Lines appear as you speak.";
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
      startAudio(ws, stream).catch(() => {
        showError("Microphone audio failed to start. Please reload and try again.");
      });
    } else if (data.type === "partial") {
      if (partialEl) {
        partialEl.textContent = data.text || "";
      }
    } else if (data.type === "turn") {
      if (lastEl) {
        lastEl.textContent = data.text || "";
      }
      if (partialEl) {
        partialEl.textContent = "";
      }
    } else if (data.type === "bill_lines" || data.type === "quote_lines") {
      renderLines(data.lines || [], data.total);
    } else if (data.type === "done") {
      cleanupMedia();
      window.location.href = data.bill_url || data.quote_url || data.review_url || "/";
    } else if (data.type === "error") {
      showError(data.message || "Live mode stopped. Please try again.");
    }
  }

  async function start() {
    clearError();
    micBtn.disabled = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      micBtn.disabled = false;
      if (err && (err.name === "NotAllowedError" || err.name === "SecurityError")) {
        showError("Microphone is blocked. Tap the lock icon in the address bar, allow the microphone, then reload and try again.");
      } else {
        showError("Could not open the microphone. Please check it is connected, then try again.");
      }
      return;
    }
    const socket = new WebSocket(wsUrl());
    ws = socket;
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      socket.send(JSON.stringify({ type: "start", kind: kind }));
      setRecording(true);
      micBtn.disabled = false;
    };
    socket.onmessage = onSocketMessage;
    socket.onerror = () => {
      if (!stopping) {
        showError("Connection lost. Check your network, then try again.");
      }
    };
    socket.onclose = () => {
      if (recording && !stopping) {
        showError("Connection lost. Check your network, then try again.");
        setRecording(false);
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
    if (doneBtn) {
      doneBtn.disabled = true;
    }
    try {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "stop" }));
      }
    } catch (err) { /* ignore */ }
    if (hint) {
      hint.textContent = "Finishing… making your bill.";
    }
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
  if (doneBtn) {
    doneBtn.addEventListener("click", stop);
  }
});
