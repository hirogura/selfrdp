
export class WebCodecsDecoder {
  constructor() {
    this.canvas = new OffscreenCanvas(1, 1);
    this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
    this.frame = null;
    this.yuv = null;
    this.yuvTs = -1;
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
    this.yuv = null;
    this.yuvTs = -1;
    this.error = null;
    this.ok = false;
    const self = this;
    try {
      this.decoder = new VideoDecoder({
        async output(frame) {
          const ts = frame.timestamp;
          try {
            const w = frame.displayWidth, h = frame.displayHeight;
            if (self.canvas.width !== w || self.canvas.height !== h) {
              self.canvas.width = w;
              self.canvas.height = h;
            }
            self.ctx.drawImage(frame, 0, 0);
            const img = self.ctx.getImageData(0, 0, w, h);
            if (ts >= self.yuvTs) {
              self.yuvTs = ts;
              self.frame = new Uint8Array(img.data.buffer);
              self.width = w;
              self.height = h;
            }
            // Also expose YUV 4:2:0 planes for AVC444 / correct color conversion.
            const lw = w;
            const cw = Math.ceil(w / 2);
            const ch = Math.ceil(h / 2);
            const ys = lw * h, cs = cw * ch;
            const buf = new Uint8Array(ys + 2 * cs);
            await frame.copyTo(buf, { format: 'I420', layout: [
              { offset: 0, stride: lw },
              { offset: ys, stride: cw },
              { offset: ys + cs, stride: cw }
            ] });
            if (ts >= self.yuvTs) {
              self.yuv = { w: w, h: h, lw: lw, cw: cw,
                y: buf.slice(0, ys), u: buf.slice(ys, ys + cs), v: buf.slice(ys + cs) };
              self.yuvTs = ts;
            }
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
        hardwareAcceleration: 'no-preference',
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

  hasYuv() { return this.yuv !== null; }
  y() { return this.yuv ? this.yuv.y : null; }
  u() { return this.yuv ? this.yuv.u : null; }
  v() { return this.yuv ? this.yuv.v : null; }
  yw() { return this.yuv ? this.yuv.w : 0; }
  yh() { return this.yuv ? this.yuv.h : 0; }
  ylw() { return this.yuv ? this.yuv.lw : 0; }
  ycw() { return this.yuv ? this.yuv.cw : 0; }
  pop() { const f = this.frame; this.frame = null; return f; }
  w() { return this.width; }
  h() { return this.height; }
  ready() { return this.ok; }
  lastError() { return this.error; }
}
