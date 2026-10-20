#!/usr/bin/env bash
set -Eeuo pipefail
REPO="https://github.com/isaacalvex/AMD-BC250-Display-Status-Bazzite-CachyOS.git"
DIR="${XDG_DATA_HOME:-$HOME/.local/share}/stellar-app-monitor"
echo "[Stellar] Instalando Stellar App Monitor..."
[[ "$EUID" -ne 0 ]] || { echo "Execute SEM sudo."; exit 1; }
for cmd in git python3; do command -v "$cmd" >/dev/null || { echo "Falta $cmd"; exit 1; }; done
if [[ -d "$DIR/.git" ]]; then git -C "$DIR" pull --ff-only
elif [[ ! -e "$DIR" ]]; then git clone --depth=1 "$REPO" "$DIR"
else echo "Diretório $DIR já existe e não é um repositório Git"; exit 1; fi
python3 -m venv "$DIR/.venv" || { echo "Falha ao criar venv: verifique python3-venv"; exit 1; }
"$DIR/.venv/bin/python" -m pip install --disable-pip-version-check -r "$DIR/requirements.txt"
# Aplicar a nova versão do bridge Python quando o serviço já existe.
if [[ -f "$HOME/.config/systemd/user/bc250-display.service" ]]; then
  echo "[Stellar] Reiniciando o serviço de temperaturas e downloads Steam..."
  systemctl --user restart bc250-display.service || echo "[Stellar] AVISO: falha ao reiniciar serviço; use a tela Serviço para diagnosticar."
fi
cat > "$DIR/abrir-stellar.sh" <<'EOS'
#!/usr/bin/env bash
set -Eeuo pipefail
DIR="${XDG_DATA_HOME:-$HOME/.local/share}/stellar-app-monitor"
cd "$DIR"
exec "$DIR/.venv/bin/python" "$DIR/main.py"
EOS
chmod +x "$DIR/abrir-stellar.sh"
mkdir -p "$HOME/.local/share/applications"
APP="$HOME/.local/share/applications/stellar-app-monitor.desktop"
cat > "$APP" <<EOS
[Desktop Entry]
Type=Application
Name=Stellar App Monitor
Comment=Monitor de temperaturas e firmware ESP32-C3
Exec=$DIR/abrir-stellar.sh
Icon=$DIR/icon.svg
Terminal=false
Categories=Utility;System;
StartupNotify=true
EOS
chmod +x "$APP"
DESKTOP=""
if command -v xdg-user-dir >/dev/null; then DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || true)"; fi
if [[ -z "$DESKTOP" ]]; then
  for p in "$HOME/Área de Trabalho" "$HOME/Desktop"; do
    if [[ -d "$p" ]]; then DESKTOP="$p"; break; fi
  done
fi
if [[ -n "$DESKTOP" && -d "$DESKTOP" ]]; then
  cp "$APP" "$DESKTOP/Stellar App Monitor.desktop"
  chmod +x "$DESKTOP/Stellar App Monitor.desktop"
  echo "[Stellar] Atalho na Área de Trabalho: $DESKTOP"
else echo "[Stellar] Área de Trabalho não encontrada; aplicativo aparece no menu."; fi
echo "[Stellar] Instalado no menu de aplicativos. Iniciando..."
exec "$DIR/abrir-stellar.sh"
