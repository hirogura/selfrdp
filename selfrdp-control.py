#!/usr/bin/env python3
# selfRDP 制御 API
#   - /                 : selfRDP ブランドの制御画面 (RDP クライアントを iframe で表示)
#   - /api/status       : 稼働状態とバージョン
#   - /api/restart      : selfRDP スタック (selfrdp / gateway / nginx) を再起動
#   - /api/update       : GitHub (https://github.com/hirogura/selfrdp.git) から更新して再起動
import http.server
import json
import os
import subprocess
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(HERE, "selfrdp-index.html")
REPO_DIR = HERE
VERSION = "v.0.1.0"
SERVICES = ["selfrdp.service", "devolutions-gateway.service", "nginx.service"]

DEFAULT_INDEX = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>selfRDP</title></head><body>
<div style="background:#1b1f27;color:#fff;padding:12px;font-family:sans-serif">
<b>selfRDP</b> <span>v.0.1.0</span>
<button onclick="fetch('/api/update',{method:'POST'})">アップデート</button>
<button onclick="fetch('/api/restart',{method:'POST'})">再起動</button>
</div>
<iframe src="/jet/webapp/client" style="width:100%;height:calc(100vh - 60px);border:0"></iframe>
</body></html>"""


def _restart():
    """レスポンスを返した後に、少し待ってからサービスを再起動する。"""
    time.sleep(1)
    try:
        subprocess.Popen(
            ["/bin/bash", "-c", "systemctl restart " + " ".join(SERVICES)],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _update():
    """リポジトリを GitHub の最新状態に同期する (ローカルの変更は消さない)。"""
    try:
        proc = subprocess.run(
            ["git", "-C", REPO_DIR, "pull", "--ff-only"],
            capture_output=True, text=True, timeout=180,
        )
        if proc.returncode != 0:
            return False, "更新に失敗しました: " + (proc.stderr or proc.stdout).strip()
        # Gateway が更新されていた場合に備えて Web UI パッチを再適用する
        patch = os.path.join(REPO_DIR, "patch-gateway-webapp.sh")
        if os.path.isfile(patch):
            subprocess.run(["bash", patch], capture_output=True, text=True, timeout=180)
        return True, "GitHub から selfRDP を更新しました"
    except Exception as exc:
        return False, "更新に失敗しました: " + str(exc)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "selfRDP/" + VERSION

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _index(self):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as fh:
                return fh.read().encode("utf-8")
        except Exception:
            return DEFAULT_INDEX.encode("utf-8")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            body = self._index()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/status":
            self._json(200, {"service": "selfRDP", "version": VERSION, "ok": True})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/restart":
            self._json(200, {"ok": True, "message": "selfRDP を再起動します"})
            threading.Thread(target=_restart, daemon=True).start()
        elif path == "/api/update":
            ok, message = _update()
            self._json(200 if ok else 500, {"ok": ok, "message": message})
            if ok:
                threading.Thread(target=_restart, daemon=True).start()
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def log_message(self, fmt, *args):
        pass


def main():
    port = int(os.environ.get("SELFRDP_API_PORT", "7172"))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
