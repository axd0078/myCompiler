import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from csp_frontend import load_translation_unit


ROOT = Path(__file__).resolve().parents[1]
CSP_ROOT = Path(r"D:\study\code\data_structure-study\programming\test\csp")


@unittest.skipUnless(CSP_ROOT.exists(), "CSP corpus is not available")
class CspFrontendCorpusTest(unittest.TestCase):
    def test_tokenizes_all_csp_sources(self):
        files = sorted(CSP_ROOT.rglob("*.cpp"))
        self.assertGreaterEqual(len(files), 1)
        for path in files:
            with self.subTest(path=str(path.relative_to(CSP_ROOT))):
                unit = load_translation_unit(path)
                self.assertTrue(unit.preprocessed.includes)
                self.assertTrue(unit.features.includes_bits)
                self.assertGreater(len(unit.tokens), 0)

    def test_detects_representative_csp_features(self):
        unit = load_translation_unit(CSP_ROOT / "41" / "3.cpp")
        self.assertIn("vector", unit.features.containers)
        self.assertIn("map", unit.features.containers)
        self.assertIn("set", unit.features.containers)
        self.assertTrue(unit.features.has_struct)
        self.assertTrue(unit.features.has_range_for)

    def test_compile_dir_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "mycompiler.py"),
                    "--compile-dir",
                    str(CSP_ROOT),
                    "--out-dir",
                    tmp,
                    "-S",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            report_path = Path(tmp) / "compile_report.txt"
            self.assertTrue(report_path.exists())
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("CSP compile report", report)
            self.assertIn("bits/stdc++.h: True", report)


if __name__ == "__main__":
    unittest.main()
