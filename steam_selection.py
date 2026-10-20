#!/usr/bin/env python3
"""Seleciona a fonte de telemetria Steam sem bloquear o fallback do ESP32.

Uma sessão Steam CEF conectada NÃO comprova que o cliente esteja ocioso:
algumas versões enviam callbacks atrasados ou estados não reconhecidos.
"""
from __future__ import annotations


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
    return tracker.scan()
