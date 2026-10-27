"use strict";
/* Voice price update: record with MediaRecorder, upload the blob for checking. */

document.addEventListener("DOMContentLoaded", () => {
  const startBtn = document.getElementById("rec-start");
  const stopBtn = document.getElementById("rec-stop");
  const status = document.getElementById("rec-status");
  if (!startBtn || !stopBtn) {
    return;
  }
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    status.textContent =
      "Recording is not supported in this browser — upload a file instead.";
    startBtn.disabled = true;
    return;
  }
  let recorder = null;
  let chunks = [];

  async function upload(blob) {
    const ext =
      blob.type.includes("mp4") || blob.type.includes("m4a") ? "m4a" : "webm";
    const form = new FormData();
    form.append("audio", blob, `update.${ext}`);
    startBtn.disabled = true;
    stopBtn.disabled = true;
    try {
      const response = await fetch(window.location.pathname, {
        method: "POST",
        body: form,
      });
      document.open();
      document.write(await response.text());
      document.close();
    } catch (err) {
      status.textContent = "Upload failed — try again.";
      startBtn.disabled = false;
    }
  }

  startBtn.addEventListener("click", async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const options = {};
      if (MediaRecorder.isTypeSupported("audio/webm")) {
        options.mimeType = "audio/webm";
      } else if (MediaRecorder.isTypeSupported("audio/mp4")) {
        options.mimeType = "audio/mp4";
      }
      chunks = [];
      recorder = new MediaRecorder(stream, options);
      recorder.ondataavailable = (event) => {
        if (event.data.size) {
          chunks.push(event.data);
        }
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        upload(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
      };
      recorder.start();
      startBtn.disabled = true;
      stopBtn.disabled = false;
      status.textContent = "Recording… say the new prices, then tap Stop.";
    } catch (err) {
      status.textContent = "Microphone unavailable — upload a file instead.";
    }
  });

  stopBtn.addEventListener("click", () => {
    if (recorder && recorder.state !== "inactive") {
      status.textContent = "Checking what you said…";
      recorder.stop();
    }
  });
});
