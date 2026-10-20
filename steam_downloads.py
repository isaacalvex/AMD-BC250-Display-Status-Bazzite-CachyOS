#!/usr/bin/env python3
"""Leitura local, somente leitura, de downloads do cliente Steam no Linux.

Steam não oferece uma API pública estável de telemetria para o cliente.
Os valores podem ser atualizados em checkpoints, não a cada segundo.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_ACF_FIELD = re.compile(r'^\s*"([^"]+)"\s*"([^"]*)"\s*$', re.M)
_RATE = re.compile(r'Current download rate:\s*([0-9]+(?:\.[0-9]+)?)\s*Mbps', re.I)
_LOG_STAMP = re.compile(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]')
_APP_MANIFEST = re.compile(r'^appmanifest_(\d+)\.acf$')
# StateFlags Steam: 256=UpdateRunning, 512=UpdatePaused,
# 1024=UpdateStarted, 1048576=Downloading.
_RUNNING = 256 | 1024 | 1048576
_PAUSED = 512
_MAX_RATE_AGE = 25.0


@dataclass(frozen=True)
class Download:
    appid: str
    name: str
    percent: int
    speed_mb_s: float | None
    completed: int
    total: int
    source: str


def _read(path: Path, limit: int = 2_000_000) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _number(value: str) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def steam_roots(home: Path | None = None) -> list[Path]:
    """Localiza Steam nativa, Flatpak e bibliotecas em outras unidades."""
    home = home or Path.home()
    override = os.environ.get("STELLAR_STEAM_ROOT", "").strip()
    candidates = [Path(override).expanduser()] if override else [
        home / ".local/share/Steam",
        home / ".steam/root",
        home / ".steam/steam",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        home / ".var/app/com.valvesoftware.Steam/.steam/root",
    ]
    result = []
    seen = set()

    def include(root: Path):
        try:
            resolved = root.resolve(strict=True)
        except (OSError, RuntimeError):
            return
        if resolved in seen or not (resolved / "steamapps").is_dir():
            return
        seen.add(resolved)
        result.append(resolved)

    for root in candidates:
        include(root)
    # Os caminhos nas libraryfolders.vdf referem-se à raiz da biblioteca.
    for root in list(result):
        vdf = _read(root / "steamapps/libraryfolders.vdf")
        for path in re.findall(r'^\s*"path"\s*"([^"]+)"', vdf, re.M | re.I):
            include(Path(path.replace(r"\\", "\\")))
    return result


def _steam_rate(roots: list[Path], now: float) -> float | None:
    """Velocidade global que o próprio Steam escreveu recentemente no log."""
    latest_time = 0.0
    latest_value = None
    for root in roots:
        log = root / "logs/content_log.txt"
        try:
            with log.open("rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 96 * 1024))
                lines = f.read().decode("utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            match = _RATE.search(line)
            if not match:
                continue
            ts = _LOG_STAMP.match(line)
            if not ts:
                continue
            try:
                recorded = datetime.strptime(ts.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
                speed = float(match.group(1)) / 8.0  # megabits/s -> MB/s
            except (ValueError, OverflowError):
                continue
            if 0 <= now - recorded <= _MAX_RATE_AGE and recorded >= latest_time:
                latest_time = recorded
                latest_value = speed
            break
    return latest_value


class SteamDownloadTracker:
    def __init__(self, home: Path | None = None):
        self.home = home
        self.previous: dict[tuple[str, str], tuple[int, float]] = {}
        self.last_roots: list[Path] = []

    def scan(self) -> Download | None:
        roots = steam_roots(self.home)
        self.last_roots = roots
        now = time.time()
        speed_from_log = _steam_rate(roots, now)
        candidates: list[tuple[float, Download]] = []
        updated: dict[tuple[str, str], tuple[int, float]] = {}
        for root in roots:
            apps = root / "steamapps"
            try:
                manifests = list(apps.glob("appmanifest_*.acf"))
            except OSError:
                continue
            for manifest in manifests:
                match = _APP_MANIFEST.match(manifest.name)
                if not match:
                    continue
                fields = dict(_ACF_FIELD.findall(_read(manifest)))
                appid = match.group(1)
                total = _number(fields.get("BytesToDownload", "0"))
                completed = _number(fields.get("BytesDownloaded", "0"))
                flags = _number(fields.get("StateFlags", "0"))
                key = (str(root), appid)
                previous = self.previous.get(key)
                updated[key] = (completed, now)

                if not total or completed >= total:
                    continue
                if not flags & _RUNNING or flags & _PAUSED:
                    continue

                # Apenas contadores Steam para porcentagem. Não mistura
                # BytesToStage com BytesToDownload: etapas diferentes.
                pct = min(99, round(completed * 100 / total))
                measured = None
                delta = 0
                if previous and completed >= previous[0]:
                    delta = completed - previous[0]
                    seconds = now - previous[1]
                    if delta > 0 and seconds > 0:
                        measured = delta / seconds / 1_000_000
                # A taxa global do log só é atribuída quando uma única
                # transferência está concorrendo. Com várias, o delta do
                # próprio aplicativo é a única aproximação válida.
                name = (fields.get("name") or f"AppID {appid}").strip()
                name = " ".join(name.split())[:100]
                candidate = Download(appid, name, pct, measured,
                                     completed, total, str(manifest))
                # Prioriza app cujo progresso mudou, depois o que tem
                # download flag e a atividade mais recente.
                rank = (100 if delta > 0 else 0) + (
                    30 if flags & 1048576 else 0
                ) + completed / total
                candidates.append((rank, candidate))

        self.previous = updated
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        chosen = candidates[0][1]
        # Velocidade reportada nos logs pode ser global. Só a usamos com
        # uma transferência; ao contrário, recorremos ao delta individual.
        speed = speed_from_log if len(candidates) == 1 and speed_from_log is not None else chosen.speed_mb_s
        return Download(chosen.appid, chosen.name, chosen.percent,
                        round(speed, 1) if speed is not None else None,
                        chosen.completed, chosen.total, chosen.source)
