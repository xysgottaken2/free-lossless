"""The overlay log: append-only, small and never able to break the pipeline."""
import importlib.util
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from helpers import ROOT


def load_diagnostics():
    spec = importlib.util.spec_from_file_location("test_subject_diagnostics", ROOT / "diagnostics.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {"FREE_LOSSLESS_LOG": "1"}):
        spec.loader.exec_module(module)
    return module


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.preferences = Path(self.temp.name) / "settings.json"
        self.module = load_diagnostics()
        self.module.get_settings_path = lambda: str(self.preferences)

    def read_log(self):
        return self.module.log_path().read_text(encoding="utf-8")

    def test_the_log_lives_beside_the_preferences(self):
        self.assertEqual(self.module.log_path(), Path(self.temp.name) / "overlay.log")

    def test_reset_starts_a_fresh_session(self):
        self.module.write("first session")
        self.module.reset()
        content = self.read_log()
        self.assertIn("Free Lossless", content)
        self.assertNotIn("first session", content)

    def test_lines_are_timestamped_and_labelled(self):
        self.module.write_now("motor", "Fast (DIS Flow)")
        line = self.read_log().strip().splitlines()[-1]
        self.assertRegex(line, r"^\[\d\d:\d\d:\d\d\] motor: Fast \(DIS Flow\)$")

    def test_the_log_is_rotated_instead_of_growing_forever(self):
        self.module.MAX_BYTES = 200
        for index in range(20):
            self.module.write(f"linha {index}")
        content = self.read_log()
        self.assertIn("linha 19", content)
        self.assertNotIn("linha 0", content)

    def test_a_broken_path_never_raises(self):
        self.module.get_settings_path = lambda: str(Path(self.temp.name))
        self.module.write("silently dropped")     # the path points at a directory

    def test_logging_can_be_switched_off(self):
        self.module.ENABLED = False
        self.module.reset()
        self.module.write("nothing")
        self.assertFalse(self.module.log_path().exists())


if __name__ == "__main__":
    unittest.main()
