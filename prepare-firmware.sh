#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
mkdir -p firmware "$HOME/.local/bin" "$HOME/Arduino"
BIN="firmware/stellar_monitor.merged.bin"
SOURCE_HASH="firmware/stellar_monitor.source.sha256"
SKETCH="$HOME/.cache/stellar-app-monitor/stellar_monitor"
mkdir -p "$SKETCH"
# Sempre verifica a versão oficial atual do INO.
# Reutiliza BIN somente quando seu hash foi gerado dessa mesma versão.
echo "Consultando a versão mais recente do firmware STELLAR..."
curl -fLsS --retry 3 https://raw.githubusercontent.com/isaacalvex/AMD-BC250-Display-Status/main/stellar_monitor.ino -o "$SKETCH/stellar_monitor.ino.download"
mv "$SKETCH/stellar_monitor.ino.download" "$SKETCH/stellar_monitor.ino"
CURRENT_HASH="$(sha256sum "$SKETCH/stellar_monitor.ino" | cut -d' ' -f1)"
if [[ -s "$BIN" && -f "$SOURCE_HASH" && "$(cat "$SOURCE_HASH")" == "$CURRENT_HASH" ]]; then
  echo "Firmware já está atualizado: $BIN"
  exit 0
fi
echo "Firmware novo detectado; compilando para ESP32-C3..."
CLI="$HOME/.local/bin/arduino-cli"
if [[ ! -x "$CLI" ]]; then
  echo "Baixando Arduino CLI para o usuário (sem sudo)..."
  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh -o /tmp/stellar-arduino-install.sh
  env BINDIR="$HOME/.local/bin" sh /tmp/stellar-arduino-install.sh
fi
if [[ ! -f "$HOME/.arduino15/arduino-cli.yaml" ]]; then "$CLI" config init; fi
"$CLI" config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json || true
"$CLI" core update-index
"$CLI" core install esp32:esp32@3.3.12
"$CLI" lib update-index
"$CLI" lib install "GFX Library for Arduino@1.6.9"
"$CLI" lib install "U8g2@2.36.19"
"$CLI" compile --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc --export-binaries "$SKETCH"
FOUND="$(find "$SKETCH" -type f -name '*.merged.bin' -size +4k -print -quit)"
[[ -n "$FOUND" && -s "$FOUND" ]] || { echo "ERRO: firmware merged.bin não foi gerado"; exit 1; }
cp "$FOUND" "$BIN"
printf '%s\n' "$CURRENT_HASH" > "$SOURCE_HASH"
sha256sum "$BIN"
echo "Firmware pronto para atualização."
