#!/usr/bin/env bash
# IronRDP master を WASM ビルドして iron-assets に配置する。
#
# Devolutions Gateway 同梱の IronRDP は KRDP (KDE) / GNOME Remote Desktop が
# 送る Server Deactivate All と EGFX (Graphics Pipeline) に対応していない。
# ここでは upstream master に対して次の 3 点を適用してビルドする:
#   1. support_dyn_vc_gfx_protocol = true (EGFX を広告する)
#   2. DrdynvcClient に GraphicsPipelineClient を接続する (描画を受け取る)
#   3. WebCodecs を使う H.264 デコーダを接続する (AVC420 を有効化して高速化)
set -Eeuo pipefail

IRONRDP_URL="${IRONRDP_URL:-https://github.com/Devolutions/IronRDP.git}"
SRC="/tmp/ironrdp-build"
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/iron-assets/pkg"

if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo が見つかりません (rustup を先に導入してください)" >&2
  exit 1
fi
export PATH="$HOME/.cargo/bin:$PATH"
command -v wasm-pack >/dev/null 2>&1 || cargo install wasm-pack
rustup target add wasm32-unknown-unknown

if [[ ! -d "$SRC/.git" ]]; then
  rm -rf "$SRC"
  git clone --depth 1 "$IRONRDP_URL" "$SRC"
fi

cd "$SRC"

# パッチ 1: EGFX を広告する
if grep -q 'support_dyn_vc_gfx_protocol: false' crates/ironrdp-web/src/session.rs; then
  sed -i 's/support_dyn_vc_gfx_protocol: false,/support_dyn_vc_gfx_protocol: true,/' crates/ironrdp-web/src/session.rs
fi

# パッチ 2: EGFX DVC を接続する
if ! grep -q 'WebEgfxHandler' crates/ironrdp-web/src/session.rs; then
  PATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ironrdp-patch"
  python3 - <<'PY'
p = 'crates/ironrdp-web/src/session.rs'
s = open(p).read()
s = s.replace('use ironrdp::dvc::DrdynvcClient;',
  'use ironrdp::dvc::DrdynvcClient;\nuse ironrdp_egfx::client::{GraphicsPipelineClient, GraphicsPipelineHandler};', 1)
marker = '    let mut connector = ClientConnector::new(config, dummy_client_addr);'
handler = '    struct WebEgfxHandler;\n    impl GraphicsPipelineHandler for WebEgfxHandler {}\n\n'
s = s.replace(marker, handler + marker, 1)
s = s.replace(marker, '    let use_egfx = config.support_dyn_vc_gfx_protocol;\n' + marker, 1)
old = '''    if use_display_control {
        connector.attach_static_channel(
            DrdynvcClient::new().with_dynamic_channel(DisplayControlClient::new(|_| Ok(Vec::new()))),
        );
    }
'''
new = '''    {
        let mut drdynvc = DrdynvcClient::new();
        if use_display_control {
            drdynvc = drdynvc.with_dynamic_channel(DisplayControlClient::new(|_| Ok(Vec::new())));
        }
        if use_egfx {
            drdynvc = drdynvc.with_dynamic_channel(GraphicsPipelineClient::new(Box::new(WebEgfxHandler), None));
        }
        connector.attach_static_channel(drdynvc);
    }
'''
if s.count(old) != 1:
    raise SystemExit('unexpected DrdynvcClient block count')
s = s.replace(old, new, 1)
open(p, 'w').write(s)
PY
fi

# ironrdp-egfx を依存に追加
if ! grep -q 'ironrdp-egfx' crates/ironrdp-web/Cargo.toml; then
  sed -i 's|ironrdp-core.path = "../ironrdp-core"|ironrdp-egfx.path = "../ironrdp-egfx"\nironrdp-core.path = "../ironrdp-core"|' crates/ironrdp-web/Cargo.toml
fi

# パッチ 3: WebCodecs H.264 デコーダを組み込む
PATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ironrdp-patch"
if ! grep -q 'mod h264_webcodecs;' crates/ironrdp-web/src/lib.rs; then
  sed -i 's/mod audio;/mod audio;\\nmod h264_webcodecs;/' crates/ironrdp-web/src/lib.rs
fi
if ! grep -q 'h264_webcodecs::WebCodecsH264' crates/ironrdp-web/src/session.rs; then
  sed -i 's/use ironrdp::dvc::DrdynvcClient;/use ironrdp::dvc::DrdynvcClient;\\nuse crate::h264_webcodecs::WebCodecsH264;/' crates/ironrdp-web/src/session.rs
  sed -i 's/GraphicsPipelineClient::new(Box::new(WebEgfxHandler), None)/GraphicsPipelineClient::new(Box::new(WebEgfxHandler), Some(Box::new(WebCodecsH264::new())))/' crates/ironrdp-web/src/session.rs
fi
cp -f "$PATCH_DIR/h264_webcodecs.rs" crates/ironrdp-web/src/h264_webcodecs.rs

cd crates/ironrdp-web
RUSTFLAGS='-Ctarget-feature=+simd128,+bulk-memory --cfg getrandom_backend="wasm_js" -Copt-level=s -Ccodegen-units=1' \
  wasm-pack build --target web

mkdir -p "$DEST"
cp -f pkg/ironrdp_web.js pkg/ironrdp_web_bg.wasm "$DEST/"
rm -rf "$DEST/snippets"
cp -r pkg/snippets "$DEST/"
echo "IronRDP WASM を $DEST に配置しました"
