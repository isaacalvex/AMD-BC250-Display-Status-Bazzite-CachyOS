"""Regressão: CEF conectado mas sem atividade NÃO oculta downloads reais."""
import unittest
from dataclasses import dataclass

from steam_selection import scan_task


@dataclass
class FakeDownload:
    appid: str
    name: str
    source: str


class FakeCEF:
    def __init__(self, result=None, status="CEF conectado, sem tarefa ativa",
                 failure=None):
        self.result = result
        self.status = status
        self.failure = failure
        self.calls = 0

    def scan(self):
        self.calls += 1
        if self.failure:
            raise self.failure
        return self.result


class FakeTracker:
    def __init__(self, result=None):
        self.result = result
        self.calls = 0

    def scan(self):
        self.calls += 1
        return self.result


class SteamSelectionTests(unittest.TestCase):
    def test_cef_connected_idle_but_active_street_fighter_is_displayed(self):
        active = FakeDownload("1364780", "Street Fighter 6",
                              "/Steam/appmanifest_1364780.acf (estimativa via ACF/log)")
        cef = FakeCEF()
        files = FakeTracker(active)
        self.assertIs(scan_task(cef, files), active)
        self.assertEqual((cef.calls, files.calls), (1, 1))

    def test_cef_pending_callback_still_falls_back(self):
        game = FakeDownload("1364780", "Street Fighter 6", "ACF/log")
        self.assertIs(scan_task(FakeCEF(status="CEF conectado, aguardando primeira telemetria"),
                                FakeTracker(game)), game)

    def test_cef_live_preferred_to_file_estimate(self):
        live = FakeDownload("1364780", "Street Fighter 6", "Steam CEF")
        files = FakeTracker(FakeDownload("1364780", "Street Fighter 6", "ACF/log"))
        self.assertIs(scan_task(FakeCEF(live), files), live)
        self.assertEqual(files.calls, 0)

    def test_cef_exception_does_not_blank_the_screen(self):
        warnings = []
        game = FakeDownload("999999", "Um jogo qualquer", "ACF/log")
        self.assertIs(scan_task(FakeCEF(failure=RuntimeError("Steam mudou API")),
                                FakeTracker(game), warnings.append), game)
        self.assertTrue(any("Steam mudou API" in item for item in warnings))

    def test_returns_idle_only_when_both_sources_report_none(self):
        self.assertIsNone(scan_task(FakeCEF(), FakeTracker()))


if __name__ == "__main__":
    unittest.main()
