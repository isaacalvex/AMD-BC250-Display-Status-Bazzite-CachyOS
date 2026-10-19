#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${BC250_REPO_URL:-https://github.com/isaacalvex/AMD-BC250-Display-Status-BazziteOS.git}"
INSTALL_DIR="$HOME/.local/share/bc250-display"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_NAME="bc250-display.service"
PYTHON="$INSTALL_DIR/venv/bin/python"
RELOGIN_REQUIRED=0

info() { printf '\n[BC250] %s\n' "$*"; }
warn() { printf '\n[ATENÇÃO] %s\n' "$*" >&2; }
die() { printf '\n[ERRO] %s\n' "$*" >&2; exit 1; }
trap 'warn "Instalação interrompida na linha $LINENO. Confira a mensagem anterior."' ERR

[[ $EUID -ne 0 ]] || die 'Execute como usuário normal, sem sudo.'
for cmd in git python3 systemctl stat id getent; do
  command -v "$cmd" >/dev/null 2>&1 || die "Comando obrigatório ausente: $cmd"
done

# ESP32-C3 por USB nativa; identificadores persistentes têm prioridade.
encontrar_esp32() {
  local porta nome
  if [[ -n "${BC250_SERIAL_PORT:-}" ]]; then
    [[ -e "$BC250_SERIAL_PORT" ]] && printf '%s\n' "$BC250_SERIAL_PORT"
    return 0
  fi
  for porta in /dev/serial/by-id/*; do
    [[ -e "$porta" ]] || continue
    nome="${porta,,}"
    if [[ "$nome" == *espressif* || "$nome" == *esp32* || "$nome" == *usb_jtag* ]]; then
      printf '%s\n' "$porta"
      return 0
    fi
  done
  for porta in /dev/serial/by-id/*; do
    [[ -e "$porta" ]] || continue
    nome="${porta,,}"
    if [[ "$nome" == *cp210* || "$nome" == *ch340* ]]; then
      printf '%s\n' "$porta"
      return 0
    fi
  done
  return 0
}

info 'Verificando acesso à USB serial'
PORTA="$(encontrar_esp32)"
if [[ -n "$PORTA" ]]; then
  ALVO="$(readlink -f "$PORTA")"
  info "Dispositivo detectado: $PORTA -> $ALVO"
  GRUPO="$(stat -Lc '%G' "$ALVO")"
  DONO="$(stat -Lc '%U' "$ALVO")"
  PERMS="$(stat -Lc '%A' "$ALVO")"
  info "Permissões: $PERMS | dono: $DONO | grupo: $GRUPO"
  if [[ ! -r "$ALVO" || ! -w "$ALVO" ]]; then
    if [[ "$GRUPO" != "root" && "$GRUPO" != "UNKNOWN" ]] && getent group "$GRUPO" >/dev/null 2>&1; then
      if ! id -nG "$USER" | tr ' ' '\n' | grep -Fxq "$GRUPO"; then
        info "É necessário adicionar $USER ao grupo $GRUPO."
        if command -v sudo >/dev/null 2>&1 && sudo usermod -aG "$GRUPO" "$USER"; then
          RELOGIN_REQUIRED=1
          info "Usuário adicionado ao grupo $GRUPO."
        else
          warn "Não foi possível adicionar ao grupo. Execute: sudo usermod -aG $GRUPO $USER"
        fi
      else
        RELOGIN_REQUIRED=1
        warn "O usuário já pertence ao grupo $GRUPO, mas a sessão atual ainda não tem acesso."
      fi
    else
      warn 'A porta não usa um grupo de acesso comum. Verifique ACL, regras udev e permissões do dispositivo.'
    fi
  else
    info 'Acesso de leitura e escrita à porta está disponível na sessão atual.'
  fi
else
  warn 'ESP32 não encontrado agora. Conecte-o pela USB e execute bash setup.sh novamente para configurar as permissões.'
fi

info 'Baixando/atualizando arquivos'
mkdir -p "$(dirname "$INSTALL_DIR")" "$SERVICE_DIR"
if [[ -d "$INSTALL_DIR/.git" ]]; then
  ORIGIN="$(git -C "$INSTALL_DIR" remote get-url origin || true)"
  if [[ "$ORIGIN" == *AMD-BC250-Display-Status-BazziteOS* ]]; then
    git -C "$INSTALL_DIR" pull --ff-only
  else
    die "Existe outro projeto em $INSTALL_DIR (origin: $ORIGIN). Faça backup antes de prosseguir."
  fi
elif [[ -e "$INSTALL_DIR" ]] && [[ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
  die "Diretório ocupado: $INSTALL_DIR. Faça backup antes de prosseguir."
else
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

info 'Preparando Python em ambiente virtual'
python3 -m venv "$INSTALL_DIR/venv" || die 'Falha no venv; verifique ensurepip/python3 no Bazzite.'
"$PYTHON" -m pip install --upgrade pyserial
"$PYTHON" -c 'import serial; print("PySerial OK")'

if ! command -v sensors >/dev/null 2>&1; then
  warn 'Comando sensors indisponível. O monitor tentará ler diretamente os sensores hwmon.'
fi

info 'Criando e ativando serviço systemd do usuário'
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

if systemctl --user list-unit-files stellar-monitor.service --no-legend 2>/dev/null | grep -q stellar-monitor; then
  systemctl --user disable --now stellar-monitor.service || true
fi
systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
systemctl --user restart "$SERVICE_NAME"

info 'Instalação concluída'
echo 'Status: systemctl --user status bc250-display.service'
echo 'Logs:   journalctl --user -u bc250-display.service -f'
if (( RELOGIN_REQUIRED )); then
  warn 'IMPORTANTE: reinicie o computador ou encerre e abra a sessão para aplicar o acesso USB ao serviço.'
  warn 'O serviço já está instalado e iniciará automaticamente na próxima sessão.'
else
  info 'O serviço está habilitado para iniciar automaticamente na sessão do usuário.'
fi
