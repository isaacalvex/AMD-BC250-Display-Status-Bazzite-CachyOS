#!/usr/bin/env python3
"""Seleciona a fonte de telemetria Steam sem bloquear o fallback do ESP32.

Uma sessão Steam CEF conectada NÃO comprova que o cliente esteja ocioso:
algumas versões enviam callbacks atrasados ou estados não reconhecidos.
"""
from __future__ import annotations

import time
from dataclasses import replace


def scan_task(cef, tracker, warn=None):
    """Prioriza CEF válido; sempre tenta logs/manifests quando CEF é inconclusivo.

    O fallback também é usado se o CEF falhar durante uma consulta.
    """
    try:
        live = cef.scan()
    except Exception as error:
        if warn is not None:
            warn(f"Falha temporária CEF: {error}")
        live = None
    if live is not None:
        return live

    # Exemplo real (Steam/Bazzite): overview entrega AppID e MB/s em
    # tempo real mas omite update_bytes_downloaded/update_bytes_to_download.
    # Preservar a velocidade REAL do mesmo AppID, mantendo explícito que
    # a porcentagem veio do appmanifest (não é telemetria ao vivo).
    files = tracker.scan()
    metrics = getattr(cef, "live_metrics", None)
    if files is None or metrics is None:
        return files
    appid, speed_mb_s, recorded_at = metrics
    if (str(appid) != str(files.appid) or speed_mb_s is None
            or time.monotonic() - recorded_at > 3.5):
        return files
    return replace(
        files,
        speed_mb_s=round(max(0.0, speed_mb_s), 1),
        source=files.source + " | velocidade Steam CEF ao vivo"
    )
