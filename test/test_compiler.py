import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CompilerIntegrationTest(unittest.TestCase):
    def compile_and_run(self, source, stdin=""):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "sample.cpp"
            asm_path = tmp_path / "sample.s"
            exe_path = tmp_path / "sample.exe"
            source_path.write_text(source, encoding="utf-8")

            compile_result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "mycompiler.py"),
                    str(source_path),
                    "-S",
                    "-o",
                    str(asm_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            self.assertTrue(asm_path.exists())

            if shutil.which("gcc") is None:
                self.skipTest("gcc is not available")

            link_result = subprocess.run(
                ["gcc", str(asm_path), "-o", str(exe_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(link_result.returncode, 0, link_result.stderr)

            return subprocess.run(
                [str(exe_path)],
                input=stdin,
                capture_output=True,
                text=True,
            )

    def test_function_call_exit_code(self):
        result = self.compile_and_run(
            """\
int add(int a, int b) { return a + b; }
int main() { return add(2, 3); }
"""
        )
        self.assertEqual(result.returncode, 5)

    def test_fifth_argument_uses_stack_call_slot(self):
        result = self.compile_and_run(
            """\
int fifth(int a, int b, int c, int d, int e) { return e; }
int main() { return fifth(1, 2, 3, 4, 9); }
"""
        )
        self.assertEqual(result.returncode, 9)

    def test_calls_inside_binary_expression(self):
        result = self.compile_and_run(
            """\
int id(int x) { return x; }
int main() { return id(1) + id(2); }
"""
        )
        self.assertEqual(result.returncode, 3)

    def test_control_flow_exit_code(self):
        result = self.compile_and_run(
            """\
int main() {
    int sum = 0;
    int i = 0;
    for (i = 0; i < 4; i = i + 1) {
        if (i == 2) continue;
        sum = sum + i;
    }
    do {
        sum = sum + 1;
    } while (sum < 5);
    return sum;
}
"""
        )
        self.assertEqual(result.returncode, 5)

    def test_cin_cout_chain(self):
        result = self.compile_and_run(
            """\
#include <iostream>
using namespace std;
int main() {
    int a;
    int b;
    cin >> a >> b;
    cout << a + b << '\\n';
    return 0;
}
""",
            stdin="3 4\n",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "7\n")

    def test_char_input_output(self):
        result = self.compile_and_run(
            """\
#include <iostream>
using namespace std;
int main() {
    char c;
    cin >> c;
    cout << c << '\\n';
    return 0;
}
""",
            stdin="Z\n",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "Z\n")

    def test_csp_style_loop_sugar(self):
        result = self.compile_and_run(
            """\
#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int n;
    cin >> n;
    int sum = 0;
    for (int i = 0; i < n; i++) {
        sum += i;
    }
    while (n--) {
        sum += 1;
    }
    cout << sum << endl;
    return sum;
}
""",
            stdin="4\n",
        )
        self.assertEqual(result.returncode, 10)
        self.assertEqual(result.stdout, "10\n")

    def test_string_output_and_builtin_abs_min_max(self):
        result = self.compile_and_run(
            """\
#include <bits/stdc++.h>
using namespace std;
int main() {
    int a = abs(3 - 8);
    int b = min(a, 4);
    int c = max(b, 6);
    cout << "v=" << c << endl;
    return c;
}
"""
        )
        self.assertEqual(result.returncode, 6)
        self.assertEqual(result.stdout, "v=6\n")

    def test_bits_source_can_emit_skeleton_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "fallback.cpp"
            asm_path = tmp_path / "fallback.s"
            source_path.write_text(
                """\
#include <bits/stdc++.h>
using namespace std;
int main() {
    vector<int> xs;
    xs.push_back(1);
    return xs[0];
}
""",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "mycompiler.py"),
                    str(source_path),
                    "-S",
                    "-o",
                    str(asm_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("CSP skeleton fallback assembly", asm_path.read_text(encoding="utf-8"))

    def test_unsupported_float_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "bad.cpp"
            asm_path = Path(tmp) / "bad.s"
            source_path.write_text(
                """\
int main() {
    float x = 1.0;
    return 0;
}
""",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "mycompiler.py"),
                    str(source_path),
                    "-S",
                    "-o",
                    str(asm_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("float", result.stderr)
            self.assertFalse(asm_path.exists())


if __name__ == "__main__":
    unittest.main()
