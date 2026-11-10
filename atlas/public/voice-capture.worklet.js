// Atlas microphone capture. Runs on the audio thread and hands blocks of samples to the page,
// where they are held in memory only until the local recogniser has read them.
class AtlasCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(2048);
    this.filled = 0;
    this.active = true;
    this.port.onmessage = (e) => {
      if (e.data === "stop") {
        this.active = false;
        this.buffer.fill(0);
      }
    };
  }

  process(inputs) {
    if (!this.active) return false;
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    let offset = 0;
    while (offset < channel.length) {
      const n = Math.min(channel.length - offset, this.buffer.length - this.filled);
      this.buffer.set(channel.subarray(offset, offset + n), this.filled);
      this.filled += n;
      offset += n;
      if (this.filled === this.buffer.length) {
        const out = this.buffer;
        this.port.postMessage(out, [out.buffer]);
        this.buffer = new Float32Array(2048);
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("atlas-capture", AtlasCapture);
