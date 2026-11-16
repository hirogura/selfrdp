//! H.264 decoder backed by the browser WebCodecs VideoDecoder API.
//!
//! WebCodecs is asynchronous while `H264Decoder` is synchronous. We bridge this by
//! keeping the most recently decoded frame: `decode()` submits the new packet and
//! returns the frame that has already come back (one frame of latency).

use ironrdp_egfx::decode::{DecodedFrame, DecoderError, DecoderResult, H264Decoder, Yuv420Frame};
use wasm_bindgen::prelude::*;

#[wasm_bindgen(inline_js = r#"
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
"#)]
extern "C" {
    #[wasm_bindgen(js_name = WebCodecsDecoder)]
    type WebCodecsDecoder;

    #[wasm_bindgen(constructor)]
    fn new() -> WebCodecsDecoder;

    #[wasm_bindgen(method)]
    fn decode(this: &WebCodecsDecoder, data: &[u8]) -> bool;
    #[wasm_bindgen(method)]
    fn has_yuv(this: &WebCodecsDecoder) -> bool;
    #[wasm_bindgen(method, js_name = y)]
    fn y_buf(this: &WebCodecsDecoder) -> Option<Vec<u8>>;
    #[wasm_bindgen(method, js_name = u)]
    fn u_buf(this: &WebCodecsDecoder) -> Option<Vec<u8>>;
    #[wasm_bindgen(method, js_name = v)]
    fn v_buf(this: &WebCodecsDecoder) -> Option<Vec<u8>>;
    #[wasm_bindgen(method)]
    fn yw(this: &WebCodecsDecoder) -> u16;
    #[wasm_bindgen(method)]
    fn yh(this: &WebCodecsDecoder) -> u16;
    #[wasm_bindgen(method)]
    fn ylw(this: &WebCodecsDecoder) -> usize;
    #[wasm_bindgen(method)]
    fn ycw(this: &WebCodecsDecoder) -> usize;
    #[wasm_bindgen(method)]
    fn pop(this: &WebCodecsDecoder) -> Option<Vec<u8>>;
    #[wasm_bindgen(method)]
    fn w(this: &WebCodecsDecoder) -> u32;
    #[wasm_bindgen(method)]
    fn h(this: &WebCodecsDecoder) -> u32;
    #[wasm_bindgen(method)]
    fn ready(this: &WebCodecsDecoder) -> bool;
    #[wasm_bindgen(method)]
    fn reset(this: &WebCodecsDecoder);
    #[wasm_bindgen(method)]
    fn last_error(this: &WebCodecsDecoder) -> Option<String>;
}

pub struct WebCodecsH264 {
    js: WebCodecsDecoder,
    last: Option<DecodedFrame>,
    last_yuv: Option<Yuv420Frame>,
}

impl WebCodecsH264 {
    pub fn new() -> Self {
        Self { js: WebCodecsDecoder::new(), last: None, last_yuv: None }
    }
}

impl H264Decoder for WebCodecsH264 {
    fn decode(&mut self, data: &[u8]) -> DecoderResult<DecodedFrame> {
        let _ = WebCodecsDecoder::decode(&self.js, data);
        if let Some(bytes) = WebCodecsDecoder::pop(&self.js) {
            let w = WebCodecsDecoder::w(&self.js);
            let h = WebCodecsDecoder::h(&self.js);
            if !bytes.is_empty() && w > 0 && h > 0 {
                let frame = DecodedFrame::new(bytes, w, h);
                self.last = Some(frame.clone());
                return Ok(frame);
            }
        }
        if let Some(frame) = &self.last {
            return Ok(frame.clone());
        }
        Ok(DecodedFrame::new(vec![0u8; 1280 * 800 * 4], 1280, 800))
    }

    fn decode_yuv420(&mut self, data: &[u8]) -> DecoderResult<Yuv420Frame> {
        let _ = self.decode(data);
        if WebCodecsDecoder::has_yuv(&self.js) {
            let y = WebCodecsDecoder::y_buf(&self.js).unwrap_or_default();
            let u = WebCodecsDecoder::u_buf(&self.js).unwrap_or_default();
            let v = WebCodecsDecoder::v_buf(&self.js).unwrap_or_default();
            let w = WebCodecsDecoder::yw(&self.js);
            let h = WebCodecsDecoder::yh(&self.js);
            let lw = WebCodecsDecoder::ylw(&self.js);
            let cw = WebCodecsDecoder::ycw(&self.js);
            if let Ok(frame) = Yuv420Frame::new(w, h, y, lw, u, v, cw) {
                self.last_yuv = Some(frame.clone());
                return Ok(frame);
            }
        }
        if let Some(frame) = &self.last_yuv {
            return Ok(frame.clone());
        }
        Err(DecoderError::msg("WebCodecs decoder has no YUV frame yet"))
    }

    fn supports_yuv420(&self) -> bool {
        true
    }

    fn wait_until_ready(&mut self) -> bool {
        let ok = WebCodecsDecoder::ready(&self.js);
        if !ok {
            tracing::warn!(error = WebCodecsDecoder::last_error(&self.js), "WebCodecs H.264 decoder unavailable");
        }
        ok
    }

    fn reset(&mut self) {
        WebCodecsDecoder::reset(&self.js);
        self.last = None;
    }
}

unsafe impl Send for WebCodecsH264 {}
