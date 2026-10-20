"""Testes da fonte ao vivo da Steam CEF sem abrir rede nem Steam."""
import unittest

from steam_cef import SteamCEFReader, steam_ui_progress


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
