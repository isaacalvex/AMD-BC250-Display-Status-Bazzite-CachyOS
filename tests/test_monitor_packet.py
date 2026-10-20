"""Verifica compatibilidade do protocolo USB sem carregar PySide ou pyserial."""
import ast
import re
import unittest
from pathlib import Path
from types import SimpleNamespace


def _load_packet_functions():
    file = Path(__file__).resolve().parents[1] / "stellar_monitor.py"
    parsed = ast.parse(file.read_text(encoding="utf-8"))
    parts = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef)
        and node.name in ("_nome_serial", "pacote_download")
    ]
    assert len(parts) == 2, "Packet functions missing"
    compiled = compile(ast.Module(body=parts, type_ignores=[]),
                       filename=str(file), mode="exec")
    env = {"re": re}
    exec(compiled, env)
    return env["pacote_download"]


class USBPacketTests(unittest.TestCase):
    def test_hundredth_percent_prepended_before_legacy_integer(self):
        packet = _load_packet_functions()
        job = SimpleNamespace(
            name="Street Fighter 6", percent=8, percent_precise=8.37,
            speed_mb_s=28.4
        )
        sent = packet(job)
        self.assertEqual(
            sent,
            b"DL:1;UNIT:Mbps;PCTF:8.37;PCT:8;SPEED:28.4;NAME:Street Fighter 6\n"
        )
        # Parser legado procura apenas os campos após ';PCT:'.
        legacy = sent.decode("utf-8")
        self.assertEqual(
            legacy.split(";PCT:", 1)[1].split(";SPEED:", 1)[0], "8"
        )

    def test_new_firmware_unit_marker_is_before_legacy_fields(self):
        packet = _load_packet_functions()
        job = SimpleNamespace(name="Jogo", percent=37,
                              percent_precise=37.81, speed_mb_s=35.3)
        text = packet(job).decode("utf-8")
        self.assertTrue(text.startswith("DL:1;UNIT:Mbps;PCTF:37.81;PCT:37;"))
        # Firmware legado ainda recebe exatamente 35.3 MB/s.
        self.assertEqual(
            text.split(";SPEED:", 1)[1].split(";NAME:", 1)[0],
            "35.3"
        )
        # Firmware atualizado exibirá 282.4 Mbps (8 bits por byte).
        self.assertAlmostEqual(35.3 * 8, 282.4)

    def test_legacy_fallback_and_unknown_speed(self):
        packet = _load_packet_functions()
        job = SimpleNamespace(
            name="Game X", percent=65, percent_precise=None,
            speed_mb_s=None
        )
        self.assertEqual(
            packet(job),
            b"DL:1;UNIT:Mbps;PCTF:65.00;PCT:65;SPEED:-1;NAME:Game X\n"
        )

    def test_nome_serial_never_injects_separators(self):
        packet = _load_packet_functions()
        job = SimpleNamespace(
            name="Game;DL:0\nInjected", percent=12,
            percent_precise=12.45, speed_mb_s=2.1
        )
        sent = packet(job).decode("utf-8")
        self.assertIn(";UNIT:Mbps;PCTF:12.45;PCT:12;SPEED:2.1;NAME:", sent)
        self.assertEqual(sent.count("\n"), 1)
        self.assertNotIn("NAME:Game;", sent)


if __name__ == "__main__":
    unittest.main()
