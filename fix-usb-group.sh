#!/usr/bin/env bash
set -Eeuo pipefail
# Roda com Polkit após o usuário confirmar o ajuste de permissões USB.
[[ $EUID -eq 0 ]] || { echo "Requer autorização administrativa"; exit 1; }
[[ $# -eq 3 ]] || { echo "Argumentos inválidos"; exit 1; }
account="$1"
group="$2"
port="$3"
[[ "$account" =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*$ ]] || exit 1
[[ "$group" == dialout || "$group" == uucp ]] || exit 1
[[ "$port" =~ ^/dev/tty(ACM|USB)[0-9]+$ ]] || exit 1
[[ -c "$port" ]] || { echo "Dispositivo desconectado"; exit 1; }
[[ "$(stat -Lc %G "$port")" == "$group" ]] || { echo "Grupo da porta mudou"; exit 1; }
getent passwd "$account" >/dev/null || { echo "Usuário inválido"; exit 1; }
if ! grep -q "^$group:" /etc/group; then
  entry="$(grep -m1 "^$group:" /usr/lib/group || true)"
  [[ -n "$entry" ]] || { echo "Grupo não existe em /usr/lib/group"; exit 1; }
  vendor_gid="$(printf '%s\n' "$entry" | cut -d: -f3)"
  device_gid="$(stat -Lc %g "$port")"
  [[ "$vendor_gid" == "$device_gid" ]] || { echo "GID do grupo difere da porta"; exit 1; }
  cp -p /etc/group "/etc/group.stellar-backup-$(date +%Y%m%d-%H%M%S)"
  printf '%s\n' "$entry" >> /etc/group
  echo "Grupo $group incluído no /etc/group."
fi
usermod -aG "$group" "$account"
id "$account"
echo "Associação atualizada. Saia completamente da sessão e entre novamente."
