# selfRDP

ブラウザ上で動作する RDP クライアントです。Devolutions Gateway（IronRDP ベースの Web RDP）をこのコンテナ内に導入し、Tailscale Serve の HTTPS（既定ポート **3375**）で公開します。

## 構成

- `install-selfrdp.sh` — インストーラ（selfRDP コンテナ内で root 実行）
- `selfrdp-control.py` — 制御 API（稼働状態 / アップデート / 再起動）
- `selfrdp-index.html` — 制御画面（タイトル **selfRDP** / **v.0.1.0** / アップデート / 再起動ボタン）
- `selfrdp-nginx.conf` — リバースプロキシ（制御画面・API と RDP エンジンを振り分け、WebSocket も透過）

## 使い方

```bash
bash install-selfrdp.sh
# カスタム例
TS_AUTHKEY=tskey-auth-xxxx DGW_PASS='任意のパスワード' bash install-selfrdp.sh
```

完了時に表示される URL（例: `https://<tailnet-host>.<tailnet-name>.ts.net:3375/`）をブラウザで開くと、上部に selfRDP / v.0.1.0 と操作ボタンが表示され、その下で RDP セッションを張れます。

- **アップデート** — `https://github.com/hirogura/selfrdp.git` の最新コードを取得して再起動します（nginx 設定はリポジトリファイルを symlink 参照しているため、更新がそのまま反映されます）。
- **再起動** — `selfrdp` / `devolutions-gateway` / `nginx` のサービスを再起動します。

詳細なオプションは `bash install-selfrdp.sh --help` を参照してください。
