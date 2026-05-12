import unittest

from intermediate import generate_output


SAMPLE_SOURCE = """\
int main() {
    int x = 10;
    float y = 20.5;

    if (x > 0) {
        float a = 5.5;
        y = a + 1;
    }
    return 0;
}
"""


SAMPLE_QUADS = """\
0: ('main', '_', '_', '_')
1: ('=', '10', '_', 'x')
2: ('=', '20.5', '_', 'y')
3: ('J>', 'x', '0', 5)
4: ('J', '_', '_', 8)
5: ('=', '5.5', '_', 'a')
6: ('+', 'a', '1', 't1')
7: ('=', 't1', '_', 'y')
8: ('ret', '_', '_', '0')
9: ('sys', '_', '_', '_')
"""


class IntermediateCodeTest(unittest.TestCase):
    def test_sample_quadruples(self):
        self.assertEqual(generate_output(SAMPLE_SOURCE), SAMPLE_QUADS)

    def test_call_and_while_quadruples(self):
        source = """\
int add(int x, int y);
int main() {
  int i = 0;
  while (i < 3)
    i = add(i, 1);
  return i;
}
"""
        output = generate_output(source)
        self.assertIn("('para', 'i', '_', '_')", output)
        self.assertIn("('call', 'add', '_', 't1')", output)
        self.assertIn("('J<', 'i', '3', 4)", output)
        self.assertTrue(output.endswith("10: ('sys', '_', '_', '_')\n"))

    def test_cpp_stream_quadruples(self):
        source = """\
#include <iostream>
using namespace std;
int main() {
  int x;
  cin >> x;
  cout << x << '\\n';
  return 0;
}
"""
        output = generate_output(source)
        self.assertIn("('in', '_', '_', 'x')", output)
        self.assertIn("('out', 'x', '_', '_')", output)
        self.assertIn("('ret', '_', '_', '0')", output)


if __name__ == "__main__":
    unittest.main()
