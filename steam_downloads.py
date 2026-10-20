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
_MAX_RATE_AGE = 100.0


@dataclass(frozen=True)
class Download:
    appid: str
    name: str
    percent: int
    speed_mb_s: float | None
    completed: int
    total: int
    source: str
    phase: str = "download"


def _read(path: Path, limit: int = 2_000_000) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _manifest_fields(data: str) -> dict[str, str]:
    """Campos de AppState, sem confundir com dados de DLCs aninhados."""
    depth = 0
    fields: dict[str, str] = {}
    for line in data.splitlines():
        stripped = line.strip()
        if stripped == "{":
            depth += 1
        elif stripped == "}":
            depth = max(0, depth - 1)
        elif depth == 1:
            match = _ACF_FIELD.match(line)
            if match:
                fields[match.group(1)] = match.group(2)
    return fields


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


# Esses formatos foram conferidos com content_log.txt reais da Steam Linux.
_EVENT = re.compile(r'AppID\s+(\d+)\s+(?:(App|Shader)\s+)?(update changed|state changed)\s*:\s*(.*)', re.I)
_STARTED = re.compile(r'AppID\s+(\d+)\s+update started\s*:\s*download\s+(\d+)/(\d+)', re.I)
_STAGE = re.compile(r'\bstage\s+(\d+)/(\d+)', re.I)
_FINISHED = re.compile(r'AppID\s+(\d+)\s+finished update\b', re.I)
# Uma transferência grande pode passar horas sem novo evento de estado.
# É necessário observar o ÚLTIMO estado registrado, não somente os últimos 8 min.
_LOG_ACTIVITY_WINDOW = 6 * 3600


def _new_event() -> dict:
    return {"time": 0.0, "active": False, "kind": None,
            "app_active": False, "shader_active": False,
            "completed": 0, "total": 0,
            "staged": 0, "stage_total": 0,
            "phase": None, "finished": False, "started": False}


def _content_events(roots: list[Path], now: float) -> dict[str, dict]:
    """Estado da TAREFA Steam completa: download + processamento/instalação.

    Cada AppID é genérico. Itens aguardando na fila não são executados.
    Os sinais explícitos de término prevalecem sobre manifests atrasados.
    """
    found: dict[str, dict] = {}
    for root in roots:
        path = root / "logs/content_log.txt"
        try:
            with path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                stream.seek(max(0, stream.tell() - 2 * 1024 * 1024))
                lines = stream.read().decode("utf-8", "replace").splitlines()
        except OSError:
            continue
        for line in lines:
            stamp = _LOG_STAMP.match(line)
            if not stamp:
                continue
            try:
                when = datetime.strptime(
                    stamp.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
            except ValueError:
                continue
            if when > now + 60 or now - when > _LOG_ACTIVITY_WINDOW:
                continue
            finished = _FINISHED.search(line)
            if finished:
                event = found.setdefault(finished.group(1), _new_event())
                if when >= event["time"]:
                    event.update(time=when, active=False, app_active=False,
                                 shader_active=False, phase="complete",
                                 kind=None, finished=True)
                continue
            started = _STARTED.search(line)
            if started:
                appid = started.group(1)
                event = found.setdefault(appid, _new_event())
                if when >= event["time"]:
                    event["completed"] = int(started.group(2))
                    event["total"] = int(started.group(3))
                    stage = _STAGE.search(line)
                    if stage:
                        event["staged"] = int(stage.group(1))
                        event["stage_total"] = int(stage.group(2))
                    event["started"] = True
                    event["finished"] = False
                    event["time"] = when
                continue
            state = _EVENT.search(line)
            if not state:
                continue
            appid, update_kind, event_type, status = state.groups()
            event = found.setdefault(appid, _new_event())
            if when < event["time"]:
                continue
            lower = status.lower()
            if event_type.lower() == "update changed":
                kind = "shader" if (update_kind or "").lower() == "shader" else "app"
                key = kind + "_active"
                running = ("running update" in lower or "running," in lower)
                stopped = any(token in lower for token in (
                    "stopping", "paused", "suspended")) or lower.strip() == "none"
                # "Running Update,Staging" e "Running Update,Committing"
                # são etapas ATIVAS, apesar de já terem baixado 100% pela rede.
                if stopped:
                    event[key] = False
                elif running:
                    event[key] = True
                # Nenhum evento de fila começa a execução sozinho.
                if running and not stopped:
                    event["kind"] = kind
                    event["phase"] = (
                        "download" if "downloading" in lower else
                        "install" if any(k in lower for k in (
                            "staging", "verifying", "committing",
                            "preallocating", "reconfiguring", "installing")) else
                        event["phase"] or "processing")
                    event["finished"] = False
                elif event["kind"] == kind and not event[key]:
                    event["kind"] = ("app" if event["app_active"] else
                                     "shader" if event["shader_active"] else None)
            elif ("fully installed" in lower and "update running" not in lower):
                event.update(app_active=False, shader_active=False,
                             kind=None, phase="complete", finished=True)
            elif any(token in lower for token in (
                    "update paused", "uninstalled", "suspended")):
                event.update(app_active=False, shader_active=False, kind=None)
            event["active"] = bool(event["app_active"] or event["shader_active"])
            event["time"] = when
    return found


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
        events = _content_events(roots, now)
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
                fields = _manifest_fields(_read(manifest))
                appid = match.group(1)
                total = _number(fields.get("BytesToDownload", "0"))
                completed = _number(fields.get("BytesDownloaded", "0"))
                stage_total = _number(fields.get("BytesToStage", "0"))
                staged = _number(fields.get("BytesStaged", "0"))
                flags = _number(fields.get("StateFlags", "0"))
                event = events.get(appid)
                if event and event["finished"]:
                    continue
                if event:
                    if not total:
                        total = event["total"]
                    if total == event["total"]:
                        completed = max(completed, event["completed"])
                    if not stage_total:
                        stage_total = event["stage_total"]
                    if stage_total == event["stage_total"]:
                        staged = max(staged, event["staged"])

                key = (str(root), appid)
                previous = self.previous.get(key)
                updated[key] = (completed, now)

                # A tarefa continua ativa durante instalação/processamento,
                # mas um app apenas "Update Queued/Started" não está rodando.
                log_active = bool(event and event["active"])
                file_downloading = bool(flags & 1048576)
                file_processing = bool(flags & 256)
                if event is not None:
                    active = log_active
                else:
                    active = file_downloading or (
                        file_processing and (total or stage_total))
                if not active or (flags & _PAUSED and not log_active):
                    continue

                phase = event["phase"] if event and event["phase"] else "download"
                if completed >= total and total > 0 and phase == "download":
                    phase = "install" if stage_total and staged < stage_total else "processing"

                # Percentual da tarefa COMPLETA, não só bytes baixados.
                # Caso os totais não estejam disponíveis, não inventamos 100%.
                overall_total = total + stage_total
                if overall_total > 0:
                    done = min(completed, total) + min(staged, stage_total)
                    pct = max(0, min(99, round(100 * done / overall_total)))
                else:
                    continue

                measured = None
                delta = 0
                if phase == "download" and previous and completed >= previous[0]:
                    delta = completed - previous[0]
                    seconds = now - previous[1]
                    if delta > 0 and seconds > 0:
                        measured = delta / seconds / 1_000_000
                # Durante instalação a rede pode corretamente estar em 0 MB/s.
                if phase != "download":
                    measured = 0.0
                name = " ".join((fields.get("name") or
                                  f"AppID {appid}").split())[:100]
                candidate = Download(
                    appid, name, pct, measured, completed, total,
                    str(manifest) + " (estimativa via ACF/log)", phase)
                # Prioriza tarefas REALMENTE executando, mesmo com rede 0.
                age = max(0, now-event["time"]) if event else 999999
                rank = (1000 if log_active else 0) + (
                    90 if age < 90 else 0) + (
                    30 if delta > 0 else 0) + completed / max(total, 1)
                candidates.append((rank, candidate))

        self.previous = updated
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        chosen = candidates[0][1]
        # Taxa global do log só se refere ao jogo com uma única transferência
        # ativa e na fase de download. Na instalação exibir 0 MB/s.
        speed = chosen.speed_mb_s
        if chosen.phase == "download" and len(candidates) == 1:
            if speed_from_log is not None:
                speed = speed_from_log
        return Download(
            chosen.appid, chosen.name, chosen.percent,
            round(speed, 1) if speed is not None else None,
            chosen.completed, chosen.total, chosen.source, chosen.phase)
