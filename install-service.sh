#!/usr/bin/env bash
set -Eeuo pipefail
APP="${XDG_DATA_HOME:-$HOME/.local/share}/stellar-app-monitor"
[[ "$EUID" -ne 0 ]] || { echo "ERRO: execute como usuário comum."; exit 1; }
test -f "$APP/stellar_monitor.py" || { echo "ERRO: backend de temperaturas não encontrado: $APP/stellar_monitor.py"; exit 1; }
test -x "$APP/.venv/bin/python" || { echo "ERRO: ambiente Python do aplicativo não está pronto."; exit 1; }
mkdir -p "$HOME/.config/systemd/user"
UNIT="$HOME/.config/systemd/user/bc250-display.service"
cat > "$UNIT" <<EOF
[Unit]
Description=Stellar App Monitor - ESP32 temperature bridge
After=default.target

[Service]
Type=simple
ExecStart=$APP/.venv/bin/python -u $APP/stellar_monitor.py
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable bc250-display.service
systemctl --user restart bc250-display.service
echo "Serviço instalado, habilitado e iniciado."
