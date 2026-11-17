#!/usr/bin/env bash
# =============================================================================
# install-selfrdp.sh
#   selfRDP - ブラウザ上で動作する RDP クライアント
#   このスクリプトは selfRDP を「現在のコンテナ内」に導入します。
#   Devolutions Gateway (IronRDP ベースの Web RDP) + 制御画面 (バージョン表示 /
#   アップデート / 再起動) + nginx リバースプロキシを構成し、Tailscale Serve の
#   HTTPS (既定ポート 3375) で公開します。
#
# 実行場所: selfRDP コンテナ内 (root)
#
# 使い方:
#   bash install-selfrdp.sh
#   TS_AUTHKEY=tskey-auth-xxxx DGW_PASS='変更後のパス' bash install-selfrdp.sh
#
# 主な環境変数 (すべて省略可):
#   TS_HOSTNAME    tailnet 上のホスト名        (既定: 現在のホスト名)
#   TS_AUTHKEY     Tailscale auth key (未ログイン時に使用)
#   TS_HTTPS_PORT  tailscale serve の HTTPS ポート (既定: 3375)
#   DGW_VERSION    Devolutions Gateway のバージョン固定 例: 2026.3.3 (既定: 最新)
#   DGW_DEB_URL    .deb の URL を直接指定 (指定時は DGW_VERSION を無視)
#   DGW_PORT       Gateway の HTTP リッスンポート (既定: 7171)
#   DGW_USER       Web UI のログインユーザー   (既定: admin)
#   DGW_PASS       Web UI のパスワード (省略時はランダム生成して最後に表示)
# =============================================================================
set -Eeuo pipefail

TS_HOSTNAME="${TS_HOSTNAME:-$(hostname)}"
TS_AUTHKEY="${TS_AUTHKEY:-}"
TS_HTTPS_PORT="${TS_HTTPS_PORT:-3375}"
DGW_VERSION="${DGW_VERSION:-}"
DGW_DEB_URL="${DGW_DEB_URL:-}"
DGW_PORT="${DGW_PORT:-7171}"
DGW_USER="${DGW_USER:-admin}"
DGW_PASS="${DGW_PASS:-}"

SR_APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SR_REPO_URL="https://github.com/hirogura/selfrdp.git"
SR_API_PORT=7172
SR_NGINX_PORT=7173
SR_VERSION="v.0.7.0"

log()  { printf '\033[1;34m[selfRDP]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }
trap 'die "行 $LINENO で失敗しました"' ERR

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,/^set -Eeuo pipefail$/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
  exit 0
fi

# ---------------------------------------------------------------- 事前チェック
[[ $EUID -eq 0 ]] || die "root で実行してください"
command -v systemctl >/dev/null || die "systemd が使えません"
for f in selfrdp-control.py selfrdp-nginx.conf build-ironrdp.sh iron-assets/index.html iron-assets/favicon.svg iron-assets/pkg/ironrdp_web.js iron-assets/pkg/ironrdp_web_bg.wasm; do
  [[ -f "$SR_APP_DIR/$f" ]] || die "$SR_APP_DIR/$f が見つかりません"
done
[[ -d "$SR_APP_DIR/iron-assets/pkg/snippets" ]] || die "iron-assets/pkg/snippets が見つかりません"

# ------------------------------------------------- 基本パッケージ + Tailscale
log "基本パッケージを導入します"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates jq openssl argon2 python3 python3-jwt nginx git \
  build-essential pkg-config libssl-dev >/dev/null

if ! command -v tailscale >/dev/null 2>&1; then
  log "Tailscale を導入します"
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled >/dev/null 2>&1 || true
for _ in $(seq 1 20); do tailscale status >/dev/null 2>&1 && break; sleep 1; done

# ------------------------------------------------------ Tailscale ログイン/FQDN
if ! tailscale status --json 2>/dev/null | jq -e '.BackendState=="Running"' >/dev/null 2>&1; then
  log "Tailscale にログインします (URL が表示された場合はブラウザで承認してください)"
  if [[ -n "$TS_AUTHKEY" ]]; then
    tailscale up --hostname="$TS_HOSTNAME" --authkey="$TS_AUTHKEY"
  else
    tailscale up --hostname="$TS_HOSTNAME"
  fi
fi
TS_FQDN="$(tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//')"
[[ -n "$TS_FQDN" && "$TS_FQDN" != "null" ]] || die "Tailscale の FQDN を取得できません (MagicDNS を有効化してください)"
log "Tailscale FQDN: $TS_FQDN"

if [[ "$TS_HTTPS_PORT" == "443" ]]; then
  EXTERNAL_URL="https://$TS_FQDN"
else
  EXTERNAL_URL="https://$TS_FQDN:$TS_HTTPS_PORT"
fi

# ------------------------------------------------------ Devolutions Gateway 導入
log "Devolutions Gateway (RDP エンジン) を導入・設定します"
CFG_DIR=/etc/devolutions-gateway
CFG="$CFG_DIR/gateway.json"

if [[ -z "$DGW_DEB_URL" ]]; then
  arch="$(dpkg --print-architecture)"
  api="https://api.github.com/repos/Devolutions/devolutions-gateway/releases"
  if [[ -n "$DGW_VERSION" ]]; then api="$api/tags/v${DGW_VERSION#v}"; else api="$api/latest"; fi
  # 新しいリリースは devolutions-gateway-<ver>-x64.deb (旧: _amd64.deb)
  if [[ "$arch" == "amd64" ]]; then arch_pat="x64|amd64"; else arch_pat="$arch"; fi
  DGW_DEB_URL="$(curl -fsSL "$api" | jq -r --arg a "$arch_pat" \
    '[.assets[] | select(.name | test("^devolutions-gateway[-_].*[-_](" + $a + ")\\.deb$"))][0].browser_download_url')"
  [[ -n "$DGW_DEB_URL" && "$DGW_DEB_URL" != "null" ]] || die "$arch 用の .deb が見つかりません (DGW_DEB_URL を指定してください)"
fi
log "deb: $DGW_DEB_URL"
curl -fsSL "$DGW_DEB_URL" -o /tmp/devolutions-gateway.deb
apt-get install -y -qq /tmp/devolutions-gateway.deb
rm -f /tmp/devolutions-gateway.deb

mkdir -p "$CFG_DIR"

if [[ ! -s "$CFG_DIR/provisioner.key" ]]; then
  openssl genrsa -out "$CFG_DIR/provisioner.key" 2048 2>/dev/null
  openssl rsa -in "$CFG_DIR/provisioner.key" -pubout -out "$CFG_DIR/provisioner.pem" 2>/dev/null
fi

USERS="$CFG_DIR/users.txt"
touch "$USERS"
if [[ -z "$DGW_PASS" ]] && grep -q "^${DGW_USER}:" "$USERS"; then
  log "ユーザー '$DGW_USER' は既に存在するためパスワードは変更しません"
else
  if [[ -z "$DGW_PASS" ]]; then
    DGW_PASS="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-20)"
    umask 077
    printf '%s' "$DGW_PASS" > /root/.selfrdp-initial-pass
  fi
  salt="$(openssl rand -hex 8)"
  hash="$(printf '%s' "$DGW_PASS" | argon2 "$salt" -id -e)"
  grep -v "^${DGW_USER}:" "$USERS" > "$USERS.new" || true
  printf '%s:%s\n' "$DGW_USER" "$hash" >> "$USERS.new"
  mv "$USERS.new" "$USERS"
fi

[[ -s "$CFG" ]] || echo '{}' > "$CFG"
tmp="$(mktemp)"
jq --arg int "http://127.0.0.1:$DGW_PORT" --arg ext "$EXTERNAL_URL" --arg host "$TS_FQDN" '
    .Hostname = $host
  | .ProvisionerPublicKeyFile  = "/etc/devolutions-gateway/provisioner.pem"
  | .ProvisionerPrivateKeyFile = "/etc/devolutions-gateway/provisioner.key"
  | .Listeners = [ { InternalUrl: $int, ExternalUrl: $ext } ]
  | .WebApp = { Enabled: true, Authentication: "Custom" }
' "$CFG" > "$tmp"
install -m 0640 "$tmp" "$CFG"
rm -f "$tmp"

svc_user="$(systemctl show -p User --value devolutions-gateway 2>/dev/null || true)"
if [[ -n "$svc_user" ]] && id "$svc_user" >/dev/null 2>&1; then
  chown -R "$svc_user": "$CFG_DIR"
fi
chmod 600 "$CFG_DIR/provisioner.key" "$USERS"

systemctl enable devolutions-gateway >/dev/null 2>&1 || true
systemctl restart devolutions-gateway

# ---------------------------------------- IronRDP (Rust + WASM) クライアント
log "IronRDP WASM クライアントを配置します"
# ビルド済みアセットをリポジトリから使用する (再ビルドする場合は build-ironrdp.sh)
[[ -f "$SR_APP_DIR/iron-assets/index.html" ]] || die "iron-assets が見つかりません"
chmod 0755 "$SR_APP_DIR/build-ironrdp.sh"

# ------------------------------------------ 接続先データ (ワークスペース外)
log "接続先データディレクトリを用意します"
mkdir -p -m 0700 /opt/selfrdp-data
chmod 0700 /opt/selfrdp-data
if [[ ! -f /opt/selfrdp-data/profiles.json ]]; then
  printf '{"profiles":[]}\n' > /opt/selfrdp-data/profiles.json
  chmod 0600 /opt/selfrdp-data/profiles.json
fi

# ------------------------------------------ selfRDP 制御画面 / API / プロキシ
log "selfRDP の制御画面・制御 API・リバースプロキシを設定します"

# アップデート用に GitHub リポジトリが origin に設定されているか確認
if ! git -C "$SR_APP_DIR" remote get-url origin >/dev/null 2>&1; then
  git -C "$SR_APP_DIR" remote add origin "$SR_REPO_URL" 2>/dev/null || true
fi

chmod 0755 "$SR_APP_DIR/selfrdp-control.py"

cat > /etc/systemd/system/selfrdp.service <<EOF
[Unit]
Description=selfRDP Control Service ($SR_VERSION)
After=network-online.target devolutions-gateway.service nginx.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$SR_APP_DIR
Environment=SELFRDP_API_PORT=$SR_API_PORT
ExecStart=/usr/bin/python3 $SR_APP_DIR/selfrdp-control.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# nginx 設定はリポジトリのファイルを symlink で参照 (git pull がそのまま反映される)
ln -sfn "$SR_APP_DIR/selfrdp-nginx.conf" /etc/nginx/conf.d/selfrdp.conf
nginx -t

systemctl daemon-reload
systemctl enable nginx >/dev/null 2>&1 || true
systemctl restart nginx
systemctl enable --now selfrdp >/dev/null 2>&1 || true

for _ in $(seq 1 20); do
  curl -fsS "http://127.0.0.1:$SR_API_PORT/api/status" >/dev/null 2>&1 && break
  sleep 1
done
echo "[selfRDP] $(curl -fsS "http://127.0.0.1:$SR_API_PORT/api/status" || echo '制御 API の起動確認に失敗')"

# ------------------------------------------------------------ Tailscale Serve
log "tailscale serve で HTTPS 公開します (ポート $TS_HTTPS_PORT)"
tailscale serve --bg --https="$TS_HTTPS_PORT" "http://127.0.0.1:$SR_NGINX_PORT" \
  || warn "tailscale serve に失敗: tailnet の管理画面で MagicDNS と HTTPS Certificates を有効化してください"

# ---------------------------------------------------------------------- 完了
PASS_SHOWN=""
if [[ -f /root/.selfrdp-initial-pass ]]; then
  PASS_SHOWN="$(cat /root/.selfrdp-initial-pass)"
  rm -f /root/.selfrdp-initial-pass
fi

cat <<EOF

==================== selfRDP $SR_VERSION 完了 ====================
  URL       : $EXTERNAL_URL/
  RDP 直接  : $EXTERNAL_URL/jet/webapp/client
  ユーザー  : $DGW_USER
  パスワード: ${PASS_SHOWN:-(既存または DGW_PASS 指定のもの)}

  制御画面の「アップデート」: GitHub から selfRDP を更新して再起動
  制御画面の「再起動」      : selfrdp / devolutions-gateway / nginx を再起動

  ログ確認 : journalctl -u selfrdp -f
  公開状況 : tailscale serve status
================================================================
EOF
