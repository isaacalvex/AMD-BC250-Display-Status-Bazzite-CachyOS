#!/usr/bin/env python3
"""Leitura SOMENTE LEITURA do progresso Steam via CEF/CDP local, quando habilitado.

Não liga depuração, não altera Steam, não executa ações SteamClient, não abre
portas nem se conecta a endereços remotos. Caso CEF não esteja disponível,
retorna None e o monitor pode usar sua fonte local de arquivos (estimativa).
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit
from pathlib import Path

from steam_downloads import Download, _manifest_fields, _read, steam_roots


# Estes campos são expostos pelo SteamClient.Downloads.RegisterForDownloadOverview
# em clientes Steam modernos. A porcentagem visual da Steam pode incluir
# download E preparação/instalação, não apenas a etapa de transferência.
_JS = r"""(async () => {
  const d = window.SteamClient && window.SteamClient.Downloads;
  if (!d) return {error: "SteamClient.Downloads indisponivel"};
  if (!window.__stellarDownloadReader) {
    const cache = window.__stellarDownloadReader = {
      overview:null, items:[], overviewTime:0, itemsTime:0,
      error:null, ready:false
    };
    try {
      if (typeof d.RegisterForDownloadOverview === 'function')
        cache.overviewListener = d.RegisterForDownloadOverview(v => {
          cache.overview = v; cache.overviewTime = Date.now();
        });
      if (typeof d.RegisterForDownloadItems === 'function')
        cache.itemsListener = d.RegisterForDownloadItems((active,items) => {
          cache.items = Array.isArray(items) ? items : [];
          cache.itemsTime = Date.now();
          cache.downloading = !!active;
        });
      cache.ready = true;
    } catch(e) {
      cache.error = String(e).slice(0,160);
    }
  }
  const cache = window.__stellarDownloadReader;
  // SteamClient informa os dados assincronamente via callbacks. A
  // primeira consulta não deve confundir "ainda não recebido" com "ocioso".
  if (!cache.overview && !cache.itemsTime) {
    await new Promise(resolve => setTimeout(resolve, 550));
  }
  let o = cache.overview;
  // API opcional, algumas versões do Steam não possuem este método.
  if (typeof d.GetDownloadOverview === 'function') {
    try {
      const latest = await d.GetDownloadOverview();
      if (latest) {
        o = latest;
        cache.overview = latest;
        cache.overviewTime = Date.now();
      }
    } catch (e) {}
  }
  const keys = [
    'update_appid','update_state','paused',
    'update_bytes_downloaded','update_bytes_to_download',
    'update_bytes_staged','update_bytes_to_stage',
    'update_bytes_processed','update_bytes_to_process',
    'update_network_bytes_per_second','update_disc_bytes_per_second',
    'update_is_shader','update_is_install'
  ];
  const overview = {};
  if (o) for (const k of keys) {
    if (o[k] !== undefined) overview[k] = o[k];
  }
  const items = (cache.items || []).slice(0,30).map(x => ({
    appid:x.appid, active:x.active, paused:x.paused,
    completed:x.completed, name:x.name,
    downloaded_bytes:x.downloaded_bytes, total_bytes:x.total_bytes
  }));
  return {
    overview, items,
    gotOverview: !!o, gotItems: cache.itemsTime > 0,
    downloading: cache.downloading === true,
    overviewAgeMs: cache.overviewTime ? Date.now()-cache.overviewTime : null,
    itemsAgeMs: cache.itemsTime ? Date.now()-cache.itemsTime : null,
    error: cache.error,
    api: {
      overviewSubscription: typeof d.RegisterForDownloadOverview === 'function',
      itemsSubscription: typeof d.RegisterForDownloadItems === 'function',
      directOverview: typeof d.GetDownloadOverview === 'function'
    }
  };
})()"""

# SteamClient.Downloads pode usar estados mais detalhados conforme a versão
# do cliente. O Bazzite reportou literalmente state="downloading" com
# update_appid=1364780 (Street Fighter 6) e contadores disponíveis.
_ACTIVE_UPDATE_STATES = frozenset({
    "starting", "updating", "stopping", "running",
    "downloading", "staging", "installing", "processing",
    "verifying", "validating", "committing", "preallocating",
    "reconfiguring", "unpacking", "patching", "preparing",
    "allocating", "finalizing",
})
_INSTALL_UPDATE_STATES = frozenset({
    "staging", "installing", "processing", "verifying",
    "validating", "committing", "preallocating", "reconfiguring",
    "unpacking", "patching", "allocating", "finalizing",
})


def _state_is_active(state: str) -> bool:
    """Estado em execução; evita selecionar aplicações apenas na fila."""
    normalized = state.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in _ACTIVE_UPDATE_STATES:
        return True
    # Aceita fases mais específicas, por exemplo "verifying_installed".
    return any(normalized.startswith(phase + "_")
               for phase in _ACTIVE_UPDATE_STATES)


def _state_is_install(state: str) -> bool:
    normalized = state.strip().lower().replace("-", "_").replace(" ", "_")
    return any(normalized == phase or normalized.startswith(phase + "_")
               for phase in _INSTALL_UPDATE_STATES)


@dataclass(frozen=True)
class CEFDiagnostic:
    status: str
    port: int | None


def steam_ui_progress(overview: dict) -> int | None:
    """Progresso geral: bytes baixados + preparação/instalação em disco.

    Processamento é usado como alternativa à preparação quando não há
    contador de staging; não se somam as duas fases indiscriminadamente.
    """
    try:
        network_total = max(0, int(overview.get("update_bytes_to_download") or 0))
        network_done = max(0, int(overview.get("update_bytes_downloaded") or 0))
        staged_total = max(0, int(overview.get("update_bytes_to_stage") or 0))
        staged_done = max(0, int(overview.get("update_bytes_staged") or 0))
        processed_total = max(0, int(overview.get("update_bytes_to_process") or 0))
        processed_done = max(0, int(overview.get("update_bytes_processed") or 0))
    except (TypeError, ValueError, OverflowError):
        return None
    disk_total = staged_total or processed_total
    disk_done = staged_done if staged_total else processed_done
    total = network_total + disk_total
    if total <= 0:
        return None
    completed = min(network_done, network_total) + min(disk_done, disk_total)
    # Enquanto Steam estiver trabalhando, não marcar 100% prematuramente.
    return max(0, min(99, round(100 * completed / total)))


def _steam_app_name(appid: str, cache: dict[str,str]) -> str:
    if appid in cache:
        return cache[appid]
    for root in steam_roots():
        try:
            manifests=list((root/"steamapps").glob(f"appmanifest_{appid}.acf"))
        except OSError:
            continue
        for manifest in manifests:
            fields=_manifest_fields(_read(manifest))
            name=fields.get("name","").strip()
            if name:
                cache[appid]=name[:120]
                return cache[appid]
    return f"AppID {appid}"


class SteamCEFReader:
    """Consulta CDP local, sem habilitar acesso remoto ou depuração do cliente."""
    def __init__(self):
        self._connection=None
        self._socket_port=None
        self._message_id=0
        self._name_cache={}
        self._retry_after=0.0
        self.diagnostic=CEFDiagnostic("CEF ainda não consultado",None)

    def close(self):
        if self._connection is not None:
            try:self._connection.close()
            except Exception:pass
        self._connection=None
        self._socket_port=None

    def _connect(self):
        import websocket
        if self._connection is not None:
            return True
        if time.monotonic() < self._retry_after:
            return False
        env=os.environ.get("STELLAR_STEAM_CEF_PORT","").strip()
        try:
            ports=[int(env)] if env else [8080,8081]
        except ValueError:
            self.diagnostic=CEFDiagnostic("STELLAR_STEAM_CEF_PORT inválida",None)
            return False
        for port in ports:
            if port < 1 or port > 65535:
                continue
            try:
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f"http://127.0.0.1:{port}/json",timeout=0.7) as r:
                    targets=json.load(r)
                if not isinstance(targets,list):
                    continue
                target=next((x for x in targets if x.get("title")=="SharedJSContext"),
                            next((x for x in targets if
                                  "steamloopback.host" in x.get("url","")),None))
                if not target:
                    continue
                wsurl=target.get("webSocketDebuggerUrl","")
                parts=urlsplit(wsurl)
                if parts.scheme!="ws" or not parts.path:
                    continue
                # Nunca utilizar o endereço anunciado: forçar 127.0.0.1.
                local_url=f"ws://127.0.0.1:{port}{parts.path}"
                if parts.query:
                    local_url+="?"+parts.query
                self._connection=websocket.create_connection(
                    local_url,timeout=1.0,origin=f"http://127.0.0.1:{port}")
                self._socket_port=port
                self.diagnostic=CEFDiagnostic("Steam CEF conectado localmente",port)
                return True
            except Exception:
                self.close()
        self.diagnostic=CEFDiagnostic(
            "Steam CEF não disponível: depuração não habilitada ou porta indisponível",
            None)
        self._retry_after=time.monotonic()+10.0
        return False

    def _query(self):
        if not self._connect():
            return None
        self._message_id+=1
        msgid=self._message_id
        payload={
            "id":msgid,
            "method":"Runtime.evaluate",
            "params":{"expression":_JS,"awaitPromise":True,"returnByValue":True}
        }
        try:
            self._connection.send(json.dumps(payload))
            deadline=time.monotonic()+1.5
            while time.monotonic()<deadline:
                self._connection.settimeout(max(.1,deadline-time.monotonic()))
                msg=json.loads(self._connection.recv())
                if msg.get("id")!=msgid:
                    continue
                result=msg.get("result",{})
                if result.get("exceptionDetails"):
                    raise RuntimeError("Erro de avaliação Steam CEF")
                value=result.get("result",{}).get("value")
                if isinstance(value,dict):
                    return value
                break
            return None
        except Exception:
            self.close()
            self._retry_after=time.monotonic()+4.0
            self.diagnostic=CEFDiagnostic("Falha na leitura CEF; tentando reconectar",None)
            return None

    def scan(self) -> Download | None:
        """Seleciona qualquer AppID ativo no Steam, não há títulos fixos."""
        data=self._query()
        if not isinstance(data,dict) or "overview" not in data:
            return None
        overview=data["overview"]
        o=overview if isinstance(overview,dict) else {}
        items=[item for item in data.get("items",[])
               if isinstance(item,dict)]
        # Antes do primeiro callback, os objetos são vazios. Isso NÃO
        # significa que nenhum jogo está sendo instalado/baixado.
        if not data.get("gotOverview", bool(o)) and not data.get(
                "gotItems", bool(items)):
            self.diagnostic=CEFDiagnostic(
                "CEF conectado, aguardando primeira telemetria SteamClient",
                self._socket_port)
            return None
        if data.get("error"):
            self.diagnostic=CEFDiagnostic(
                "CEF: erro na assinatura de eventos SteamClient",
                self._socket_port)
            return None
        active_item=next((
            item for item in items
            if item.get("active") and not item.get("paused")
            and not item.get("completed")
        ),None)
        try:
            appid=str(int(o.get("update_appid") or 0))
            paused=bool(o.get("paused"))
            state=str(o.get("update_state") or "").lower()
        except (TypeError,ValueError,OverflowError):
            return None
        if appid=="0" and active_item:
            try: appid=str(int(active_item["appid"]))
            except (ValueError,TypeError,OverflowError): return None

        # Estado "downloading" foi observado no Bazzite real e deve ser
        # considerado ativo, mesmo quando a lista de itens está vazia.
        ongoing=_state_is_active(state)
        if (appid=="0" or paused or
                (not ongoing and not active_item)):
            self.diagnostic=CEFDiagnostic(
                f"CEF conectado, sem tarefa ativa (state={state}, "
                f"appid={appid}, items_ativos={int(active_item is not None)})",
                self._socket_port)
            return None
        item=next((x for x in items
                   if str(x.get("appid"))==appid),None)
        pct=steam_ui_progress(o) if ongoing else None
        if pct is None and item is not None:
            try:
                total=max(0,int(item.get("total_bytes") or 0))
                completed=max(0,int(item.get("downloaded_bytes") or 0))
                if total:
                    pct=max(0,min(99,round(completed*100/total)))
            except (TypeError,ValueError,OverflowError):
                pass
        if pct is None:
            self.diagnostic=CEFDiagnostic(
                "CEF conectado, progresso indisponível",self._socket_port)
            return None
        rate=o.get("update_network_bytes_per_second")
        try:
            age=data.get("overviewAgeMs")
            fresh=(age is None or 0 <= float(age) <= 3500)
            # CEF ao vivo deve ter callbacks recentes; nunca apresentar
            # uma taxa antiga como velocidade instantânea.
            speed=(max(0,float(rate))/1_000_000
                   if rate is not None and fresh else None)
        except (TypeError,ValueError,OverflowError):
            speed=None
        try:
            network_total=int(o.get("update_bytes_to_download") or 0)
            network_done=int(o.get("update_bytes_downloaded") or 0)
        except (TypeError,ValueError,OverflowError):
            network_total,network_done=0,0
        installing=bool(
            _state_is_install(state) or
            (network_total and network_done >= network_total) or
            (network_total == 0 and (o.get("update_bytes_to_stage") or
                                     o.get("update_bytes_to_process"))))
        # A velocidade de REDE durante a instalação é zero, mesmo quando
        # a transferência em disco está progredindo.
        if installing:
            speed=0.0
        name=str(item.get("name") or "")[:120] if item else ""
        if not name:
            name=_steam_app_name(appid,self._name_cache)
        try:
            completed=int(o.get("update_bytes_downloaded") or
                          (item or {}).get("downloaded_bytes") or 0)
            total=int(o.get("update_bytes_to_download") or
                      (item or {}).get("total_bytes") or 0)
        except (TypeError,ValueError,OverflowError):
            completed,total=0,0
        self.diagnostic=CEFDiagnostic(
            f"CEF ao vivo: {name} (AppID {appid}) {pct}%",self._socket_port)
        return Download(
            appid=appid,name=name,percent=pct,
            speed_mb_s=round(speed,1) if speed is not None else None,
            completed=completed,total=total,
            source="Steam CEF (tarefa completa; progresso geral estimado)",
            phase="install" if installing else "download")
