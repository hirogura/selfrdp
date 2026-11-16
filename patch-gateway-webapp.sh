#!/usr/bin/env bash
# Devolutions Gateway のスタンドアロン Web UI に対して、
# RDP 接続時に CredSSP (NLA) を無効化し TLS ログオンを使うようパッチを当てる。
#
# 背景: KRDP (KDE リモートデスクトップ) などの TLS+PAM 方式の RDP サーバは
#       PROTOCOL_SSL を選択する。IronRDP Web クライアントは既定で CredSSP を
#       要求するためネゴシエーション後に切断される。enable_credssp=false を
#       注入することで TLS ログオン (ユーザー名/パスワード) に切り替わる。
set -Eeuo pipefail

WEBAPP_DIR="/usr/share/devolutions-gateway/webapp/client"
MARKER="__selfrdp_disable_credssp__"

log() { printf '\033[1;34m[selfRDP]\033[0m %s\n' "$*"; }

[[ -d "$WEBAPP_DIR" ]] || { echo "Web UI が見つかりません: $WEBAPP_DIR" >&2; exit 1; }

changed=0
shopt -s nullglob
for f in "$WEBAPP_DIR"/*.js; do
  # RDP の callConnect と Extension クラスを持つバンドルだけを対象にする
  grep -q 'g.enableDisplayControl&&(C.withExtension(My(!0))' "$f" || continue
  grep -q 'var dB=class' "$f" || continue
  grep -q "$MARKER" "$f" && { log "Already patched: $(basename "$f")"; continue; }

  if [[ ! -f "$f.selfrdp.bak" ]]; then
    cp -p "$f" "$f.selfrdp.bak"
  fi

  python3 - "$f" "$MARKER" <<'PY'
import sys
path, marker = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    src = fh.read()

needle = '.withAuthToken(g.token);g.domain!=null&&C.withServerDomain(g.domain)'
count = src.count(needle)
if count != 1:
    raise SystemExit(f"unexpected match count for RDP callConnect: {count}")

replacement = (
    '.withAuthToken(g.token);'
    'C.withExtension(new dB("enable_credssp",!1))/*' + marker + '*/;'
    'g.domain!=null&&C.withServerDomain(g.domain)'
)
with open(path, "w", encoding="utf-8") as fh:
    fh.write(src.replace(needle, replacement))
PY
  log "Patched: $(basename "$f")"
  changed=1
done

if [[ "$changed" == 1 ]]; then
  log "gateway を再起動します"
  systemctl restart devolutions-gateway
else
  log "パッチ対象の変更はありません"
fi
