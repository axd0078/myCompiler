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
                self.assertIsNotNone(unit.skeleton)
                self.assertTrue(unit.skeleton.has_main())
                for function in unit.skeleton.functions:
                    if function.has_body:
                        self.assertIsNotNone(function.body)

    def test_detects_representative_csp_features(self):
        unit = load_translation_unit(CSP_ROOT / "41" / "3.cpp")
        self.assertIn("vector", unit.features.containers)
        self.assertIn("map", unit.features.containers)
        self.assertIn("set", unit.features.containers)
        self.assertTrue(unit.features.has_struct)
        self.assertTrue(unit.features.has_range_for)
        self.assertGreaterEqual(len(unit.skeleton.structs), 1)
        self.assertTrue(any(function.name == "main" for function in unit.skeleton.functions))
        statement_counts = unit.skeleton.statement_kind_counts()
        self.assertGreaterEqual(statement_counts.get("RangeForStmt", 0), 1)
        self.assertGreaterEqual(statement_counts.get("InputStmt", 0), 1)
        self.assertGreaterEqual(statement_counts.get("OutputStmt", 0), 1)

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
            self.assertEqual(result.returncode, 0, result.stderr)
            report_path = Path(tmp) / "compile_report.txt"
            self.assertTrue(report_path.exists())
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("CSP compile report", report)
            self.assertIn("FALLBACK", report)

            generated = list(Path(tmp).rglob("*.s"))
            self.assertEqual(len(generated), len(list(CSP_ROOT.rglob("*.cpp"))))


if __name__ == "__main__":
    unittest.main()
