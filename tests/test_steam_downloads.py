"""Testes do parser local Steam, sem Steam instalada nem hardware."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from steam_downloads import SteamDownloadTracker, steam_roots


def manifest(root, appid, name, done, total, flags):
    steamapps = root / "steamapps"
    steamapps.mkdir(parents=True, exist_ok=True)
    data = f'''"AppState"
{{
  "appid" "{appid}"
  "name" "{name}"
  "StateFlags" "{flags}"
  "BytesToDownload" "{total}"
  "BytesDownloaded" "{done}"
}}
'''
    (steamapps / f"appmanifest_{appid}.acf").write_text(data, encoding="utf-8")


class SteamDownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "Steam"
        (self.root / "steamapps").mkdir(parents=True)
        self.patchenv = patch.dict(os.environ, {"STELLAR_STEAM_ROOT": str(self.root)})
        self.patchenv.start()
        self.addCleanup(self.patchenv.stop)

    def test_no_active_download(self):
        manifest(self.root, "10", "Finalizado", 100, 100, 4)
        self.assertIsNone(SteamDownloadTracker().scan())

    def test_active_game_name_percent(self):
        manifest(self.root, "20", "Cyberpunk 2077", 65, 100, 1048576)
        item = SteamDownloadTracker().scan()
        self.assertEqual((item.name, item.percent), ("Cyberpunk 2077", 65))
        self.assertIsNone(item.speed_mb_s)

    def test_paused_not_active(self):
        manifest(self.root, "30", "Pausado", 40, 100, 1024 | 512)
        self.assertIsNone(SteamDownloadTracker().scan())

    def test_speed_by_byte_delta(self):
        manifest(self.root, "40", "Counter-Strike 2", 1_000_000, 10_000_000, 1048576)
        tr = SteamDownloadTracker()
        self.assertIsNone(tr.scan().speed_mb_s)
        manifest(self.root, "40", "Counter-Strike 2", 3_000_000, 10_000_000, 1048576)
        item = tr.scan()
        self.assertEqual(item.percent, 30)
        # O ACF pode salvar vários minutos acumulados num checkpoint:
        # isso não é velocidade instantânea de rede.
        self.assertIsNone(item.speed_mb_s)

    def test_log_rate_mbps_to_mb_s(self):
        manifest(self.root, "50", "Jogo", 100, 1000, 1048576)
        logdir = self.root / "logs"
        logdir.mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        (logdir / "content_log.txt").write_text(
            f"[{stamp}] Current download rate: 80.000 Mbps\n", encoding="utf-8")
        item = SteamDownloadTracker().scan()
        self.assertAlmostEqual(item.speed_mb_s, 10.0)

    def test_expired_steam_log_rate_not_repeated(self):
        manifest(self.root, "501", "Download com taxa antiga",
                 20000000, 100000000, 1048576)
        logdir=self.root / "logs"
        logdir.mkdir()
        stamp=time.strftime("%Y-%m-%d %H:%M:%S",
                            time.localtime(time.time()-20))
        (logdir / "content_log.txt").write_text(
            f"[{stamp}] Current download rate: 25.6 Mbps\n",
            encoding="utf-8")
        result=SteamDownloadTracker().scan()
        self.assertIsNotNone(result)
        self.assertIsNone(result.speed_mb_s)

    def test_real_steam_log_app_update_changed(self):
        # Formato exato usado por versões recentes da Steam no Linux.
        manifest(self.root, "71", "Jogo Steam Bazzite", 650000, 1000000, 2)
        logdir = self.root / "logs"
        logdir.mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        (logdir / "content_log.txt").write_text(
            f"[{stamp}] AppID 71 update started : download 0/1000000, store 0/0, reuse 0/0, delta 0/0, stage 0/1300000\n"
            f"[{stamp}] AppID 71 App update changed : Running Update,Downloading,Staging,\n",
            encoding="utf-8")
        item = SteamDownloadTracker().scan()
        self.assertIsNotNone(item)
        self.assertEqual(item.name, "Jogo Steam Bazzite")
        # Download (65%) ainda requer 1,3M de preparação em disco.
        self.assertEqual(item.percent, 28)

    def test_real_log_staging_keeps_job_active(self):
        manifest(self.root, "72", "Jogo processando", 650000, 1000000, 2)
        logdir = self.root / "logs"
        logdir.mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        (logdir / "content_log.txt").write_text(
            f"[{stamp}] AppID 72 App update changed : Running Update,Downloading,Staging,\n"
            f"[{stamp}] AppID 72 App update changed : Running Update,Staging,\n",
            encoding="utf-8")
        result=SteamDownloadTracker().scan()
        self.assertIsNotNone(result)
        self.assertEqual(result.phase,"install")
        self.assertEqual(result.speed_mb_s,0.0)

    def test_recent_log_detects_download_despite_stale_manifest_flags(self):
        manifest(self.root, "70", "Jogo com manifesto atrasado", 65, 100, 2)
        logdir = self.root / "logs"
        logdir.mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        (logdir / "content_log.txt").write_text(
            f"[{stamp}] AppID 70 update changed : Running,Downloading,Staging,\n",
            encoding="utf-8")
        item = SteamDownloadTracker().scan()
        self.assertIsNotNone(item)
        self.assertEqual((item.name, item.percent),
                         ("Jogo com manifesto atrasado", 65))

    def test_log_supplies_total_when_manifest_has_zero(self):
        manifest(self.root, "80", "Jogo iniciando", 0, 0, 2)
        logdir = self.root / "logs"
        logdir.mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        (logdir / "content_log.txt").write_text(
            f"[{stamp}] AppID 80 update started : download 150/1000, "
            "store 0/0, reuse 0/0\n"
            f"[{stamp}] AppID 80 update changed : Running,Downloading,\n",
            encoding="utf-8")
        item = SteamDownloadTracker().scan()
        self.assertIsNotNone(item)
        self.assertEqual(item.percent, 15)

    def test_stale_log_does_not_trigger(self):
        manifest(self.root, "90", "Jogo encerrado", 65, 100, 2)
        logdir = self.root / "logs"
        logdir.mkdir()
        old = time.strftime("%Y-%m-%d %H:%M:%S",
                            time.localtime(time.time() - 7 * 3600))
        (logdir / "content_log.txt").write_text(
            f"[{old}] AppID 90 update changed : Running,Downloading,\n",
            encoding="utf-8")
        self.assertIsNone(SteamDownloadTracker().scan())

    def test_long_download_without_new_events(self):
        manifest(self.root, "91", "Download grande", 25, 100, 2)
        (self.root / "logs").mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S",
                              time.localtime(time.time() - 35 * 60))
        (self.root / "logs/content_log.txt").write_text(
            f"[{stamp}] AppID 91 update changed : Running Update,Downloading,Staging,\n",
            encoding="utf-8")
        item = SteamDownloadTracker().scan()
        self.assertIsNotNone(item)
        self.assertEqual(item.name, "Download grande")

    def test_staging_keeps_app_active_without_network(self):
        manifest(self.root, "92", "Terminou transferencia", 25, 100, 2)
        (self.root / "logs").mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        (self.root / "logs/content_log.txt").write_text(
            f"[{stamp}] AppID 92 update changed : Running Update,Downloading,\n"
            f"[{stamp}] AppID 92 update changed : Running Update,Staging,\n",
            encoding="utf-8")
        result=SteamDownloadTracker().scan()
        self.assertIsNotNone(result)
        self.assertEqual(result.phase,"install")

    def test_bazzite_shader_real_log_active(self):
        # Evidência real do Bazzite: AppID 1794680 / Vampire Survivors.
        manifest(self.root, "1794680", "Vampire Survivors",
                 2934016, 502455904, 1042)
        logdir = self.root / "logs"
        logdir.mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        (logdir / "content_log.txt").write_text(
            f"[{stamp}] AppID 1794680 update started : download "
            "2934016/502455904, store 0/0, reuse 0/0, "
            "delta 0/0, stage 3045105/1130055333\n"
            f"[{stamp}] AppID 1794680 Shader update changed : "
            "Running Update,Downloading,Staging,\n",
            encoding="utf-8")
        data = SteamDownloadTracker().scan()
        self.assertIsNotNone(data)
        self.assertEqual(data.name, "Vampire Survivors")
        self.assertEqual(data.appid, "1794680")
        # A tarefa geral inclui staging informado no log.
        self.assertEqual(data.percent, 0)

    def test_bazzite_shader_preferred_over_inactive_manifest(self):
        manifest(self.root, "1209490", "Exit the Gungeon",
                 512812752, 1011679456, 1026)
        manifest(self.root, "1794680", "Vampire Survivors",
                 2934016, 502455904, 1042)
        logdir = self.root / "logs"
        logdir.mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        (logdir / "content_log.txt").write_text(
            f"[{stamp}] AppID 1794680 update started : "
            "download 2934016/502455904, store 0/0, reuse 0/0, "
            "delta 0/0, stage 3045105/1130055333\n"
            f"[{stamp}] AppID 1794680 Shader update changed : "
            "Running Update,Downloading,Staging,\n",
            encoding="utf-8")
        info = SteamDownloadTracker().scan()
        self.assertIsNotNone(info)
        self.assertEqual(info.appid, "1794680")
        self.assertEqual(info.name, "Vampire Survivors")

    def test_shader_stop_and_resume(self):
        manifest(self.root, "1794680", "Vampire Survivors",
                 2934016, 502455904, 1042)
        logdir = self.root / "logs"
        logdir.mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        path = logdir / "content_log.txt"
        start = (
            f"[{stamp}] AppID 1794680 Shader update changed : "
            "Running Update,Downloading,Staging,\n"
        )
        stopping = (
            f"[{stamp}] AppID 1794680 Shader update changed : "
            "Running Update,Downloading,Staging,Stopping,\n"
            f"[{stamp}] AppID 1794680 Shader update changed : "
            "Running Update,Stopping,\n"
            f"[{stamp}] AppID 1794680 Shader update changed : None\n"
        )
        path.write_text(start + stopping, encoding="utf-8")
        self.assertIsNone(SteamDownloadTracker().scan())
        # Retomar a fila NÃO basta; precisa efetivamente de Downloading.
        path.write_text(start + stopping +
            f"[{stamp}] AppID 1794680 state changed : "
            "Update Required,Update Queued,Update Started,\n",
            encoding="utf-8")
        self.assertIsNone(SteamDownloadTracker().scan())
        path.write_text(start + stopping +
            f"[{stamp}] AppID 1794680 state changed : "
            "Update Required,Update Queued,Update Started,\n"
            + start,
            encoding="utf-8")
        self.assertIsNotNone(SteamDownloadTracker().scan())

    def test_shader_staging_keeps_task_visible(self):
        manifest(self.root, "1794680", "Vampire Survivors",
                 2934016, 502455904, 1042)
        logdir = self.root / "logs"
        logdir.mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        (logdir / "content_log.txt").write_text(
            f"[{stamp}] AppID 1794680 Shader update changed : "
            "Running Update,Downloading,Staging,\n"
            f"[{stamp}] AppID 1794680 Shader update changed : "
            "Running Update,Staging,\n",
            encoding="utf-8")
        result=SteamDownloadTracker().scan()
        self.assertIsNotNone(result)
        self.assertEqual(result.phase,"install")
        self.assertEqual(result.speed_mb_s,0.0)

    def test_proton_installs_after_network_finishes_then_stops(self):
        """Proton 11.0 da captura: 403 MB baixados, instalação 90%."""
        steamapps = self.root / "steamapps"
        data = (
            '"AppState"\n{\n'
            '"appid" "4628710"\n"name" "Proton 11.0"\n'
            '"StateFlags" "1026"\n'
            '"BytesToDownload" "403000000"\n'
            '"BytesDownloaded" "403000000"\n'
            '"BytesToStage" "800000000"\n'
            '"BytesStaged" "720000000"\n}\n'
        )
        (steamapps / "appmanifest_4628710.acf").write_text(
            data, encoding="utf-8")
        (self.root / "logs").mkdir()
        path = self.root / "logs/content_log.txt"
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        path.write_text(
            f"[{stamp}] AppID 4628710 App update changed : Running Update,Staging,\n",
            encoding="utf-8")
        result = SteamDownloadTracker().scan()
        self.assertIsNotNone(result)
        self.assertEqual(result.name,"Proton 11.0")
        self.assertEqual(result.phase,"install")
        self.assertEqual(result.speed_mb_s,0.0)
        self.assertEqual(result.percent,93)  # total do trabalho: rede + disco

        # A tarefa continua em Verifying/Committing depois da rede.
        path.write_text(
            f"[{stamp}] AppID 4628710 App update changed : Running Update,Verifying Staged,\n"
            f"[{stamp}] AppID 4628710 App update changed : Running Update,Committing,\n",
            encoding="utf-8")
        result = SteamDownloadTracker().scan()
        self.assertIsNotNone(result)
        self.assertEqual(result.phase,"install")

        # Apenas conclusão real remove a tela.
        with path.open("a",encoding="utf-8") as out:
            out.write(
                f"[{stamp}] AppID 4628710 finished update, 1 mounted depots\n"
                f"[{stamp}] AppID 4628710 App update changed : None\n")
        self.assertIsNone(SteamDownloadTracker().scan())

    def test_queued_game_not_selected_while_other_app_installs(self):
        manifest(self.root, "1209490", "Exit the Gungeon",
                 512812752, 1011679456, 1026)
        manifest(self.root, "4628710", "Proton 11.0",
                 403000000,403000000,1026)
        path = self.root / "steamapps/appmanifest_4628710.acf"
        path.write_text(path.read_text().replace(
            '"BytesDownloaded" "403000000"',
            '"BytesDownloaded" "403000000"\n"BytesToStage" "100"\n"BytesStaged" "90"'),
            encoding="utf-8")
        (self.root / "logs").mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        (self.root / "logs/content_log.txt").write_text(
            f"[{stamp}] AppID 4628710 App update changed : Running Update,Staging,\n",
            encoding="utf-8")
        result=SteamDownloadTracker().scan()
        self.assertIsNotNone(result)
        self.assertEqual(result.appid,"4628710")

    def test_top_level_manifest_counters_ignore_nested_dlc(self):
        """Downloads de DLC não sobrescrevem os contadores do jogo."""
        path=self.root / "steamapps/appmanifest_999999.acf"
        path.write_text(
            '"AppState"\n{\n'
            '"appid" "999999"\n"name" "Jogo com DLC"\n'
            '"StateFlags" "1048576"\n'
            '"BytesToDownload" "100"\n'
            '"BytesDownloaded" "60"\n'
            '"DlcDownloads"\n{\n'
            '"456" \n{\n'
            '"BytesToDownload" "9000"\n'
            '"BytesDownloaded" "1"\n'
            '}\n}\n}\n', encoding="utf-8")
        item=SteamDownloadTracker().scan()
        self.assertIsNotNone(item)
        self.assertEqual(item.name,"Jogo com DLC")
        self.assertEqual(item.percent,60)

    def test_secondary_library(self):
        extra = Path(self.tmp.name) / "games"
        manifest(extra, "60", "Jogo externo", 25, 100, 1048576)
        (self.root / "steamapps/libraryfolders.vdf").write_text(
            '"libraryfolders"\n{\n "1"\n {\n "path" "' +
            str(extra) + '"\n }\n}\n', encoding="utf-8")
        roots = steam_roots()
        self.assertEqual(len(roots), 2)
        self.assertEqual(SteamDownloadTracker().scan().name, "Jogo externo")


if __name__ == "__main__":
    unittest.main()
