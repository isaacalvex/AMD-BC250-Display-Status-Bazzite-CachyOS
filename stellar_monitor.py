#!/usr/bin/env python3
"""Le temperaturas reais da AMD BC250 e envia ao ESP32 pela USB serial."""
import glob
import os
import re
import signal
import subprocess
import time

import serial

BAUDRATE = 115200
INTERVALO = 1.0
rodando = True


def encerrar(_sig, _frame):
    global rodando
    rodando = False


signal.signal(signal.SIGINT, encerrar)
signal.signal(signal.SIGTERM, encerrar)


def portas_candidatas():
    # Permite fixar a porta quando há vários dispositivos seriais conectados.
    configurada = os.environ.get('BC250_SERIAL_PORT', '').strip()
    if configurada:
        return [configurada]
    # A seleção de ESP32 via by-id é preferida a uma porta arbitrária.
    ids = sorted(glob.glob('/dev/serial/by-id/*'))
    esp = [p for p in ids if any(k in p.lower() for k in ('esp32', 'espressif', 'usb_jtag', 'cp210', 'ch340'))]
    return esp + [p for p in ids if p not in esp] + sorted(glob.glob('/dev/ttyACM*')) + sorted(glob.glob('/dev/ttyUSB*'))


def ler_cpu():
    # Fonte alternativa independente do comando sensors (k10temp).
    for arquivo in sorted(glob.glob('/sys/class/hwmon/hwmon*/temp*_input')):
        try:
            pasta = os.path.dirname(arquivo)
            with open(os.path.join(pasta, 'name'), encoding='utf-8') as f:
                if f.read().strip().lower() != 'k10temp':
                    continue
            rotulo = arquivo.replace('_input', '_label')
            if os.path.isfile(rotulo):
                with open(rotulo, encoding='utf-8') as f:
                    if f.read().strip().lower() not in ('tctl', 'tdie'):
                        continue
            with open(arquivo, encoding='utf-8') as f:
                valor = int(f.read().strip()) / 1000.0
            if -20 <= valor <= 120:
                return valor
        except (OSError, ValueError):
            continue
    try:
        out = subprocess.run(['sensors'], capture_output=True, text=True, timeout=1).stdout
        for linha in out.splitlines():
            if linha.strip().startswith('Tctl:'):
                m = re.search(r'([+-]?\d+(?:\.\d+)?)\s*°C', linha)
                if m and -20 <= float(m.group(1)) <= 120:
                    return float(m.group(1))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def ler_gpu():
    for path in sorted(glob.glob('/sys/class/drm/card*/device/hwmon/hwmon*/temp*_input')):
        try:
            with open(os.path.join(os.path.dirname(path), 'name'), encoding='utf-8') as f:
                if 'amdgpu' not in f.read().lower():
                    continue
            with open(path, encoding='utf-8') as f:
                temp = int(f.read().strip()) / 1000
            if 0 <= temp <= 120:
                return temp
        except (OSError, ValueError):
            pass
    try:
        out = subprocess.run(['sensors'], capture_output=True, text=True, timeout=1).stdout
        dentro_gpu = False
        for linha in out.splitlines():
            s = linha.strip()
            if s.startswith('amdgpu-pci'):
                dentro_gpu = True
            elif dentro_gpu and s.startswith('edge:'):
                m = re.search(r'([+-]?\d+(?:\.\d+)?)\s*°C', s)
                if m and 0 <= float(m.group(1)) <= 120:
                    return float(m.group(1))
            elif not s:
                dentro_gpu = False
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def main():
    print('AMD BC250 Display Status - Bazzite', flush=True)
    while rodando:
        serial_port = None
        for porta in portas_candidatas():
            try:
                serial_port = serial.Serial(porta, BAUDRATE, timeout=0.5, write_timeout=0.5)
                print(f'Porta conectada: {porta}', flush=True)
                time.sleep(2)
                break
            except (OSError, serial.SerialException) as ex:
                print(f'Não foi possível abrir {porta}: {ex}', flush=True)
        if serial_port is None:
            print('ESP32 não localizado. Tentando novamente...', flush=True)
            time.sleep(3)
            continue
        with serial_port as ser:
            while rodando:
                cpu, gpu = ler_cpu(), ler_gpu()
                if cpu is not None and gpu is not None:
                    try:
                        pacote = f'CPU:{cpu:.1f};GPU:{gpu:.1f}\n'
                        ser.write(pacote.encode())
                        ser.flush()
                        print(pacote.strip(), flush=True)
                    except (OSError, serial.SerialException) as ex:
                        print(f'USB desconectado: {ex}', flush=True)
                        break
                else:
                    print('Sem leitura válida de CPU/GPU.', flush=True)
                time.sleep(INTERVALO)


if __name__ == '__main__':
    main()
