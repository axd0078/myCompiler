import unittest

from semantic import analyze_text, generate_output


SAMPLE_AST = """\
Program
  FunctionDecl(int main)[3]
    Compound
      VarDecl(int a)[4]
        10[4]
      VarDecl(float c)[5]
        3.14[5]
      VarDecl(char d)[6]
        A[6]
      VarDecl(int a)[7]
        20[7]
      VarDecl(int sum)[8]
        +[8]
          a[8]
          b[8]
      VarDecl(float product)[9]
        *[9]
          d[9]
          c[9]
      ReturnStmt[10]
        0[10]
"""

CALL_AST = """\
Program
  FunctionDecl(int add)[1]
    Param(int x)[1]
    Param(int y)[1]
  FunctionDecl(int main)[2]
    Compound
      VarDecl(int ok)[3]
        Call(add)[3]
          1[3]
          2[3]
      VarDecl(int badCount)[4]
        Call(add)[4]
          1[4]
      VarDecl(int badType)[5]
        Call(add)[5]
          1.0[5]
          2[5]
      ReturnStmt[6]
        0[6]
"""

FUNCTION_RULE_AST = """\
Program
  FunctionDecl(void f)[1]
    Compound
      ReturnStmt[2]
        1[2]
  FunctionDecl(int main)[4]
    Compound
      ConstDecl(int a)[5]
        1[5]
      ExprStmt
        =[6]
          a[6]
          2[6]
      ReturnStmt[7]
        0[7]
  FunctionDecl(int g)[9]
    Compound
      VarDecl(int x)[10]
        1[10]
"""

FUNCTION_DUP_AST = """\
Program
  FunctionDecl(int foo)[1]
    Param(int x)[1]
  FunctionDef(int foo)[3]
    Param(int x)[3]
    Compound
      ReturnStmt[4]
        x[4]
  FunctionDecl(int foo)[6]
    Param(int x)[6]
  FunctionDef(int foo)[8]
    Param(int x)[8]
    Compound
      ReturnStmt[9]
        x[9]
"""

LOOP_AST = """\
Program
  FunctionDecl(int main)[1]
    Compound
      VarDecl(int i)[2]
        0[2]
      WhileStmt
        <[3]
          i[3]
          10[3]
        ExprStmt
          =[4]
            i[4]
            +[4]
              i[4]
              1[4]
      ReturnStmt[5]
        0[5]
"""

TYPE_MISMATCH_AST = """\
Program
  FunctionDecl(int main)[1]
    Compound
      VarDecl(int a)[2]
        1[2]
      ExprStmt
        =[3]
          a[3]
          1.0[3]
      ExprStmt
        ==[4]
          a[4]
          1.0[4]
      ReturnStmt[5]
        0[5]
"""

CONST_ASSIGN_PRIORITY_AST = """\
Program
  FunctionDecl(int main)[1]
    Compound
      ConstDecl(int c)[2]
        1[2]
      ExprStmt
        =[3]
          c[3]
          +[3]
            1[3]
            1.0[3]
      ReturnStmt[4]
        0[4]
"""

NESTED_CONST_ASSIGN_AST = """\
Program
  FunctionDecl(int main)[1]
    Compound
      ConstDecl(int c)[2]
        1[2]
      ExprStmt
        =[3]
          +[3]
            c[3]
            1.0[3]
          2[3]
      ReturnStmt[4]
        0[4]
"""

UNKNOWN_EXPR_MISMATCH_AST = """\
Program
  FunctionDecl(int main)[1]
    Compound
      ExprStmt
        AdditiveExpr[29]
          1[29]
          1.0[29]
"""

UNKNOWN_STMT_MISMATCH_AST = """\
Program
  FunctionDecl(int main)[1]
    Compound
      AdditiveExpr[29]
        1[29]
        1.0[29]
"""

BINARY_EXPR_WITH_OPERATOR_MARKER_AST = """\
Program
  FunctionDecl(int main)[1]
    Compound
      ExprStmt
        BinaryExpr[29]
          +[29]
          1[29]
          1.0[29]
"""

LINELESS_ARITHMETIC_WRAPPER_AST = """\
Program
  FunctionDecl(int main)[1]
    Compound
      ExprStmt
        AdditiveExpr
          1[29]
          1.0[29]
"""

UNDECLARED_CALL_AST = """\
Program
  FunctionDecl(int main)[1]
    Compound
      ExprStmt
        Call(add)[2]
          1[2]
          2[2]
      ReturnStmt[3]
        0[3]
  FunctionDecl(int add)[5]
    Param(int x)[5]
    Param(int y)[5]
"""

IO_AST = """\
Program
  FunctionDecl(int main)[1]
    Compound
      VarDecl(int x)[2]
        0[2]
      InputStmt[3]
        x[3]
      OutputStmt[4]
        x[4]
      ReturnStmt[5]
        0[5]
"""

IO_ERROR_AST = """\
Program
  FunctionDecl(int main)[1]
    Compound
      ConstDecl(int c)[2]
        1[2]
      InputStmt[3]
        c[3]
      VarDecl(float y)[4]
        1.0[4]
      OutputStmt[5]
        y[5]
      ReturnStmt[6]
        0[6]
"""


class SemanticAnalyzerTest(unittest.TestCase):
    def test_sample_errors(self):
        self.assertEqual(generate_output(SAMPLE_AST), "7 301\n8 302\n")

    def test_function_call_checks(self):
        self.assertEqual(generate_output(CALL_AST), "4 305\n5 306\n")

    def test_return_and_const_assignment(self):
        self.assertEqual(generate_output(FUNCTION_RULE_AST), "2 307\n6 309\n10 307\n")

    def test_undeclared_function_call(self):
        self.assertEqual(generate_output(UNDECLARED_CALL_AST), "2 304\n")

    def test_duplicate_function_only_when_signature_conflicts_or_redefined(self):
        self.assertEqual(generate_output(FUNCTION_DUP_AST), "8 303\n")

    def test_loop_without_break_is_not_an_error(self):
        self.assertEqual(generate_output(LOOP_AST), "")

    def test_expression_type_mismatch_covers_assignment_and_comparison(self):
        self.assertEqual(generate_output(TYPE_MISMATCH_AST), "")

    def test_const_assignment_takes_priority_over_rhs_type_mismatch(self):
        self.assertEqual(generate_output(CONST_ASSIGN_PRIORITY_AST), "3 309\n")

    def test_nested_const_assignment_still_reports_309_first(self):
        self.assertEqual(generate_output(NESTED_CONST_ASSIGN_AST), "3 309\n")

    def test_unknown_expression_node_still_checks_child_types(self):
        self.assertEqual(generate_output(UNKNOWN_EXPR_MISMATCH_AST), "29 310\n")

    def test_unknown_statement_node_still_checks_child_expression_types(self):
        self.assertEqual(generate_output(UNKNOWN_STMT_MISMATCH_AST), "29 310\n")

    def test_binary_expression_operator_marker_checks_child_types(self):
        self.assertEqual(generate_output(BINARY_EXPR_WITH_OPERATOR_MARKER_AST), "29 310\n")

    def test_lineless_arithmetic_wrapper_uses_child_line(self):
        self.assertEqual(generate_output(LINELESS_ARITHMETIC_WRAPPER_AST), "29 310\n")

    def test_symbol_tables_are_generated(self):
        result = analyze_text(CALL_AST)
        self.assertIn("add int 1 decl int,int", result.function_table)
        self.assertIn("ok int 3", result.var_table)

    def test_input_output_statements_are_checked(self):
        self.assertEqual(generate_output(IO_AST), "")
        self.assertEqual(generate_output(IO_ERROR_AST), "3 309\n")


if __name__ == "__main__":
    unittest.main()
