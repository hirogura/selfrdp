# selfRDP

ブラウザ上で動作する RDP クライアントです。Tailscale Serve の HTTPS（既定ポート **3375**）で公開します。

RDP の描画は **IronRDP（Rust）を WebAssembly 化したクライアント**がブラウザ内で直接処理します。中継は Devolutions Gateway の RDCleanPath プロキシのみなので、画質・応答が良好です。

## 構成

- `install-selfrdp.sh` — インストーラ（selfRDP コンテナ内で root 実行）
- `selfrdp-control.py` — 制御 API（トークン発行 / アップデート / 再起動）
- `iron-assets/` — IronRDP の WASM とトップページ（selfRDP / v.0.1.0 / アップデート / 再起動）
- `selfrdp-nginx.conf` — リバースプロキシ（トップページ・API・Gateway WebSocket を振り分け）
- `build-ironrdp.sh` — IronRDP master を WASM ビルドして `iron-assets/pkg` を更新するスクリプト

IronRDP は upstream master に対して次のパッチを適用してビルドしています（KRDP / GNOME Remote Desktop 対応）:

1. `support_dyn_vc_gfx_protocol = true` — EGFX (Graphics Pipeline) を広告する
2. `DrdynvcClient` に `GraphicsPipelineClient` を接続し、デコードしたフレームを canvas に描画する

## 使い方

```bash
bash install-selfrdp.sh
```

`https://<tailnet-host>.<tailnet-name>.ts.net:3375/` を開き、接続先ホスト・ユーザー名・パスワードを入力して「接続」を押します。

- **アップデート** — `https://github.com/hirogura/selfrdp.git` の最新コードを取得して再起動します。
- **再起動** — `selfrdp` / `devolutions-gateway` / `nginx` のサービスを再起動します。

WASM を作り直す場合は `bash build-ironrdp.sh` を実行してください（Rust / wasm-pack が必要）。

詳細なオプションは `bash install-selfrdp.sh --help` を参照してください。
