#!/usr/bin/env python3
"""Le temperaturas reais da AMD BC250 e envia ao ESP32 pela USB serial."""
import glob
import os
import re
import signal
import subprocess
import time
import sys
from pathlib import Path

import serial
from steam_downloads import SteamDownloadTracker
from steam_cef import SteamCEFReader

BAUDRATE = 115200
INTERVALO = 1.0  # Segundo: uma leitura e um envio em cada ciclo.
rodando = True


def encerrar(_sig, _frame):
    global rodando
    rodando = False


signal.signal(signal.SIGINT, encerrar)
signal.signal(signal.SIGTERM, encerrar)


def portas_candidatas():
    # Permite fixar a porta quando há vários dispositivos seriais conectados.
    configurada = os.environ.get('BC250_SERIAL_PORT', '').strip()
    if not configurada:
        try:
            configurada = (Path.home() / '.config/bc250-display/port').read_text(encoding='utf-8').strip()
        except OSError:
            pass
    if configurada and configurada.startswith('/dev/'):
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


def _nome_serial(nome):
    # Nunca deixe delimitadores e quebras de linha da Steam afetarem o protocolo.
    nome = re.sub(r'[;\r\n\x00-\x1f]', ' ', nome)
    nome = ' '.join(nome.split())
    # Deixa uma folga para o limite de buffer de 240 caracteres do ESP32.
    while len(nome.encode('utf-8')) > 140:
        nome = nome[:-1]
    return nome or 'Jogo'


def pacote_download(download):
    """Protocolo USB genérico: nunca depende do título ou AppID de um jogo."""
    nome = _nome_serial(download.name)
    velocidade = (f'{download.speed_mb_s:.1f}'
                  if download.speed_mb_s is not None else '-1')
    return (f'DL:1;PCT:{download.percent};SPEED:{velocidade};'
            f'NAME:{nome}\n').encode('utf-8')


def steam_status():
    from steam_downloads import _manifest_fields, _content_events, _read
    tracker = SteamDownloadTracker()
    cef = SteamCEFReader()
    info_cef = cef.scan()
    info_files = tracker.scan()
    info = info_cef or info_files
    print("Leitura CEF:", cef.diagnostic.status,flush=True)
    if cef.diagnostic.port is not None:
        print("Porta CEF:", cef.diagnostic.port,flush=True)
    print("Fonte usada:", info.source if info else "nenhuma",flush=True)
    cef.close()
    print("Diagnóstico Steam — nenhuma configuração será alterada.", flush=True)
    print("Bibliotecas Steam encontradas:", len(tracker.last_roots), flush=True)
    if not tracker.last_roots:
        print("Steam não localizada. Verifique instalação nativa/Flatpak, "
              "links ~/.steam e bibliotecas montadas.", flush=True)
        return
    for root in tracker.last_roots:
        print(" -", root, flush=True)
        apps = root / "steamapps"
        manifests = sorted(apps.glob("appmanifest_*.acf"))
        print(f"   appmanifest disponíveis: {len(manifests)}", flush=True)
        shown = 0
        for path in manifests:
            fields = _manifest_fields(_read(path))
            try:
                flags = int(fields.get("StateFlags", "0"))
                total = int(fields.get("BytesToDownload", "0"))
                done = int(fields.get("BytesDownloaded", "0"))
            except ValueError:
                continue
            if (flags & (256 | 512 | 1024 | 1048576)) or (0 < done < total):
                print(f"   {path.stem}: {fields.get('name', '?')[:55]} | "
                      f"StateFlags={flags} | BytesDownloaded={done} | "
                      f"BytesToDownload={total}", flush=True)
                shown += 1
                if shown >= 12:
                    print("   ...mais candidatos omitidos...", flush=True)
                    break
        log = root / "logs/content_log.txt"
        print(f"   content_log.txt: {'encontrado' if log.exists() else 'ausente'}",
              flush=True)
        if log.is_file():
            try:
                with log.open("rb") as f:
                    f.seek(0, os.SEEK_END)
                    f.seek(max(0, f.tell() - 96 * 1024))
                    raw = f.read().decode("utf-8", errors="replace")
                matches = [line.strip() for line in raw.splitlines()
                           if "AppID " in line and
                           any(word in line for word in
                               ("update started", "update changed", "state changed"))]
                print("   Últimos eventos relacionados aos jogos:", flush=True)
                for line in matches[-8:]:
                    print("   ", line[:220], flush=True)
            except OSError as exc:
                print("   Erro na leitura do log:", exc, flush=True)
    recent = _content_events(tracker.last_roots, time.time())
    if recent:
        print("Atividade recente no log:", flush=True)
        for appid, event in list(recent.items())[-10:]:
            print(f"   AppID {appid}: ativo={event['active']}, "
                  f"tipo={event.get('kind') or 'nenhum'}, "
                  f"download={event['completed']}/{event['total']}", flush=True)
    if info is None:
        print("Resultado: nenhum jogo com download e porcentagem verificáveis.",
              flush=True)
        print("A Steam pode não ter atualizado os contadores no manifesto; "
              "confira os eventos acima.", flush=True)
    else:
        speed = f"{info.speed_mb_s:.1f} MB/s" if info.speed_mb_s is not None else "indisponível"
        print(f"Resultado: {info.name} (AppID {info.appid}) "
              f"{info.percent}% | {speed} | etapa={info.phase}", flush=True)
        print("Origem:", info.source, flush=True)




def cef_debug():
    """Inspeção SOMENTE LEITURA dos callbacks Downloads no SharedJSContext.

    Somente campos de downloads; não extrai cookies, conta, sessão ou URL.
    """
    import json
    cef=SteamCEFReader()
    print("=== Diagnóstico Steam CEF — apenas telemetria de download ===", flush=True)
    try:
        for sample in range(4):
            result=cef._query()
            print(f"[{sample + 1}/4] Porta: {cef.diagnostic.port}; "
                  f"Estado: {cef.diagnostic.status}", flush=True)
            if result is None:
                print("CEF: nenhuma resposta válida",flush=True)
            elif result.get("error"):
                print("API SteamClient:",str(result["error"])[:160],flush=True)
            else:
                summary={
                    "api":result.get("api",{}),
                    "gotOverview":result.get("gotOverview"),
                    "gotItems":result.get("gotItems"),
                    "overviewAgeMs":result.get("overviewAgeMs"),
                    "downloading":result.get("downloading"),
                    "overview":result.get("overview",{}),
                    "activeItems":[{
                        "appid":x.get("appid"),
                        "active":x.get("active"),
                        "completed":x.get("completed"),
                        "paused":x.get("paused"),
                        "downloaded_bytes":x.get("downloaded_bytes"),
                        "total_bytes":x.get("total_bytes"),
                    } for x in result.get("items",[])
                       if isinstance(x,dict) and x.get("active")][:3],
                    "itemsCount":len(result.get("items",[])),
                    "error":result.get("error")
                }
                print(json.dumps(summary,ensure_ascii=False,default=str),flush=True)
            if sample < 3:
                time.sleep(1)
    finally:
        cef.close()


def steam_watch(seconds=10):
    """Uma amostra por segundo, distinguindo fonte viva de arquivos defasados."""
    tracker = SteamDownloadTracker()
    cef = SteamCEFReader()
    print('Monitorando Steam por 10 segundos (1 consulta por segundo).', flush=True)
    snapshots=[]
    using_files=False
    try:
        for i in range(seconds):
            start = time.monotonic()
            live = cef.scan()
            fallback = tracker.scan() if live is None else None
            result = live or fallback
            if result:
                using_files = using_files or live is None
                speed = (f'{result.speed_mb_s:.1f} MB/s'
                         if result.speed_mb_s is not None else '-- MB/s (sem medição)')
                print(f'[{i+1:02d}/{seconds}] AppID {result.appid} | '
                      f'{result.name} | {result.percent}% | {speed} | '
                      f'etapa={result.phase} | {result.source}', flush=True)
                snapshots.append((result.appid,result.percent,result.speed_mb_s))
            else:
                print(f'[{i+1:02d}/{seconds}] Sem download ativo | '
                      f'{cef.diagnostic.status}', flush=True)
            time.sleep(max(0.0, INTERVALO-(time.monotonic()-start)))
    finally:
        cef.close()
    if using_files:
        print('AVISO: CEF indisponível: appmanifest/content_log são snapshots '
              'e NÃO fornecem progresso nem MB/s garantidos em tempo real.',
              flush=True)
    if len(snapshots) >= 5 and len(set(snapshots)) == 1:
        print('AVISO: Todas as leituras tiveram valores IDÊNTICOS. '
              'O ESP32 está recebendo os mesmos dados; não há confirmação '
              'de progresso ao vivo nesta fonte.', flush=True)



def main():
    print('Stellar Display - temperaturas + downloads Steam (Bazzite/CachyOS)', flush=True)
    tracker = SteamDownloadTracker()
    cef = SteamCEFReader()
    last_steam_report = 0.0
    last_steam_source = None
    last_steam_identity = None
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

        download_anterior = False
        with serial_port as ser:
            while rodando:
                inicio_ciclo = time.monotonic()
                try:
                    cpu, gpu = ler_cpu(), ler_gpu()
                    if cpu is not None and gpu is not None:
                        pacote = f'CPU:{cpu:.1f};GPU:{gpu:.1f}\n'
                        ser.write(pacote.encode('ascii'))
                        print(pacote.strip(), flush=True)
                    try:
                        # Preferir valores fornecidos diretamente pelo cliente Steam.
                        # Sem CEF (recurso opcional), manter a leitura local
                        # por manifests/logs, que pode atrasar.
                        download = cef.scan()
                        # Quando o cliente informou explicitamente que está
                        # parado, não ressuscitar downloads antigos do ACF.
                        cef_idle = cef.diagnostic.status.startswith(
                            'CEF conectado, sem tarefa ativa')
                        if download is None and not cef_idle:
                            download = tracker.scan()
                    except Exception as ex:
                        print(f'Steam: falha temporária na leitura: {ex}', flush=True)
                        download = None

                    if download is not None:
                        nome = _nome_serial(download.name)
                        ser.write(pacote_download(download))
                        if (last_steam_identity != (download.appid, download.percent) or
                            last_steam_source != download.source or
                            time.monotonic() - last_steam_report >= 8):
                            taxa = (f'{download.speed_mb_s:.1f} MB/s'
                                    if download.speed_mb_s is not None else 'indisponível')
                            print(f'Steam tarefa ({download.source}): {nome} | '
                                  f'{download.percent}% | {taxa} | etapa={download.phase}', flush=True)
                            if download.source.startswith('Steam CEF'):
                                print('Fonte: Steam CEF ao vivo (percentual total estimado).',flush=True)
                            else:
                                print('AVISO: Steam CEF indisponível; progresso baseado em arquivos '
                                      'pode não atualizar em tempo real.',flush=True)
                            last_steam_report = time.monotonic()
                            last_steam_source = download.source
                            last_steam_identity = (download.appid, download.percent)
                        download_anterior = True
                    elif download_anterior:
                        ser.write(b'DL:0\n')
                        print('Steam: tarefa completa/sem instalação ativa; tela térmica.', flush=True)
                        last_steam_identity = None
                        last_steam_source = None
                        download_anterior = False

                    ser.flush()
                except (OSError, serial.SerialException) as ex:
                    print(f'USB desconectado: {ex}', flush=True)
                    break
                # Cadência baseada em relógio monotônico: a duração
                # da leitura não se SOMA a cada intervalo de um segundo.
                decorrido = time.monotonic() - inicio_ciclo
                time.sleep(max(0.0, INTERVALO - decorrido))


if __name__ == '__main__':
    if '--cef-debug' in sys.argv:
        cef_debug()
    elif '--steam-status' in sys.argv:
        steam_status()
    elif '--steam-watch' in sys.argv:
        steam_watch()
    else:
        main()
