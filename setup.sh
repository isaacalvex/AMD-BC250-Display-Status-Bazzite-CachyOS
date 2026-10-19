#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${BC250_REPO_URL:-https://github.com/isaacalvex/AMD-BC250-Display-Status-BazziteOS.git}"
INSTALL_DIR="$HOME/.local/share/bc250-display"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_NAME="bc250-display.service"
PYTHON="$INSTALL_DIR/venv/bin/python"

if [[ ${EUID} -eq 0 ]]; then echo 'Execute como usuário normal, sem sudo.' >&2; exit 1; fi
for cmd in git python3 systemctl; do
  command -v "$cmd" >/dev/null || { echo "Comando necessário ausente: $cmd" >&2; exit 1; }
done

if ! command -v sensors >/dev/null 2>&1; then
  echo 'Aviso: sensors não disponível. O monitor tentará usar os sensores hwmon do kernel.'
fi

mkdir -p "$(dirname "$INSTALL_DIR")" "$SERVICE_DIR"
if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo 'Atualizando projeto...'
  git -C "$INSTALL_DIR" pull --ff-only
elif [[ -e "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
  echo "Diretório ocupado: $INSTALL_DIR. Faça backup ou remova-o antes de instalar." >&2
  exit 1
else
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

if ! python3 -m venv "$INSTALL_DIR/venv"; then
  echo 'Não foi possível criar o venv. Verifique se python3-venv/ensurepip está disponível no Bazzite.' >&2
  exit 1
fi
"$PYTHON" -m pip install --upgrade pyserial
"$PYTHON" -c 'import serial; print("PySerial OK")'

cat > "$SERVICE_DIR/$SERVICE_NAME" <<EOF_SERVICE
[Unit]
Description=AMD BC250 Display Status - Bazzite (USB ESP32)
After=default.target

[Service]
Type=simple
ExecStart=$PYTHON -u $INSTALL_DIR/stellar_monitor.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF_SERVICE

# Impede que o serviço antigo concorra pela mesma porta serial.
if systemctl --user list-unit-files stellar-monitor.service --no-legend 2>/dev/null | grep -q stellar-monitor; then
  systemctl --user disable --now stellar-monitor.service || true
fi
systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE_NAME"

if [[ -e /dev/ttyACM0 || -e /dev/ttyUSB0 ]]; then
  echo 'Porta serial encontrada. Verifique permissões se houver Permission denied.'
fi
if getent group dialout >/dev/null && ! id -nG | tr ' ' '\n' | grep -qx dialout; then
  echo 'ATENÇÃO: seu usuário não pertence ao grupo dialout.'
  echo 'Se necessário, execute: sudo usermod -aG dialout "$USER"; depois encerre a sessão e entre novamente.'
fi

echo "Instalação finalizada. Status: systemctl --user status $SERVICE_NAME"
echo "Logs: journalctl --user -u $SERVICE_NAME -f"
echo 'O serviço inicia automaticamente quando a sessão de usuário é iniciada.'
