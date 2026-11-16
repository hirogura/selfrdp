# selfRDP

ブラウザ上で動作する RDP クライアントです。Tailscale Serve の HTTPS（既定ポート **3375**）で公開します。

RDP の描画は **IronRDP（Rust）を WebAssembly 化したクライアント**がブラウザ内で直接処理します。中継は Devolutions Gateway の RDCleanPath プロキシのみです。H.264 (AVC420) はブラウザの WebCodecs でハードウェアデコードします。

## 構成

- `install-selfrdp.sh` — インストーラ（selfRDP コンテナ内で root 実行）
- `selfrdp-control.py` — 制御 API（状態判定・トークン発行・プロファイル・更新・再起動）
- `iron-assets/` — IronRDP の WASM、トップページ、ファビコン
- `selfrdp-nginx.conf` — リバースプロキシ
- `build-ironrdp.sh` / `ironrdp-patch/` — IronRDP の再ビルド手順とパッチ

接続先プロファイルは **`/opt/selfrdp-data/profiles.json`**（ワークスペース外・root のみ読み書き）に保存します。誤って GitHub に上げることはありません。パスワードは保存されません。

## 使い方

```bash
bash install-selfrdp.sh
```

`https://<tailnet-host>.<tailnet-name>.ts.net:3375/` を開きます。

- 保存済みの接続先をドロップダウンで選ぶか、新規にホスト名・ユーザー名・パスワードを入力して「接続」
- 「保存」で接続先を登録、「削除」で削除
- 「方式を自動判定」を ON にすると、対象の RDP 応答を調べて NLA(CredSSP) / TLS を自動で切り替えます
  - KDE (KRDP) は TLS、Ubuntu (GNOME) は NLA を要求します
- 接続中は「切断」ボタン、および 半角/全角・変換・無変換・Ctrl+Alt+Del・Win・Alt+Tab・Ctrl+Shift+Esc・PrtSc の特殊キーを送信できます
- 「アップデート」は GitHub から更新して再起動、「再起動」はサービスを再起動します

IronRDP のパッチ内容:

1. `support_dyn_vc_gfx_protocol = true` — EGFX (Graphics Pipeline) を広告
2. `DrdynvcClient` に `GraphicsPipelineClient` を接続
3. WebCodecs (`VideoDecoder`) による H.264 AVC420 デコード（`ironrdp-patch/h264_webcodecs.rs`）

再ビルド: `bash build-ironrdp.sh`（Rust / wasm-pack が必要）
