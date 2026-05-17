"""语义分析阶段。

语义分析接收 Parser 生成的 AST，负责检查“语法正确但语义不合理”的问题：
重定义、未声明、函数签名不匹配、返回值错误、break 使用位置、内建 read/write 规则等。
"""

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


ERROR_NAME_REDEFINED = 301
ERROR_NAME_UNDECLARED = 302
ERROR_FUNCTION_REDEFINED = 303
ERROR_FUNCTION_UNDECLARED = 304
ERROR_ARGUMENT_COUNT = 305
ERROR_ARGUMENT_TYPE = 306
ERROR_RETURN_MISMATCH = 307
ERROR_BREAK_USAGE = 308
ERROR_ASSIGN_TO_CONST = 309
ERROR_OPERAND_TYPE = 310

FUNCTION_KINDS = {"FunctionDecl", "FunctionDef"}
BUILTIN_FUNCTIONS = {"read", "write"}
BLOCK_KINDS = {"Compound"}
STATEMENT_KINDS = {
    "Compound",
    "IfStmt",
    "WhileStmt",
    "ForStmt",
    "DoWhileStmt",
    "ExprStmt",
    "ReturnStmt",
    "ContinueStmt",
    "BreakStmt",
    "Empty",
}
DECL_KINDS = {"ConstDecl", "VarDecl"}
OPERATOR_SET = {"=", "||", "&&", "==", "!=", "<", ">", "<=", ">=", "+", "-", "*", "/", "%", "!"}
ARITHMETIC_OPERATORS = {"+", "-", "*", "/", "%"}
ARITHMETIC_NODE_NAMES = {
    "add",
    "addexpr",
    "additiveexpr",
    "additiveexpression",
    "addition",
    "plus",
    "sub",
    "subexpr",
    "subtraction",
    "minus",
    "mul",
    "mulexpr",
    "multiplicativeexpr",
    "multiplicativeexpression",
    "times",
    "multiply",
    "div",
    "divexpr",
    "divide",
    "division",
    "mod",
    "modexpr",
    "modulo",
    "modulus",
    "arithmeticexpr",
    "arithmeticexpression",
}
IDENTIFIER_RE = re.compile(r"[A-Za-z_]\w*")
INT_LITERAL_RE = re.compile(r"[+-]?(?:0|[1-9]\d*|0[xX][0-9A-Fa-f]+|0[0-7]+)")
FLOAT_LITERAL_RE = re.compile(r"[+-]?(?:(?:\d+\.\d*|\d*\.\d+)(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)")


@dataclass
class ASTNode:
    """语义模块使用的 AST 节点结构。

    这个结构与 intermediate.py 的 ASTNode 字段保持一致。
    """

    kind: str
    line: Optional[int] = None
    type_name: Optional[str] = None
    name: Optional[str] = None
    value: Optional[str] = None
    children: List["ASTNode"] = field(default_factory=list)


@dataclass
class Scope:
    """作用域节点，保存当前作用域直接声明的名字。"""

    id: int
    parent: Optional["Scope"]
    names: Dict[str, "Symbol"] = field(default_factory=dict)

    @property
    def depth(self) -> int:
        if self.parent is None:
            return 0
        return self.parent.depth + 1


@dataclass
class Symbol:
    """变量或常量符号。"""

    name: str
    type_name: str
    line: int
    scope_id: int
    kind: str
    role: str


@dataclass
class FunctionSymbol:
    """函数声明/定义的签名记录。"""

    name: str
    return_type: str
    line: int
    param_types: List[str]
    status: str


@dataclass
class ExprResult:
    """表达式分析结果。

    type_name 用于类型检查；symbol/is_lvalue 用于赋值左值和常量赋值检查。
    """

    type_name: Optional[str] = None
    symbol: Optional[Symbol] = None
    is_lvalue: bool = False


@dataclass
class FunctionContext:
    """分析函数体时保存的返回值上下文。"""

    return_type: str
    end_line: int
    any_return: bool = False
    valid_return: bool = False
    invalid_return: bool = False


@dataclass
class AnalysisResult:
    """语义分析输出。"""

    errors: List[Tuple[int, int]]
    const_table: str
    var_table: str
    function_table: str






class SemanticAnalyzer:
    """AST 语义检查器。"""

    def __init__(self, root: ASTNode):
        self.root = root
        self.errors: List[Tuple[int, int]] = []
        self.error_lines = set()
        self.scope_counter = 0
        self.const_records: List[Tuple[str, str, int, int, str]] = []
        self.var_records: List[Tuple[str, str, int, int, str, str]] = []
        self.functions: Dict[str, FunctionSymbol] = {}
        self.const_names = set()

    def analyze(self) -> AnalysisResult:
        """执行完整语义分析并返回错误和符号表文本。"""
        global_scope = self.new_scope(None)
        if self.root.kind != "Program":
            raise ValueError("AST root must be Program")

        for child in self.root.children:
            self.analyze_toplevel(child, global_scope)

        return AnalysisResult(
            errors=self.errors,
            const_table=self.format_const_table(),
            var_table=self.format_var_table(),
            function_table=self.format_function_table(),
        )

    def new_scope(self, parent: Optional[Scope]) -> Scope:
        """创建一个新作用域。"""
        scope = Scope(id=self.scope_counter, parent=parent)
        self.scope_counter += 1
        return scope

    def analyze_toplevel(self, node: ASTNode, scope: Scope) -> None:
        """分析顶层节点：全局声明或函数。"""
        if node.kind == "ConstDecl":
            self.handle_const_decl(node, scope)
            return
        if node.kind == "VarDecl":
            self.handle_var_decl(node, scope)
            return
        if node.kind in FUNCTION_KINDS:
            self.handle_function(node, scope)
            return
        self.analyze_statement(node, scope, None, loop_depth=0)

    def handle_function(self, node: ASTNode, global_scope: Scope) -> None:
        """检查函数声明/定义，并在函数体内建立参数作用域。"""
        params = [child for child in node.children if child.kind == "Param"]
        body = node.children[-1] if node.children and node.children[-1].kind == "Compound" else None
        status = "def" if body is not None else "decl"
        name = node.name or ""
        return_type = node.type_name or ""
        param_types = [param.type_name or "" for param in params]

        if name in BUILTIN_FUNCTIONS:
            self.record_error(node.line, ERROR_FUNCTION_REDEFINED)
            return

        existing = self.functions.get(name)
        if existing is None:
            self.functions[name] = FunctionSymbol(
                name=name,
                return_type=return_type,
                line=node.line or 0,
                param_types=param_types,
                status=status,
            )
        else:
            same_signature = (
                existing.return_type == return_type and existing.param_types == param_types
            )
            duplicate_definition = existing.status == "def" and status == "def"

            if not same_signature or duplicate_definition:
                self.record_error(node.line, ERROR_FUNCTION_REDEFINED)
            elif status == "def":
                existing.status = "def"

        if body is None:
            return

        function_scope = self.new_scope(global_scope)
        for param in params:
            symbol = self.declare_symbol(
                scope=function_scope,
                name=param.name or "",
                type_name=param.type_name or "",
                line=param.line or 0,
                kind="var",
                role="param",
            )
            if symbol is not None:
                self.var_records.append(
                    (symbol.name, symbol.type_name, symbol.line, symbol.scope_id, symbol.role, "-")
                )

        end_line = self.estimate_block_end_line(body, node.line or 1)
        context = FunctionContext(return_type=node.type_name or "void", end_line=end_line)
        self.analyze_compound(body, function_scope, context, loop_depth=0, create_scope=False)

        if context.return_type != "void" and not context.valid_return and name != "main":
            context.invalid_return = True
        if context.invalid_return:
            self.record_error(context.end_line, ERROR_RETURN_MISMATCH)

    def analyze_compound(
        self,
        node: ASTNode,
        scope: Scope,
        context: Optional[FunctionContext],
        loop_depth: int,
        create_scope: bool = True,
    ) -> bool:
        """分析复合语句块，必要时创建块级作用域。"""
        current_scope = self.new_scope(scope) if create_scope else scope
        found_break = False

        for child in node.children:
            if child.kind == "ConstDecl":
                self.handle_const_decl(child, current_scope)
                continue
            if child.kind == "VarDecl":
                self.handle_var_decl(child, current_scope)
                continue
            found_break = self.analyze_statement(child, current_scope, context, loop_depth) or found_break

        return found_break

    def analyze_statement(
        self,
        node: ASTNode,
        scope: Scope,
        context: Optional[FunctionContext],
        loop_depth: int,
    ) -> bool:
        """分析语句节点，返回该语句中是否出现 break。"""
        if node.kind == "Compound":
            return self.analyze_compound(node, scope, context, loop_depth, create_scope=True)

        if node.kind == "ExprStmt":
            if node.children:
                self.analyze_expression(node.children[0], scope)
            return False

        if node.kind == "Empty":
            return False

        if node.kind == "ReturnStmt":
            self.handle_return(node, scope, context)
            return False

        if node.kind == "IfStmt":
            if node.children:
                self.analyze_expression(node.children[0], scope)
            found_break = False
            if len(node.children) >= 2:
                found_break = self.analyze_statement(node.children[1], scope, context, loop_depth) or found_break
            if len(node.children) >= 3:
                found_break = self.analyze_statement(node.children[2], scope, context, loop_depth) or found_break
            return found_break

        if node.kind == "WhileStmt":
            if node.children:
                self.analyze_expression(node.children[0], scope)
            body = node.children[1] if len(node.children) > 1 else None
            return self.handle_loop_body(body, scope, context, loop_depth)

        if node.kind == "ForStmt":
            if node.children:
                for child in node.children[:-1]:
                    self.analyze_expression(child, scope)
                body = node.children[-1]
                return self.handle_loop_body(body, scope, context, loop_depth)
            return False

        if node.kind == "DoWhileStmt":
            body = node.children[0] if node.children else None
            if len(node.children) > 1:
                self.analyze_expression(node.children[1], scope)
            return self.handle_loop_body(body, scope, context, loop_depth)

        if node.kind == "BreakStmt":
            if loop_depth == 0:
                self.record_error(node.line, ERROR_BREAK_USAGE)
                return False
            return True

        if node.kind == "ContinueStmt":
            return False

        if node.children:
            self.analyze_expression(node, scope)

        return False

    """遇到循环语句 加上一层循环"""
    def handle_loop_body(
        self,
        body: Optional[ASTNode],
        scope: Scope,
        context: Optional[FunctionContext],
        loop_depth: int,
    ) -> bool:
        if body is None:
            return False

        self.analyze_statement(body, scope, context, loop_depth + 1)
        return False

    def handle_return(self, node: ASTNode, scope: Scope, context: Optional[FunctionContext]) -> None:
        """检查 return 是否符合当前函数返回类型。"""
        if context is None:
            return

        context.any_return = True
        expr = node.children[0] if node.children else None

        """void 后面不能跟东西"""
        if context.return_type == "void":
            if expr is None:
                context.valid_return = True
                return
            self.analyze_expression(expr, scope)
            context.invalid_return = True
            return

        """非void函数后面写了 return;"""
        if expr is None:
            context.invalid_return = True
            return

        """非void函数写了return expr; 判断返回类型对不对"""
        result = self.analyze_expression(expr, scope)
        if result.type_name is None or result.type_name == context.return_type:
            context.valid_return = True
        else:
            context.invalid_return = True

    """添加常量到变量表"""
    def handle_const_decl(self, node: ASTNode, scope: Scope) -> None:
        initializer = self.expr_to_text(node.children[0]) if node.children else "-"
        self.const_names.add(node.name or "")
        symbol = self.declare_symbol(
            scope=scope,
            name=node.name or "",
            type_name=node.type_name or "",
            line=node.line or 0,
            kind="const",
            role="const",
        )
        if symbol is not None:
            self.const_records.append(
                (symbol.name, symbol.type_name, symbol.line, symbol.scope_id, initializer)
            )
        if node.children:
            self.analyze_expression(node.children[0], scope)

    """添加变量到变量表"""
    def handle_var_decl(self, node: ASTNode, scope: Scope) -> None:
        initializer = self.expr_to_text(node.children[0]) if node.children else "-"
        symbol = self.declare_symbol(
            scope=scope,
            name=node.name or "",
            type_name=node.type_name or "",
            line=node.line or 0,
            kind="var",
            role="global" if scope.parent is None else "local",
        )
        if symbol is not None:
            self.var_records.append(
                (symbol.name, symbol.type_name, symbol.line, symbol.scope_id, symbol.role, initializer)
            )
        if node.children:
            self.analyze_expression(node.children[0], scope)

    def declare_symbol(
        self,
        scope: Scope,
        name: str,
        type_name: str,
        line: int,
        kind: str,
        role: str,
    ) -> Optional[Symbol]:
        """在当前作用域声明变量/常量/参数，并检查同作用域重定义。"""
        if name in scope.names:
            self.record_error(line, ERROR_NAME_REDEFINED)
            return None

        symbol = Symbol(
            name=name,
            type_name=type_name,
            line=line,
            scope_id=scope.id,
            kind=kind,
            role=role,
        )
        scope.names[name] = symbol
        return symbol

    """分析表达式类型、函数调用、赋值合法性和内建函数规则。"""
    def analyze_expression(self, node: ASTNode, scope: Scope) -> ExprResult:
        """叶子节点查作用域或识别字面量类型"""
        if node.kind == "Leaf":
            if node.children:
                return self.analyze_unknown_expression_node(node, scope)
            return self.analyze_leaf(node, scope)

        if node.kind == "Call":
            args = [self.analyze_expression(child, scope) for child in node.children]
            if node.name == "read":
                if args:
                    self.record_error(node.line, ERROR_ARGUMENT_COUNT)
                return ExprResult(type_name="int")
            if node.name == "write":
                if len(args) != 1:
                    self.record_error(node.line, ERROR_ARGUMENT_COUNT)
                elif args[0].type_name is not None and args[0].type_name != "int":
                    self.record_error(node.line, ERROR_ARGUMENT_TYPE)
                return ExprResult(type_name="void")

            function = self.functions.get(node.name or "")
            """函数未声明"""
            if function is None:
                self.record_error(node.line, ERROR_FUNCTION_UNDECLARED)
                return ExprResult()

            if len(args) != len(function.param_types):
                self.record_error(node.line, ERROR_ARGUMENT_COUNT)
            else:
                for arg, expected_type in zip(args, function.param_types):
                    if arg.type_name is not None and arg.type_name != expected_type:
                        self.record_error(node.line, ERROR_ARGUMENT_TYPE)
                        break
            return ExprResult(type_name=function.return_type)

        if node.kind != "Operator":
            return ExprResult()

        if len(node.children) == 1:
            child = self.analyze_expression(node.children[0], scope)
            if node.value == "!":
                return ExprResult(type_name="int")
            return ExprResult(type_name=child.type_name)

        if node.value == "=":
            """检查等号左边是不是常量"""
            if self.assignment_target_is_const_like(node.children[0], scope):
                self.record_error(node.line, ERROR_ASSIGN_TO_CONST)
            """再检查等号左右"""
            left = self.analyze_expression(node.children[0], scope)
            right = self.analyze_expression(node.children[1], scope)
            """最终算完再检查 防御性编程"""
            if node.line not in self.error_lines and not left.is_lvalue:
                self.record_error(node.line, ERROR_ASSIGN_TO_CONST)
            return ExprResult(type_name=left.type_name or right.type_name)

        """二元运算符"""
        left = self.analyze_expression(node.children[0], scope)
        right = self.analyze_expression(node.children[1], scope)

        """左右类型需要一致"""
        if self.is_arithmetic_operator_value(node.value):
            if self.types_mismatch(left.type_name, right.type_name):
                self.record_error(node.line, ERROR_OPERAND_TYPE)
            return ExprResult(type_name=left.type_name or right.type_name)

        if node.value in {"<", ">", "<=", ">=", "==", "!=", "&&", "||"}:
            return ExprResult(type_name="int")

        child_results = [left, right]
        for child in node.children[2:]:
            child_results.append(self.analyze_expression(child, scope))
        if self.contains_arithmetic_operator(node) and self.expression_types_mismatch(child_results):
            self.record_error(self.expression_error_line(node), ERROR_OPERAND_TYPE)
        return ExprResult(type_name=child_results[0].type_name if child_results else None)

    """一组表达式的操作数类型是否匹配"""
    def expression_types_mismatch(self, results: Sequence[ExprResult]) -> bool:
        categories = {
            self.type_category(result.type_name)
            for result in results
            if self.type_category(result.type_name) is not None
        }
        return len(categories) > 1

    """检查表达式左右两边的类型是否冲突"""
    def types_mismatch(self, left_type: Optional[str], right_type: Optional[str]) -> bool:
        left_category = self.type_category(left_type)
        right_category = self.type_category(right_type)
        return left_category is not None and right_category is not None and left_category != right_category

    def type_category(self, type_name: Optional[str]) -> Optional[str]:
        if type_name is None:
            return None
        if type_name in {"float", "double"}:
            return "real"
        return type_name

    """叶子节点带了子节点  防御性代码 配合470行"""
    def analyze_unknown_expression_node(self, node: ASTNode, scope: Scope) -> ExprResult:
        child_results = [self.analyze_expression(child, scope) for child in node.children]
        if self.contains_arithmetic_operator(node) and self.expression_types_mismatch(child_results):
            self.record_error(self.expression_error_line(node), ERROR_OPERAND_TYPE)
        for result in child_results:
            if result.type_name is not None:
                return ExprResult(type_name=result.type_name)
        return ExprResult()

    """判断字符串值是否代表算术运算符"""
    def is_arithmetic_operator_value(self, value: Optional[str]) -> bool:
        if value is None:
            return False
        normalized = value.strip().lower()
        if normalized in ARITHMETIC_OPERATORS or normalized in ARITHMETIC_NODE_NAMES:
            return True
        return any(marker in value for marker in ARITHMETIC_OPERATORS)

    """判断AST子树是否涉及算术运算"""
    def contains_arithmetic_operator(self, node: ASTNode) -> bool:
        if self.is_arithmetic_operator_value(node.value):
            return True
        return any(self.contains_arithmetic_operator(child) for child in node.children)

    """定位具体报错行数"""
    def expression_error_line(self, node: ASTNode) -> Optional[int]:
        if node.line is not None:
            return node.line
        for child in node.children:
            line = self.expression_error_line(child)
            if line is not None:
                return line
        return None

    """判断左侧是不是常量"""
    def assignment_target_is_const_like(self, node: ASTNode, scope: Scope) -> bool:
        if self.assignment_target_contains_const(node, scope):
            return True
        if node.kind != "Leaf":
            return True
        return self.detect_literal_type(node.value or "") is not None

    """判断有没有对常量复制"""
    def assignment_target_contains_const(self, node: ASTNode, scope: Scope) -> bool:
        if node.kind == "Leaf":
            symbol = self.lookup_symbol(scope, node.value or "")
            if symbol is not None and symbol.kind == "const":
                return True
            return (node.value or "") in self.const_names

        for child in node.children:
            if self.assignment_target_contains_const(child, scope):
                return True
        return False

    """到达叶子节点 这个叶子是什么"""
    def analyze_leaf(self, node: ASTNode, scope: Scope) -> ExprResult:
        """分析变量引用或字面量。"""
        text = node.value or ""
        symbol = self.lookup_symbol(scope, text)
        if symbol is not None:
            return ExprResult(
                type_name=symbol.type_name,
                symbol=symbol,
                is_lvalue=symbol.kind == "var",
            )

        literal_type = self.detect_literal_type(text)
        if literal_type is not None:
            return ExprResult(type_name=literal_type)

        """未声明的标识符"""
        if IDENTIFIER_RE.fullmatch(text):
            self.record_error(node.line, ERROR_NAME_UNDECLARED)
        return ExprResult()

    def lookup_symbol(self, scope: Scope, name: str) -> Optional[Symbol]:
        """从当前作用域向父作用域查找符号。"""
        current: Optional[Scope] = scope
        while current is not None:
            if name in current.names:
                return current.names[name]
            current = current.parent
        return None

    def detect_literal_type(self, text: str) -> Optional[str]:
        """判断字面量类型"""
        if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
            return "string"
        if len(text) >= 3 and text[0] == "'" and text[-1] == "'":
            return "char"
        if FLOAT_LITERAL_RE.fullmatch(text):
            return "float"
        if INT_LITERAL_RE.fullmatch(text):
            return "int"
        if text in {"\\n", "\\t", "\\r", "\\0", "\\\\", "\\'"}:
            return "char"
        if len(text) == 1 and not text.isdigit() and (text.isupper() or not IDENTIFIER_RE.fullmatch(text)):
            return "char"
        return None

    """找最大行号"""
    def max_line(self, node: Optional[ASTNode]) -> Optional[int]:
        if node is None:
            return None

        candidate = node.line
        for child in node.children:
            child_line = self.max_line(child)
            if child_line is not None:
                candidate = child_line if candidate is None else max(candidate, child_line)
        return candidate

    """发现函数返回值问题时 报错应该在函数体最后一行"""
    def estimate_block_end_line(self, node: Optional[ASTNode], fallback: int) -> int:
        if node is None:
            return fallback
        max_line = self.max_line(node)
        if max_line is None:
            return fallback
        return max_line

    def record_error(self, line: Optional[int], code: int) -> None:
        """记录语义错误；同一行只保留一个错误，减少级联报错。"""
        if line is None or line in self.error_lines:
            return
        self.error_lines.add(line)
        self.errors.append((line, code))

    """AST树转源代码文本"""
    def expr_to_text(self, node: ASTNode) -> str:
        if node.kind == "Leaf":
            return node.value or ""
        if node.kind == "Call":
            args = ",".join(self.expr_to_text(child) for child in node.children)
            return f"{node.name}({args})"
        if node.kind == "Operator":
            if len(node.children) == 1:
                return f"{node.value}{self.expr_to_text(node.children[0])}"
            left = self.expr_to_text(node.children[0])
            right = self.expr_to_text(node.children[1])
            return f"({left}{node.value}{right})"
        return node.kind

    def format_const_table(self) -> str:
        return self.format_rows(
            f"{name} {type_name} {line} {scope_id} {initializer}"
            for name, type_name, line, scope_id, initializer in self.const_records
        )

    def format_var_table(self) -> str:
        return self.format_rows(
            f"{name} {type_name} {line} {scope_id} {role} {initializer}"
            for name, type_name, line, scope_id, role, initializer in self.var_records
        )

    def format_function_table(self) -> str:
        return self.format_rows(
            f"{symbol.name} {symbol.return_type} {symbol.line} {symbol.status} "
            f"{','.join(symbol.param_types) if symbol.param_types else '-'}"
            for symbol in self.functions.values()
        )

    """格式化输出"""
    @staticmethod
    def format_rows(rows: Iterable[str]) -> str:
        materialized = list(rows)
        if not materialized:
            return ""
        return "\n".join(materialized) + "\n"
