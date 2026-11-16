#!/usr/bin/env python3
# selfRDP 制御 API
#   - /api/status        : 稼働状態とバージョン
#   - /api/profiles      : 接続先プロファイルの取得 / 保存 / 削除
#   - /api/rdp-token     : Gateway 用 ASSOCIATION トークンの発行
#   - /api/restart       : selfRDP スタックを再起動
#   - /api/update        : GitHub から更新して再起動
#   - /api/log           : Web クライアント側ログ (デバッグ用)
import http.server
import json
import os
import subprocess
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = HERE
VERSION = "v.0.6.1"
SERVICES = ["selfrdp.service", "devolutions-gateway.service", "nginx.service"]

DATA_DIR = os.environ.get("SELFRDP_DATA_DIR", "/opt/selfrdp-data")
PROFILES_FILE = os.path.join(DATA_DIR, "profiles.json")


def _ensure_data_dir():
    try:
        os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
        os.chmod(DATA_DIR, 0o700)
    except Exception:
        pass


def _read_profiles():
    _ensure_data_dir()
    try:
        with open(PROFILES_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            data = {"profiles": data}
        return data.get("profiles", [])
    except Exception:
        return []


def _write_profiles(profiles):
    _ensure_data_dir()
    with open(PROFILES_FILE, "w", encoding="utf-8") as fh:
        json.dump({"profiles": profiles}, fh, ensure_ascii=False, indent=2)
    os.chmod(PROFILES_FILE, 0o600)


def _probe_target(host):
    """対象の X.224 応答から NLA (CredSSP) 要不要を判定する。"""
    import socket
    import struct

    try:
        nego = bytes([0x01, 0x00, 0x08, 0x00]) + struct.pack("<I", 0x0B)
        x224 = bytes([0x0E, 0xE0, 0, 0, 0, 0, 0]) + nego
        pkt = bytes([0x03, 0x00]) + struct.pack(">H", len(x224) + 4) + x224
        sock = socket.create_connection((host, 3389), timeout=5)
        sock.sendall(pkt)
        sock.settimeout(3)
        data = sock.recv(64)
        sock.close()
        if len(data) < 19 or data[11] != 0x02:
            return True, {"ok": False, "selected": None}
        selected = struct.unpack("<I", data[15:19])[0]
        # PROTOCOL_HYBRID (0x2) / HYBRID_EX (0x8) が選ばれたら NLA が必要
        credssp = bool(selected & 0x0A)
        return True, {"ok": True, "selected": "0x%08x" % selected, "credssp": credssp}
    except Exception as exc:
        return False, {"ok": False, "error": str(exc)}


def _gateway_token(host):
    """Gateway の provisioner 鍵で RDP 用 ASSOCIATION トークンを署名する。"""
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


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "selfRDP/" + VERSION

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/api/status":
            self._json(200, {"service": "selfRDP", "version": VERSION, "ok": True})
        elif path == "/api/profiles":
            self._json(200, {"ok": True, "profiles": _read_profiles()})
        elif path == "/api/probe":
            host = params.get("host", [""])[0]
            ok, result = _probe_target(host)
            self._json(200 if ok else 500, result)
        elif path == "/api/rdp-token":
            host = params.get("host", [""])[0]
            ok, result = _gateway_token(host)
            self._json(200 if ok else 500, {
                "ok": ok, "token": result if ok else "",
                "message": "" if ok else result,
            })
        elif path == "/":
            body = ("<!doctype html><meta charset='utf-8'><title>selfRDP</title>"
                    "<h1>selfRDP " + VERSION + "</h1>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
        elif path == "/api/profiles":
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
            action = data.get("action", "")
            profiles = _read_profiles()
            if action == "save":
                profile = data.get("profile", {})
                name = str(profile.get("name", "")).strip()
                if not name:
                    self._json(400, {"ok": False, "message": "名前は必須です"})
                    return
                clean = {
                    "name": name,
                    "host": str(profile.get("host", "")).strip(),
                    "username": str(profile.get("username", "")).strip(),
                    "password": str(profile.get("password", "")),
                    "autodetect": bool(profile.get("autodetect", True)),
                    "credssp": bool(profile.get("credssp", False)),
                    "width": int(profile.get("width", 1280)),
                    "height": int(profile.get("height", 800)),
                    "perf": int(profile.get("perf", 0x83)),
                }
                replaced = False
                for i, p in enumerate(profiles):
                    if p.get("name") == name:
                        profiles[i] = clean
                        replaced = True
                        break
                if not replaced:
                    profiles.append(clean)
                _write_profiles(profiles)
                self._json(200, {"ok": True, "message": "保存しました", "profiles": profiles})
            elif action == "delete":
                name = str(data.get("name", ""))
                profiles = [p for p in profiles if p.get("name") != name]
                _write_profiles(profiles)
                self._json(200, {"ok": True, "message": "削除しました", "profiles": profiles})
            else:
                self._json(400, {"ok": False, "message": "不正な操作です"})
        elif path == "/api/restart":
            self._json(200, {"ok": True, "message": "selfRDP を再起動します"})
            threading.Thread(target=_restart, daemon=True).start()
        elif path == "/api/update":
            ok, msg = True, "GitHub から更新しました"
            try:
                proc = subprocess.run(
                    ["git", "-C", REPO_DIR, "pull", "--ff-only"],
                    capture_output=True, text=True, timeout=180,
                )
                if proc.returncode != 0:
                    ok, msg = False, "更新に失敗しました: " + (proc.stderr or proc.stdout).strip()
            except Exception as exc:
                ok, msg = False, "更新に失敗しました: " + str(exc)
            self._json(200 if ok else 500, {"ok": ok, "message": msg})
            if ok:
                threading.Thread(target=_restart, daemon=True).start()
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def log_message(self, fmt, *args):
        pass


def main():
    _ensure_data_dir()
    port = int(os.environ.get("SELFRDP_API_PORT", "7172"))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
