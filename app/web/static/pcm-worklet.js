/* Live prices PCM worklet: float32 -> 16-bit PCM mono at 24 kHz.
   Posts ~80 ms frames (1920 samples) as ArrayBuffers. */

class LivePCM extends AudioWorkletProcessor {
  constructor() {
    super();
    this._inRate = sampleRate;
    this._outRate = 24000;
    this._carry = [];
    this._phase = 0;
    this._out = [];
    this._frame = 1920;
  }

  _pushInput(samples) {
    for (let i = 0; i < samples.length; i += 1) {
      this._carry.push(samples[i]);
    }
    // Resample with linear interpolation.
    const step = this._inRate / this._outRate;
    let pos = this._phase;
    while (pos + 1 < this._carry.length) {
      const idx = Math.floor(pos);
      const frac = pos - idx;
      const a = this._carry[idx];
      const b = this._carry[idx + 1];
      const sample = a + (b - a) * frac;
      const clamped = Math.max(-1, Math.min(1, sample));
      this._out.push(clamped < 0 ? Math.round(clamped * 32768) : Math.round(clamped * 32767));
      pos += step;
      if (this._out.length >= this._frame) {
        const chunk = new Int16Array(this._out.slice(0, this._frame));
        this.port.postMessage(chunk.buffer, [chunk.buffer]);
        this._out = this._out.slice(this._frame);
      }
    }
    const consumed = Math.floor(pos);
    if (consumed > 0) {
      this._carry = this._carry.slice(consumed);
      this._phase = pos - consumed;
    } else {
      this._phase = pos;
    }
    if (this._carry.length > this._inRate * 2) {
      this._carry = this._carry.slice(-this._inRate);
    }
  }

  process(inputs) {
    const channel = inputs && inputs[0] && inputs[0][0];
    if (channel && channel.length) {
      this._pushInput(channel);
    }
    return true;
  }
}

registerProcessor("live-pcm", LivePCM);
