#!/usr/bin/env python3
# selfRDP 制御 API
#   - /                  : selfRDP 制御画面 (接続フォーム + noVNC)
#   - /api/status        : 稼働状態とバージョン
#   - /api/session       : 現在の RDP セッション状態
#   - /api/connect       : FreeRDP セッションを開始 (Xvfb + x11vnc + websockify + xfreerdp)
#   - /api/disconnect    : RDP セッションを終了
#   - /api/restart       : selfRDP スタック (selfrdp / gateway / nginx) を再起動
#   - /api/update        : GitHub から更新して再起動
#   - /api/log           : Web クライアント側エラーの記録 (デバッグ用)
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

DISPLAY = ":99"
VNC_PORT = 5900
WEBSOCKIFY_PORT = 6080

_procs = []
_lock = threading.Lock()
_session = {"host": "", "username": "", "started": 0}


def _terminate_procs():
    global _procs
    with _lock:
        for proc in reversed(_procs):
            try:
                proc.terminate()
            except Exception:
                pass
        for proc in reversed(_procs):
            try:
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        _procs = []
    _session.update(host="", username="", started=0)


def _spawn(args, env=None):
    return subprocess.Popen(
        args,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _connect(host, username, password):
    """FreeRDP セッションを開始する。"""
    if not host or not username:
        return False, "host と username は必須です"

    _terminate_procs()

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    try:
        _procs.append(_spawn([
            "Xvfb", DISPLAY, "-screen", "0", "1600x1000x24", "-nolisten", "tcp",
        ]))
        time.sleep(1)
        _procs.append(_spawn([
            "x11vnc", "-display", DISPLAY, "-listen", "127.0.0.1",
            "-rfbport", str(VNC_PORT), "-forever", "-shared", "-nopw",
        ]))
        _procs.append(_spawn([
            "websockify",
            "127.0.0.1:%d" % WEBSOCKIFY_PORT,
            "127.0.0.1:%d" % VNC_PORT,
        ]))
        time.sleep(1)

        rdp_args = [
            "xfreerdp3",
            "/v:" + host,
            "/u:" + username,
            "/p:" + password,
            "/cert:ignore",
            "/f",
            "/clipboard",
            "+compression",
        ]
        _procs.append(_spawn(rdp_args, env=env))
    except Exception as exc:
        _terminate_procs()
        return False, "セッション開始に失敗しました: " + str(exc)

    _session.update(host=host, username=username, started=int(time.time()))
    return True, "セッションを開始しました"


def _restart():
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


def _gateway_token(host):
    """Gateway の provisioner 鍵で RDP 用 ASSOCIATION トークンを署名する。"""
    import time
    import uuid
    import jwt

    key_path = "/etc/devolutions-gateway/provisioner.key"
    try:
        with open(key_path, encoding="utf-8") as fh:
            key = fh.read()
    except Exception as exc:
        return False, "provisioner 鍵を読み込めません: " + str(exc)

    now = int(time.time())
    payload = {
        "cert_thumb256": None,
        "dst_alt": [],
        "dst_hst": "tcp://%s:3389" % host,
        "iat": now,
        "nbf": now,
        "exp": now + 60,
        "jet_aid": str(uuid.uuid4()),
        "jet_ap": "rdp",
        "jet_cm": "fwd",
        "jet_flt": False,
        "jet_rec": "none",
        "jet_reuse": 0,
        "jet_ttl": 60,
        "jti": str(uuid.uuid4()),
    }
    try:
        token = jwt.encode(
            payload, key, algorithm="RS256",
            headers={"typ": "JWT", "cty": "ASSOCIATION"},
        )
        return True, token
    except Exception as exc:
        return False, "トークン署名に失敗しました: " + str(exc)


def _update():
    try:
        proc = subprocess.run(
            ["git", "-C", REPO_DIR, "pull", "--ff-only"],
            capture_output=True, text=True, timeout=180,
        )
        if proc.returncode != 0:
            return False, "更新に失敗しました: " + (proc.stderr or proc.stdout).strip()
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
            return b"<!doctype html><title>selfRDP</title><h1>selfRDP v.0.1.0</h1>"

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/rdp-token":
            host = ""
            from urllib.parse import urlparse, parse_qs
            params = parse_qs(urlparse(self.path).query)
            host = params.get("host", [""])[0]
            ok, result = _gateway_token(host)
            self._json(200 if ok else 500, {"ok": ok, "token": result if ok else "", "message": "" if ok else result})
        elif path in ("/", "/index.html"):
            body = self._index()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/status":
            self._json(200, {"service": "selfRDP", "version": VERSION, "ok": True})
        elif path == "/api/session":
            self._json(200, {
                "connected": bool(_session["host"]),
                "host": _session["host"],
                "username": _session["username"],
            })
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""

        if path == "/api/log":
            try:
                with open("/tmp/selfrdp-webclient-error.log", "a", encoding="utf-8") as fh:
                    fh.write(raw[:2000] + "\n")
            except Exception:
                pass
            self._json(200, {"ok": True})
        elif path == "/api/connect":
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
            ok, msg = _connect(
                data.get("host", "").strip(),
                data.get("username", "").strip(),
                data.get("password", ""),
            )
            self._json(200 if ok else 400, {"ok": ok, "message": msg})
        elif path == "/api/disconnect":
            _terminate_procs()
            self._json(200, {"ok": True, "message": "セッションを終了しました"})
        elif path == "/api/restart":
            self._json(200, {"ok": True, "message": "selfRDP を再起動します"})
            threading.Thread(target=_restart, daemon=True).start()
        elif path == "/api/update":
            ok, msg = _update()
            self._json(200 if ok else 500, {"ok": ok, "message": msg})
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
