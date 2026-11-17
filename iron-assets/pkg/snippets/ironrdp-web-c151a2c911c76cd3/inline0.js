
export class WebCodecsDecoder {
  constructor() {
    this.canvas = new OffscreenCanvas(1, 1);
    this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
    this.frame = null;
    this.width = 0;
    this.height = 0;
    this.error = null;
    this.ok = false;
    this.ts = 0;
    this.reset();
  }

  reset() {
    if (this.decoder) { try { this.decoder.close(); } catch (e) {} }
    this.frame = null;
    this.error = null;
    this.ok = false;
    const self = this;
    try {
      this.decoder = new VideoDecoder({
        output(frame) {
          try {
            if (self.canvas.width !== frame.displayWidth || self.canvas.height !== frame.displayHeight) {
              self.canvas.width = frame.displayWidth;
              self.canvas.height = frame.displayHeight;
            }
            self.ctx.drawImage(frame, 0, 0);
            const img = self.ctx.getImageData(0, 0, self.canvas.width, self.canvas.height);
            self.frame = new Uint8Array(img.data.buffer);
            self.width = frame.displayWidth;
            self.height = frame.displayHeight;
          } catch (e) {
            self.error = String(e);
            console.error('WebCodecs H264 output error', String(e));
          }
          frame.close();
        },
        error(e) { self.error = String(e); console.error('WebCodecs H264 error', String(e)); }
      });
      this.decoder.configure({
        codec: 'avc1.42001f',
        hardwareAcceleration: 'prefer-hardware',
        optimizeForLatency: true
      });
      this.ok = true;
    } catch (e) {
      this.error = String(e);
      console.error('WebCodecs H264 configure error', String(e));
    }
  }

  decode(data) {
    if (!this.ok) return false;
    let key = false;
    for (let i = 0; i + 4 < data.length; i++) {
      if (data[i] === 0 && data[i + 1] === 0 && data[i + 2] === 1 && (data[i + 3] & 0x1f) === 5) { key = true; break; }
      if (data[i] === 0 && data[i + 1] === 0 && data[i + 2] === 0 && data[i + 3] === 1 && (data[i + 4] & 0x1f) === 5) { key = true; break; }
    }
    this.ts += 1;
    try {
      this.decoder.decode(new EncodedVideoChunk({
        type: key ? 'key' : 'delta',
        timestamp: this.ts * 1000,
        data: data
      }));
      return true;
    } catch (e) {
      this.error = String(e);
      console.error('WebCodecs H264 decode error', String(e));
      return false;
    }
  }

  pop() { const f = this.frame; this.frame = null; return f; }
  w() { return this.width; }
  h() { return this.height; }
  ready() { return this.ok; }
  lastError() { return this.error; }
}
