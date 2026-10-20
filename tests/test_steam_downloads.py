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
        self.assertGreater(item.speed_mb_s, 0)

    def test_log_rate_mbps_to_mb_s(self):
        manifest(self.root, "50", "Jogo", 100, 1000, 1048576)
        logdir = self.root / "logs"
        logdir.mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        (logdir / "content_log.txt").write_text(
            f"[{stamp}] Current download rate: 80.000 Mbps\n", encoding="utf-8")
        item = SteamDownloadTracker().scan()
        self.assertAlmostEqual(item.speed_mb_s, 10.0)

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
