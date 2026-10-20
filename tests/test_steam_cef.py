"""Testes da fonte ao vivo da Steam CEF sem abrir rede nem Steam."""
import unittest

from steam_cef import (
    SteamCEFReader, steam_ui_progress, steam_ui_progress_precise,
    _native_progress_precise, _state_is_active, _state_is_install
)


class SteamCEFTests(unittest.TestCase):
    def test_progress_uses_download_and_staging(self):
        o={"update_bytes_downloaded":60,"update_bytes_to_download":100,
           "update_bytes_staged":20,"update_bytes_to_stage":100}
        self.assertEqual(steam_ui_progress(o),40)

    def test_download_only_falls_back_without_staging(self):
        o={"update_bytes_downloaded":80,"update_bytes_to_download":100}
        self.assertEqual(steam_ui_progress(o),80)

    def test_unknown_progress_not_faked(self):
        self.assertIsNone(steam_ui_progress({}))

    def test_live_reading_changes_and_speed_is_measured(self):
        reader=SteamCEFReader()
        sample={"overview":{
            "update_appid":123,"update_state":"Updating","paused":False,
            "update_bytes_downloaded":50,"update_bytes_to_download":100,
            "update_bytes_staged":20,"update_bytes_to_stage":100,
            "update_network_bytes_per_second":28400000
        },"items":[{"appid":123,"name":"Um jogo muito legal","active":True}]}
        reader._query=lambda:sample
        x=reader.scan()
        self.assertEqual(x.percent,35)
        self.assertAlmostEqual(x.speed_mb_s,28.4)
        self.assertEqual(x.name,"Um jogo muito legal")
        sample["overview"]["update_bytes_downloaded"]=90
        sample["overview"]["update_bytes_staged"]=60
        y=reader.scan()
        self.assertEqual(y.percent,75)
        self.assertNotEqual(x.percent,y.percent)

    def test_any_appid_from_active_item_without_overview(self):
        # Novo jogo sem manifesto inicial: nenhum AppID fica codificado.
        reader=SteamCEFReader()
        reader._query=lambda:{
            "overview":{},
            "items":[{"appid":9991991,"active":True,"paused":False,
                      "downloaded_bytes":33,"total_bytes":100,
                      "name":"Jogo desconhecido da Steam"}]
        }
        result=reader.scan()
        self.assertIsNotNone(result)
        self.assertEqual(result.appid,"9991991")
        self.assertEqual(result.name,"Jogo desconhecido da Steam")
        self.assertEqual(result.percent,33)

    def test_switch_to_whichever_game_is_active(self):
        reader=SteamCEFReader()
        sample={"overview":{
            "update_appid":11111,"update_state":"Updating","paused":False,
            "update_bytes_downloaded":20,"update_bytes_to_download":100,
            "update_network_bytes_per_second":3000000},
            "items":[{"appid":11111,"active":True,"name":"Jogo primeiro"},
                     {"appid":22222,"active":False,"name":"Jogo seguinte"}]}
        reader._query=lambda:sample
        first=reader.scan()
        self.assertEqual((first.appid,first.percent),("11111",20))
        sample["overview"]["update_appid"]=22222
        sample["overview"]["update_bytes_downloaded"]=75
        sample["items"][0]["active"]=False
        sample["items"][1]["active"]=True
        second=reader.scan()
        self.assertEqual((second.appid,second.name,second.percent),
                         ("22222","Jogo seguinte",75))

    def test_item_updates_when_overview_not_ready(self):
        reader=SteamCEFReader()
        sample={"overview":{}, "items":[{
            "appid":7654321,"active":True,"paused":False,
            "downloaded_bytes":20,"total_bytes":100,"name":"Novo jogo"}]}
        reader._query=lambda:sample
        first=reader.scan()
        self.assertEqual(first.percent,20)
        sample["items"][0]["downloaded_bytes"]=78
        second=reader.scan()
        self.assertEqual(second.percent,78)

    def test_proton_disk_install_90pct_after_download_100pct(self):
        """Exemplo da tela Steam: os 403MB terminaram, mas disco 90%."""
        reader=SteamCEFReader()
        overview={
            "update_appid":4628710,"update_state":"Updating","paused":False,
            "update_bytes_downloaded":403000000,
            "update_bytes_to_download":403000000,
            "update_bytes_staged":720000000,
            "update_bytes_to_stage":800000000,
            "update_network_bytes_per_second":0
        }
        sample={"overview":overview,
                "items":[{"appid":4628710,"active":True,
                          "completed":False,"paused":False,
                          "name":"Proton 11.0"},
                         {"appid":1794680,"active":False,
                          "name":"Vampire Survivors"}]}
        reader._query=lambda:sample
        result=reader.scan()
        self.assertIsNotNone(result)
        self.assertEqual(result.appid,"4628710")
        self.assertEqual(result.phase,"install")
        self.assertEqual(result.percent,93)
        self.assertEqual(result.speed_mb_s,0)

        overview["update_bytes_staged"]=792000000
        result=reader.scan()
        self.assertEqual(result.percent,99)
        self.assertEqual(result.phase,"install")

        # Agora Steam confirma o fim e avança ou volta à tela térmica.
        overview["update_state"]="None"
        overview["update_appid"]=0
        sample["items"][0]["active"]=False
        sample["items"][0]["completed"]=True
        self.assertIsNone(reader.scan())

    def test_processing_is_used_without_staging_counters(self):
        o={"update_bytes_to_download":100,
           "update_bytes_downloaded":100,
           "update_bytes_to_process":100,
           "update_bytes_processed":90}
        self.assertEqual(steam_ui_progress(o),95)

    def test_initial_callbacks_pending_is_not_idle(self):
        reader=SteamCEFReader()
        reader._query=lambda:{
            "overview":{},"items":[],
            "gotOverview":False,"gotItems":False
        }
        self.assertIsNone(reader.scan())
        self.assertIn("aguardando primeira telemetria",reader.diagnostic.status)

    def test_live_state_without_items_still_detects_any_app(self):
        reader=SteamCEFReader()
        reader._query=lambda:{
            "overview":{
                "update_appid":1364780,
                "update_state":"Updating",
                "update_bytes_downloaded":22,
                "update_bytes_to_download":100,
                "update_bytes_staged":10,
                "update_bytes_to_stage":100,
                "update_network_bytes_per_second":2300000
            },
            "items":[],"gotOverview":True,"gotItems":False,
            "overviewAgeMs":500
        }
        item=reader.scan()
        self.assertIsNotNone(item)
        self.assertEqual(item.appid,"1364780")
        self.assertEqual(item.percent,16)
        self.assertEqual(item.speed_mb_s,2.3)

    def test_stale_callback_cannot_report_old_speed(self):
        reader=SteamCEFReader()
        reader._query=lambda:{
            "overview":{
                "update_appid":100,
                "update_state":"Updating",
                "update_bytes_downloaded":50,
                "update_bytes_to_download":100,
                "update_network_bytes_per_second":3000000
            },"items":[],"gotOverview":True,
            "overviewAgeMs":9000
        }
        info=reader.scan()
        self.assertIsNotNone(info)
        self.assertIsNone(info.speed_mb_s)

    def test_real_bazzite_street_fighter_state_downloading(self):
        """Caso observado 13:23:07: CEF indicou downloading, appid 1364780."""
        reader=SteamCEFReader()
        sample={
            "overview":{
                "update_appid":1364780,
                "update_state":"downloading",
                "paused":False,
                "update_bytes_downloaded":8_000_000_000,
                "update_bytes_to_download":100_000_000_000,
                "update_bytes_staged":4_000_000_000,
                "update_bytes_to_stage":100_000_000_000,
                "update_network_bytes_per_second":24_500_000
            },
            "items":[],
            "gotOverview":True,
            "gotItems":False,
            "overviewAgeMs":180
        }
        reader._query=lambda:sample
        item=reader.scan()
        self.assertIsNotNone(item)
        self.assertEqual(item.appid,"1364780")
        self.assertEqual(item.percent,6)
        self.assertEqual(item.phase,"download")
        self.assertEqual(item.speed_mb_s,24.5)
        self.assertTrue(item.source.startswith("Steam CEF"))
        sample["overview"]["update_bytes_downloaded"]=24_000_000_000
        sample["overview"]["update_bytes_staged"]=18_000_000_000
        sample["overview"]["update_network_bytes_per_second"]=30_100_000
        updated=reader.scan()
        self.assertEqual(updated.percent,21)
        self.assertEqual(updated.speed_mb_s,30.1)

    def test_cef_install_state_with_zero_network_speed(self):
        reader=SteamCEFReader()
        reader._query=lambda:{
            "overview":{
                "update_appid":1364780,
                "update_state":"staging",
                "paused":False,
                "update_bytes_downloaded":100,
                "update_bytes_to_download":100,
                "update_bytes_staged":86,
                "update_bytes_to_stage":100,
                "update_network_bytes_per_second":0
            },
            "items":[],"gotOverview":True,"overviewAgeMs":100
        }
        item=reader.scan()
        self.assertIsNotNone(item)
        self.assertEqual(item.appid,"1364780")
        self.assertEqual(item.phase,"install")
        self.assertEqual(item.percent,93)
        self.assertEqual(item.speed_mb_s,0.0)

    def test_various_steam_work_states_and_queued_states(self):
        for state in ("downloading","staging","installing","committing",
                      "verifying_installed","processing","updating",
                      "starting","stopping","preallocating"):
            with self.subTest(state=state):
                self.assertTrue(_state_is_active(state))
        for state in ("none","paused","queued","completed","",
                      "update_queued"):
            with self.subTest(state=state):
                self.assertFalse(_state_is_active(state))
        self.assertTrue(_state_is_install("Verifying Installed"))
        self.assertFalse(_state_is_install("downloading"))

    def test_large_download_centiprogress_instead_of_stuck_integer(self):
        """Percentual 8,01% -> 8,04% precisa ser preservado para o anel."""
        reader=SteamCEFReader()
        overview={
            "update_appid":1364780,"update_state":"downloading",
            "paused":False,
            "update_bytes_to_download":100_000_000_000,
            "update_bytes_downloaded":8_010_000_000,
            "update_network_bytes_per_second":22_000_000
        }
        reader._query=lambda:{"overview":overview,"gotOverview":True,
                              "items":[],"overviewAgeMs":100}
        a=reader.scan()
        self.assertEqual(a.percent,8)
        self.assertEqual(a.percent_precise,8.01)
        overview["update_bytes_downloaded"]=8_040_000_000
        b=reader.scan()
        self.assertEqual(b.percent,8)
        self.assertEqual(b.percent_precise,8.04)
        self.assertEqual(steam_ui_progress_precise(overview),8.04)

    def test_calculate_rate_from_fresh_cef_delta_if_native_rate_is_zero(self):
        import time
        reader=SteamCEFReader()
        overview={
            "update_appid":1364780,"update_state":"downloading",
            "paused":False,
            "update_bytes_to_download":100_000_000_000,
            "update_bytes_downloaded":8_000_000_000,
            "update_network_bytes_per_second":0
        }
        reader._query=lambda:{"overview":overview,"gotOverview":True,
                              "items":[],"overviewAgeMs":100}
        reader.scan()
        reader._last_counter=("1364780",8_000_000_000,time.monotonic()-1)
        overview["update_bytes_downloaded"]=8_025_000_000
        result=reader.scan()
        self.assertIsNotNone(result)
        self.assertGreater(result.speed_mb_s,20)
        self.assertLess(result.speed_mb_s,30)

    def test_real_bazzite_sparse_cef_keeps_live_speed(self):
        """Quatro snapshots reais: Steam envia AppID/rate, mas omite totais."""
        reader=SteamCEFReader()
        overview={
            "update_appid":1364780,
            "update_state":"Downloading",
            "paused":False,
            "update_network_bytes_per_second":36_828_172,
            "update_disc_bytes_per_second":35_572_703,
            "update_is_install":True,
        }
        reader._query=lambda:{
            "overview":overview,
            "gotOverview":True,
            "gotItems":False,
            "items":[{"appid":1364780,"active":False}],
            "overviewAgeMs":391,
        }
        # Sem denominador confiável: CEF isoladamente não pode inventar %.
        self.assertIsNone(reader.scan())
        self.assertIsNotNone(reader.live_metrics)
        self.assertEqual(reader.live_metrics[0],"1364780")
        self.assertAlmostEqual(reader.live_metrics[1],36.83)
        self.assertIn("sem contadores",reader.diagnostic.status)
        overview["update_network_bytes_per_second"]=35_804_765
        self.assertIsNone(reader.scan())
        self.assertAlmostEqual(reader.live_metrics[1],35.8)

    def test_cef_expired_callback_does_not_supply_speed(self):
        reader=SteamCEFReader()
        reader._query=lambda:{
            "overview":{
                "update_appid":1364780,"update_state":"Downloading",
                "update_network_bytes_per_second":36_800_000
            },"gotOverview":True,"items":[],"overviewAgeMs":10000
        }
        self.assertIsNone(reader.scan())
        self.assertIsNone(reader.live_metrics)

    def test_active_overview_uses_matching_steam_item_even_without_active_flag(self):
        """O único item do CEF pode não ter active=True em certos builds."""
        reader=SteamCEFReader()
        item={"appid":1364780,"active":False,"paused":False,
              "downloaded_bytes":36000000000,"total_bytes":100000000000,
              "name":"Street Fighter 6"}
        reader._query=lambda:{
            "overview":{
                "update_appid":1364780,
                "update_state":"Downloading",
                "update_network_bytes_per_second":36828172
            },
            "gotOverview":True,"gotItems":True,"overviewAgeMs":391,
            "items":[item]
        }
        result=reader.scan()
        self.assertIsNotNone(result)
        self.assertEqual(result.appid,"1364780")
        self.assertEqual(result.percent,36)
        self.assertEqual(result.percent_precise,36.0)
        self.assertAlmostEqual(result.speed_mb_s,36.8)
        item["downloaded_bytes"]=36550000000
        updated=reader.scan()
        self.assertEqual(updated.percent_precise,36.55)

    def test_cef_progress_fraction_overrides_missing_bytes(self):
        reader=SteamCEFReader()
        overview={
            "update_appid":1904480,
            "update_state":"Preallocating",
            "progress":0.3472,
            "paused":False,
            "update_network_bytes_per_second":357873,
        }
        reader._query=lambda:{
            "overview":overview, "gotOverview":True, "items":[],
            "overviewAgeMs":100
        }
        result=reader.scan()
        self.assertIsNotNone(result)
        self.assertEqual(result.percent_precise,34.72)
        self.assertEqual(result.phase,"install")
        self.assertAlmostEqual(result.speed_mb_s,0.4)
        self.assertIn("progresso nativo",result.source)
        overview["progress"]=0.3581
        result=reader.scan()
        self.assertEqual(result.percent_precise,35.81)

    def test_cef_progress_overall_percent_nested_preferred(self):
        reader=SteamCEFReader()
        overview={
            "update_appid":1364780,
            "update_state":"Downloading",
            "progress":{"overall_percent_complete":46.83},
            "paused":False,
            "update_network_bytes_per_second":35804765,
        }
        reader._query=lambda:{
            "overview":overview,"gotOverview":True,"items":[],
            "overviewAgeMs":50
        }
        result=reader.scan()
        self.assertEqual(result.percent_precise,46.83)
        self.assertAlmostEqual(result.speed_mb_s,35.8)
        overview["progress"]["overall_percent_complete"]=47.21
        self.assertEqual(reader.scan().percent_precise,47.21)

    def test_progress_invalid_data_does_not_make_up_percentage(self):
        for value in (-1,120,float("nan"),float("inf"),{},None,True):
            with self.subTest(value=value):
                self.assertIsNone(_native_progress_precise({"progress":value}))
        self.assertEqual(_native_progress_precise({"progress":0.0}),0.0)
        self.assertEqual(_native_progress_precise(
            {"overall_percent_complete":77.6}),77.6)

    def test_idle_or_paused_is_not_reported_as_download(self):
        reader=SteamCEFReader()
        sample={"overview":{"update_appid":123,"update_state":"Updating",
                            "paused":True,"update_bytes_downloaded":50,
                            "update_bytes_to_download":100}}
        reader._query=lambda:sample
        self.assertIsNone(reader.scan())
        sample["overview"]["paused"]=False
        sample["overview"]["update_state"]="None"
        self.assertIsNone(reader.scan())


if __name__=="__main__":
    unittest.main()
