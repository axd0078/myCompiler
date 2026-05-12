from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set


CPP_KEYWORDS = {
    "auto",
    "bool",
    "break",
    "case",
    "catch",
    "char",
    "class",
    "const",
    "continue",
    "default",
    "delete",
    "do",
    "double",
    "else",
    "enum",
    "false",
    "float",
    "for",
    "friend",
    "if",
    "int",
    "long",
    "namespace",
    "new",
    "operator",
    "private",
    "protected",
    "public",
    "return",
    "short",
    "signed",
    "sizeof",
    "static",
    "struct",
    "switch",
    "template",
    "this",
    "throw",
    "true",
    "try",
    "typedef",
    "typename",
    "unsigned",
    "using",
    "void",
    "while",
}

MULTI_CHAR_OPERATORS = [
    ">>=",
    "<<=",
    "->*",
    "...",
    "::",
    "++",
    "--",
    "->",
    "&&",
    "||",
    "==",
    "!=",
    "<=",
    ">=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "<<",
    ">>",
]

SINGLE_CHAR_OPERATORS = set("{}[]()<>;:,.?~!+-*/%=&|^")
CONTAINER_NAMES = {
    "vector",
    "string",
    "pair",
    "map",
    "set",
    "unordered_map",
    "unordered_set",
    "queue",
    "stack",
    "priority_queue",
}
STL_FUNCTIONS = {
    "sort",
    "reverse",
    "prev",
    "lower_bound",
    "min",
    "max",
    "abs",
    "llabs",
    "sin",
    "cos",
}


class CspFrontendError(Exception):
    pass


@dataclass
class PreprocessResult:
    source: str
    includes: List[str] = field(default_factory=list)
    using_namespaces: List[str] = field(default_factory=list)
    skipped_lines: Dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CppToken:
    kind: str
    lexeme: str
    line: int
    column: int


@dataclass
class FeatureReport:
    includes_bits: bool = False
    uses_std_namespace: bool = False
    identifiers: Set[str] = field(default_factory=set)
    containers: Set[str] = field(default_factory=set)
    stl_functions: Set[str] = field(default_factory=set)
    scalar_types: Set[str] = field(default_factory=set)
    operators: Set[str] = field(default_factory=set)
    has_struct: bool = False
    has_class: bool = False
    has_lambda: bool = False
    has_range_for: bool = False
    has_reference: bool = False
    has_pointer: bool = False
    has_member_access: bool = False
    has_string_literal: bool = False
    has_float_literal: bool = False

    def summary_lines(self) -> List[str]:
        lines = [
            "bits/stdc++.h: %s" % self.includes_bits,
            "using namespace std: %s" % self.uses_std_namespace,
            "scalar types: %s" % self.format_set(self.scalar_types),
            "containers: %s" % self.format_set(self.containers),
            "stl functions: %s" % self.format_set(self.stl_functions),
            "operators: %s" % self.format_set(self.operators),
        ]
        flags = [
            name
            for name, enabled in [
                ("struct", self.has_struct),
                ("class", self.has_class),
                ("lambda", self.has_lambda),
                ("range-for", self.has_range_for),
                ("reference", self.has_reference),
                ("pointer", self.has_pointer),
                ("member-access", self.has_member_access),
                ("string-literal", self.has_string_literal),
                ("float-literal", self.has_float_literal),
            ]
            if enabled
        ]
        lines.append("flags: %s" % (", ".join(flags) if flags else "-"))
        return lines

    @staticmethod
    def format_set(values: Iterable[str]) -> str:
        materialized = sorted(values)
        return ", ".join(materialized) if materialized else "-"


@dataclass
class CspTranslationUnit:
    path: Optional[Path]
    preprocessed: PreprocessResult
    tokens: List[CppToken]
    features: FeatureReport
    skeleton: Optional["CspSkeleton"] = None


@dataclass
class CspFunction:
    name: str
    line: int
    return_tokens: List[str]
    parameter_tokens: List[str]
    has_body: bool
    body_token_count: int = 0
    body: Optional["CspBlock"] = None


@dataclass
class CspStruct:
    name: str
    line: int
    token_count: int


@dataclass
class CspGlobalDecl:
    name: str
    line: int
    type_tokens: List[str]


@dataclass
class CspStatement:
    kind: str
    line: int
    tokens: List[str] = field(default_factory=list)
    children: List["CspStatement"] = field(default_factory=list)


@dataclass
class CspBlock:
    line: int
    statements: List[CspStatement] = field(default_factory=list)

    def statement_kind_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}

        def visit(statement: CspStatement) -> None:
            counts[statement.kind] = counts.get(statement.kind, 0) + 1
            for child in statement.children:
                visit(child)

        for statement in self.statements:
            visit(statement)
        return counts


@dataclass
class CspSkeleton:
    functions: List[CspFunction] = field(default_factory=list)
    structs: List[CspStruct] = field(default_factory=list)
    globals: List[CspGlobalDecl] = field(default_factory=list)

    def has_main(self) -> bool:
        return any(function.name == "main" and function.has_body for function in self.functions)

    def statement_kind_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for function in self.functions:
            if function.body is None:
                continue
            for kind, count in function.body.statement_kind_counts().items():
                counts[kind] = counts.get(kind, 0) + count
        return counts

    def summary_lines(self) -> List[str]:
        defined_functions = sum(1 for function in self.functions if function.has_body)
        counts = self.statement_kind_counts()
        statement_summary = ", ".join(
            "%s=%d" % (kind, counts[kind]) for kind in sorted(counts)
        )
        return [
            "functions: %d defined / %d total" % (defined_functions, len(self.functions)),
            "structs: %d" % len(self.structs),
            "globals: %d" % len(self.globals),
            "main: %s" % self.has_main(),
            "statements: %s" % (statement_summary if statement_summary else "-"),
        ]


def preprocess_source(source: str) -> PreprocessResult:
    result = PreprocessResult(source="")
    output_lines: List[str] = []

    for line_number, raw_line in enumerate(source.splitlines(), 1):
        stripped = raw_line.strip()
        if stripped.startswith("#include"):
            result.includes.append(stripped)
            result.skipped_lines[line_number] = raw_line
            output_lines.append("")
            continue
        if stripped.startswith("using namespace"):
            namespace = stripped.removeprefix("using namespace").strip().rstrip(";").strip()
            result.using_namespaces.append(namespace)
            result.skipped_lines[line_number] = raw_line
            output_lines.append("")
            continue
        output_lines.append(raw_line)

    result.source = "\n".join(output_lines)
    if source.endswith("\n"):
        result.source += "\n"
    return result


class CppLexer:
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: List[CppToken] = []

    def tokenize(self) -> List[CppToken]:
        while not self.at_end():
            self.skip_space_and_comments()
            if self.at_end():
                break

            ch = self.current()
            if ch.isalpha() or ch == "_":
                self.tokens.append(self.read_identifier())
            elif ch.isdigit() or (ch == "." and self.peek().isdigit()):
                self.tokens.append(self.read_number())
            elif ch == '"':
                self.tokens.append(self.read_string())
            elif ch == "'":
                self.tokens.append(self.read_char())
            else:
                self.tokens.append(self.read_operator())

        return self.tokens

    def at_end(self) -> bool:
        return self.pos >= len(self.source)

    def current(self) -> str:
        if self.at_end():
            return "\0"
        return self.source[self.pos]

    def peek(self, distance: int = 1) -> str:
        index = self.pos + distance
        if index >= len(self.source):
            return "\0"
        return self.source[index]

    def advance(self) -> str:
        ch = self.current()
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def skip_space_and_comments(self) -> None:
        while not self.at_end():
            ch = self.current()
            if ch in " \t\r\n":
                self.advance()
                continue
            if ch == "/" and self.peek() == "/":
                while not self.at_end() and self.current() != "\n":
                    self.advance()
                continue
            if ch == "/" and self.peek() == "*":
                self.advance()
                self.advance()
                while not self.at_end():
                    if self.current() == "*" and self.peek() == "/":
                        self.advance()
                        self.advance()
                        break
                    self.advance()
                continue
            break

    def read_identifier(self) -> CppToken:
        line, column = self.line, self.column
        start = self.pos
        while not self.at_end() and (self.current().isalnum() or self.current() == "_"):
            self.advance()
        lexeme = self.source[start:self.pos]
        kind = "keyword" if lexeme in CPP_KEYWORDS else "identifier"
        return CppToken(kind, lexeme, line, column)

    def read_number(self) -> CppToken:
        line, column = self.line, self.column
        start = self.pos

        if self.current() == "0" and self.peek() in {"x", "X"}:
            self.advance()
            self.advance()
            while self.current().isalnum() or self.current() == "_":
                self.advance()
            return CppToken("number", self.source[start:self.pos], line, column)

        saw_dot = False
        while not self.at_end():
            ch = self.current()
            if ch.isdigit():
                self.advance()
                continue
            if ch == "." and not saw_dot:
                saw_dot = True
                self.advance()
                continue
            if ch in {"e", "E"}:
                self.advance()
                if self.current() in {"+", "-"}:
                    self.advance()
                continue
            if ch.isalpha() or ch == "_":
                self.advance()
                continue
            break
        return CppToken("number", self.source[start:self.pos], line, column)

    def read_string(self) -> CppToken:
        return self.read_quoted('"', "string")

    def read_char(self) -> CppToken:
        return self.read_quoted("'", "char")

    def read_quoted(self, quote: str, kind: str) -> CppToken:
        line, column = self.line, self.column
        start = self.pos
        self.advance()
        while not self.at_end():
            ch = self.advance()
            if ch == "\\" and not self.at_end():
                self.advance()
                continue
            if ch == quote:
                break
        return CppToken(kind, self.source[start:self.pos], line, column)

    def read_operator(self) -> CppToken:
        line, column = self.line, self.column
        for operator in MULTI_CHAR_OPERATORS:
            if self.source.startswith(operator, self.pos):
                for _ in operator:
                    self.advance()
                return CppToken("operator", operator, line, column)

        ch = self.advance()
        if ch in SINGLE_CHAR_OPERATORS:
            return CppToken("operator", ch, line, column)
        raise CspFrontendError("Line %d:%d: unsupported character %r" % (line, column, ch))


def analyze_features(
    tokens: Sequence[CppToken],
    preprocess: Optional[PreprocessResult] = None,
) -> FeatureReport:
    report = FeatureReport()
    if preprocess is not None:
        report.includes_bits = any("bits/stdc++.h" in include for include in preprocess.includes)
        report.uses_std_namespace = "std" in preprocess.using_namespaces

    for index, token in enumerate(tokens):
        if token.kind in {"identifier", "keyword"}:
            report.identifiers.add(token.lexeme)
        if token.lexeme in CONTAINER_NAMES:
            report.containers.add(token.lexeme)
        if token.lexeme in STL_FUNCTIONS:
            report.stl_functions.add(token.lexeme)
        if token.lexeme in {"char", "int", "long", "unsigned", "float", "double", "bool", "void"}:
            report.scalar_types.add(token.lexeme)
        if token.kind == "operator":
            report.operators.add(token.lexeme)
        if token.lexeme == "struct":
            report.has_struct = True
        if token.lexeme == "class":
            report.has_class = True
        if token.kind == "string":
            report.has_string_literal = True
        if token.kind == "number" and any(marker in token.lexeme for marker in [".", "e", "E"]):
            report.has_float_literal = True
        if token.lexeme in {".", "->", "::"}:
            report.has_member_access = True
        if token.lexeme == "*" and looks_like_declarator(tokens, index):
            report.has_pointer = True
        if token.lexeme == "&" and looks_like_declarator(tokens, index):
            report.has_reference = True
        if token.lexeme == "[" and index + 1 < len(tokens) and tokens[index + 1].lexeme == "]":
            report.has_lambda = True
        if token.lexeme == "for" and token_starts_range_for(tokens, index):
            report.has_range_for = True

    return report


def looks_like_declarator(tokens: Sequence[CppToken], index: int) -> bool:
    if index == 0 or index + 1 >= len(tokens):
        return False
    left = tokens[index - 1].lexeme
    right = tokens[index + 1]
    return left in CPP_KEYWORDS or left in CONTAINER_NAMES or right.kind == "identifier"


def token_starts_range_for(tokens: Sequence[CppToken], index: int) -> bool:
    depth = 0
    for token in tokens[index + 1 :]:
        if token.lexeme == "(":
            depth += 1
            continue
        if token.lexeme == ")":
            depth -= 1
            if depth <= 0:
                return False
        if token.lexeme == ":" and depth == 1:
            return True
        if token.lexeme == ";" and depth == 1:
            return False
    return False


def load_translation_unit(path: Path) -> CspTranslationUnit:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    preprocessed = preprocess_source(text)
    tokens = CppLexer(preprocessed.source).tokenize()
    features = analyze_features(tokens, preprocessed)
    skeleton = CspSkeletonParser(tokens).parse()
    return CspTranslationUnit(
        path=path,
        preprocessed=preprocessed,
        tokens=tokens,
        features=features,
        skeleton=skeleton,
    )


class CspSkeletonParser:
    def __init__(self, tokens: Sequence[CppToken]):
        self.tokens = list(tokens)
        self.pos = 0
        self.skeleton = CspSkeleton()

    def parse(self) -> CspSkeleton:
        while self.pos < len(self.tokens):
            token = self.tokens[self.pos]
            if token.lexeme == "typedef" and self.peek_lexeme(1) == "struct":
                self.parse_struct(is_typedef=True)
                continue
            if token.lexeme == "struct":
                self.parse_struct(is_typedef=False)
                continue
            if self.try_parse_function_or_global():
                continue
            self.pos += 1
        return self.skeleton

    def parse_struct(self, is_typedef: bool) -> None:
        start = self.pos
        line = self.tokens[self.pos].line
        if is_typedef:
            self.pos += 1
        self.pos += 1

        name = ""
        if self.current_kind() == "identifier":
            name = self.tokens[self.pos].lexeme
            self.pos += 1

        if self.current_lexeme() != "{":
            self.skip_until_top_level(";")
            return

        end_brace = self.matching_index(self.pos, "{", "}")
        if end_brace is None:
            raise CspFrontendError("Line %d: unclosed struct body" % line)

        self.pos = end_brace + 1
        if is_typedef and self.current_kind() == "identifier":
            name = self.tokens[self.pos].lexeme
            self.pos += 1

        self.skip_optional_declarators_to_semicolon()
        self.skeleton.structs.append(
            CspStruct(name=name or "<anonymous>", line=line, token_count=self.pos - start)
        )

    def try_parse_function_or_global(self) -> bool:
        start = self.pos
        statement_end = self.find_top_level_statement_end(start)
        if statement_end is None:
            return False

        lparen = self.find_top_level_token("(", start, statement_end)
        if lparen is not None:
            rparen = self.matching_index(lparen, "(", ")")
            if rparen is not None:
                body_start = self.skip_cv_after_parameters(rparen + 1)
                if body_start < len(self.tokens) and self.tokens[body_start].lexeme in {"{", ";"}:
                    function = self.build_function(start, lparen, rparen, body_start)
                    if function is not None:
                        self.skeleton.functions.append(function)
                        if self.tokens[body_start].lexeme == "{":
                            body_end = self.matching_index(body_start, "{", "}")
                            if body_end is None:
                                raise CspFrontendError(
                                    "Line %d: unclosed function body" % self.tokens[body_start].line
                                )
                            self.pos = body_end + 1
                        else:
                            self.pos = body_start + 1
                        return True

        if self.tokens[statement_end].lexeme == ";":
            self.collect_global_decls(start, statement_end)
            self.pos = statement_end + 1
            return True

        return False

    def build_function(
        self,
        start: int,
        lparen: int,
        rparen: int,
        body_start: int,
    ) -> Optional[CspFunction]:
        name_index = lparen - 1
        if name_index < start:
            return None

        name = self.tokens[name_index].lexeme
        if name == ")":
            return None
        if name == "operator":
            name = "operator"
        if name in CPP_KEYWORDS and name != "operator":
            return None

        return_tokens = [token.lexeme for token in self.tokens[start:name_index]]
        parameter_tokens = [token.lexeme for token in self.tokens[lparen + 1 : rparen]]
        has_body = self.tokens[body_start].lexeme == "{"
        body_token_count = 0
        body = None
        if has_body:
            body_end = self.matching_index(body_start, "{", "}")
            if body_end is not None:
                body_tokens = self.tokens[body_start + 1 : body_end]
                body_token_count = len(body_tokens)
                body = CspStatementParser(body_tokens, self.tokens[body_start].line).parse_block()
        return CspFunction(
            name=name,
            line=self.tokens[name_index].line,
            return_tokens=return_tokens,
            parameter_tokens=parameter_tokens,
            has_body=has_body,
            body_token_count=body_token_count,
            body=body,
        )

    def collect_global_decls(self, start: int, end: int) -> None:
        segment = self.tokens[start:end]
        if not segment:
            return
        if any(token.lexeme in {"=", "(", ")"} for token in segment):
            return
        for index, token in enumerate(segment):
            if token.kind == "identifier":
                previous = segment[index - 1].lexeme if index > 0 else ""
                next_lexeme = segment[index + 1].lexeme if index + 1 < len(segment) else ""
                if previous in {",", "*", "&"} or next_lexeme in {",", "[", ""}:
                    self.skeleton.globals.append(
                        CspGlobalDecl(
                            name=token.lexeme,
                            line=token.line,
                            type_tokens=[item.lexeme for item in segment[:index]],
                        )
                    )

    def find_top_level_statement_end(self, start: int) -> Optional[int]:
        depth = {"(": 0, "[": 0, "{": 0, "<": 0}
        index = start
        while index < len(self.tokens):
            lexeme = self.tokens[index].lexeme
            if all(value == 0 for value in depth.values()) and lexeme in {";", "{"}:
                return index

            if lexeme in {"(", "[", "{"}:
                depth[lexeme] += 1
            elif lexeme == ")" and depth["("] > 0:
                depth["("] -= 1
            elif lexeme == "]" and depth["["] > 0:
                depth["["] -= 1
            elif lexeme == "}" and depth["{"] > 0:
                depth["{"] -= 1
            elif lexeme == "<" and self.looks_like_template_angle(index):
                depth["<"] += 1
            elif lexeme == ">" and depth["<"] > 0:
                depth["<"] -= 1

            index += 1
        return None

    def find_top_level_token(self, target: str, start: int, end: int) -> Optional[int]:
        angle_depth = 0
        for index in range(start, end + 1):
            lexeme = self.tokens[index].lexeme
            if lexeme == "<" and self.looks_like_template_angle(index):
                angle_depth += 1
                continue
            if lexeme == ">" and angle_depth > 0:
                angle_depth -= 1
                continue
            if angle_depth == 0 and lexeme == target:
                return index
        return None

    def matching_index(self, start: int, open_lexeme: str, close_lexeme: str) -> Optional[int]:
        depth = 0
        for index in range(start, len(self.tokens)):
            lexeme = self.tokens[index].lexeme
            if lexeme == open_lexeme:
                depth += 1
            elif lexeme == close_lexeme:
                depth -= 1
                if depth == 0:
                    return index
        return None

    def skip_cv_after_parameters(self, index: int) -> int:
        while index < len(self.tokens) and self.tokens[index].lexeme in {"const", "noexcept"}:
            index += 1
        return index

    def skip_optional_declarators_to_semicolon(self) -> None:
        while self.pos < len(self.tokens) and self.tokens[self.pos].lexeme != ";":
            self.pos += 1
        if self.pos < len(self.tokens):
            self.pos += 1

    def skip_until_top_level(self, lexeme: str) -> None:
        while self.pos < len(self.tokens) and self.tokens[self.pos].lexeme != lexeme:
            self.pos += 1
        if self.pos < len(self.tokens):
            self.pos += 1

    def looks_like_template_angle(self, index: int) -> bool:
        if index == 0 or index + 1 >= len(self.tokens):
            return False
        previous = self.tokens[index - 1]
        next_token = self.tokens[index + 1]
        return previous.kind in {"identifier", "keyword"} and next_token.lexeme not in {"=", ";"}

    def current_lexeme(self) -> str:
        if self.pos >= len(self.tokens):
            return ""
        return self.tokens[self.pos].lexeme

    def current_kind(self) -> str:
        if self.pos >= len(self.tokens):
            return ""
        return self.tokens[self.pos].kind

    def peek_lexeme(self, distance: int) -> str:
        index = self.pos + distance
        if index >= len(self.tokens):
            return ""
        return self.tokens[index].lexeme


class CspStatementParser:
    TYPE_STARTERS = {
        "auto",
        "bool",
        "char",
        "const",
        "double",
        "float",
        "int",
        "long",
        "short",
        "signed",
        "string",
        "unsigned",
    } | CONTAINER_NAMES

    def __init__(self, tokens: Sequence[CppToken], block_line: int):
        self.tokens = list(tokens)
        self.block_line = block_line
        self.pos = 0

    def parse_block(self) -> CspBlock:
        statements: List[CspStatement] = []
        while self.pos < len(self.tokens):
            if self.current_lexeme() == ";":
                self.pos += 1
                continue
            statements.append(self.parse_statement())
        return CspBlock(line=self.block_line, statements=statements)

    def parse_statement(self) -> CspStatement:
        token = self.current()
        lexeme = token.lexeme
        if lexeme == "{":
            return self.parse_compound()
        if lexeme == "if":
            return self.parse_if()
        if lexeme == "while":
            return self.parse_while()
        if lexeme == "for":
            return self.parse_for()
        if lexeme == "do":
            return self.parse_do_while()
        if lexeme == "return":
            return self.parse_until_semicolon("ReturnStmt")
        if lexeme == "break":
            return self.parse_until_semicolon("BreakStmt")
        if lexeme == "continue":
            return self.parse_until_semicolon("ContinueStmt")
        if self.is_iostream_start("cin", ">>"):
            return self.parse_until_semicolon("InputStmt")
        if self.is_iostream_start("cout", "<<"):
            return self.parse_until_semicolon("OutputStmt")
        if self.looks_like_declaration():
            return self.parse_until_semicolon("DeclStmt")
        return self.parse_until_semicolon("ExprStmt")

    def parse_compound(self) -> CspStatement:
        start = self.pos
        end = self.matching_index(start, "{", "}")
        if end is None:
            raise CspFrontendError("Line %d: unclosed compound statement" % self.tokens[start].line)
        inner = CspStatementParser(self.tokens[start + 1 : end], self.tokens[start].line).parse_block()
        self.pos = end + 1
        return CspStatement(
            kind="CompoundStmt",
            line=self.tokens[start].line,
            tokens=self.lexemes(start, end + 1),
            children=inner.statements,
        )

    def parse_if(self) -> CspStatement:
        start = self.pos
        self.pos += 1
        condition = self.consume_parenthesized_tokens()
        children: List[CspStatement] = []
        if self.pos < len(self.tokens):
            children.append(self.parse_statement())
        if self.current_lexeme() == "else":
            self.pos += 1
            if self.pos < len(self.tokens):
                children.append(self.parse_statement())
        return CspStatement(
            kind="IfStmt",
            line=self.tokens[start].line,
            tokens=["if"] + condition,
            children=children,
        )

    def parse_while(self) -> CspStatement:
        start = self.pos
        self.pos += 1
        condition = self.consume_parenthesized_tokens()
        children = [self.parse_statement()] if self.pos < len(self.tokens) else []
        return CspStatement(
            kind="WhileStmt",
            line=self.tokens[start].line,
            tokens=["while"] + condition,
            children=children,
        )

    def parse_for(self) -> CspStatement:
        start = self.pos
        self.pos += 1
        header = self.consume_parenthesized_tokens()
        children = [self.parse_statement()] if self.pos < len(self.tokens) else []
        kind = "RangeForStmt" if self.has_top_level_colon(header) else "ForStmt"
        return CspStatement(
            kind=kind,
            line=self.tokens[start].line,
            tokens=["for"] + header,
            children=children,
        )

    def parse_do_while(self) -> CspStatement:
        start = self.pos
        self.pos += 1
        children = [self.parse_statement()] if self.pos < len(self.tokens) else []
        trailer: List[str] = []
        if self.current_lexeme() == "while":
            trailer.append("while")
            self.pos += 1
            trailer.extend(self.consume_parenthesized_tokens())
        if self.current_lexeme() == ";":
            trailer.append(";")
            self.pos += 1
        return CspStatement(
            kind="DoWhileStmt",
            line=self.tokens[start].line,
            tokens=["do"] + trailer,
            children=children,
        )

    def parse_until_semicolon(self, kind: str) -> CspStatement:
        start = self.pos
        end = self.find_statement_end(start)
        if end is None:
            end = len(self.tokens) - 1
            self.pos = len(self.tokens)
        else:
            self.pos = end + 1
        return CspStatement(
            kind=kind,
            line=self.tokens[start].line,
            tokens=self.lexemes(start, end + 1),
        )

    def consume_parenthesized_tokens(self) -> List[str]:
        if self.current_lexeme() != "(":
            return []
        start = self.pos
        end = self.matching_index(start, "(", ")")
        if end is None:
            raise CspFrontendError("Line %d: unclosed parenthesized header" % self.tokens[start].line)
        self.pos = end + 1
        return self.lexemes(start, end + 1)

    def looks_like_declaration(self) -> bool:
        lexeme = self.current_lexeme()
        if lexeme in self.TYPE_STARTERS:
            return True
        token = self.current()
        if token.kind != "identifier":
            return False
        next_lexeme = self.peek_lexeme(1)
        next_kind = self.peek_kind(1)
        if next_kind == "identifier":
            return True
        return next_lexeme in {"*", "&", "<", "::"}

    def is_iostream_start(self, stream_name: str, operator: str) -> bool:
        if self.current_lexeme() == stream_name and self.peek_lexeme(1) == operator:
            return True
        return (
            self.current_lexeme() == "std"
            and self.peek_lexeme(1) == "::"
            and self.peek_lexeme(2) == stream_name
            and self.peek_lexeme(3) == operator
        )

    def has_top_level_colon(self, lexemes: Sequence[str]) -> bool:
        depth = {"(": 0, "[": 0, "{": 0, "<": 0}
        for lexeme in lexemes:
            if lexeme == "(":
                depth["("] += 1
            elif lexeme == ")" and depth["("] > 0:
                depth["("] -= 1
            elif lexeme == "[":
                depth["["] += 1
            elif lexeme == "]" and depth["["] > 0:
                depth["["] -= 1
            elif lexeme == "{":
                depth["{"] += 1
            elif lexeme == "}" and depth["{"] > 0:
                depth["{"] -= 1
            elif lexeme == "<":
                depth["<"] += 1
            elif lexeme == ">" and depth["<"] > 0:
                depth["<"] -= 1
            elif lexeme == ":" and depth == {"(": 1, "[": 0, "{": 0, "<": 0}:
                return True
        return False

    def find_statement_end(self, start: int) -> Optional[int]:
        depth = {"(": 0, "[": 0, "{": 0}
        for index in range(start, len(self.tokens)):
            lexeme = self.tokens[index].lexeme
            if all(value == 0 for value in depth.values()) and lexeme == ";":
                return index
            if lexeme == "(":
                depth["("] += 1
            elif lexeme == ")" and depth["("] > 0:
                depth["("] -= 1
            elif lexeme == "[":
                depth["["] += 1
            elif lexeme == "]" and depth["["] > 0:
                depth["["] -= 1
            elif lexeme == "{":
                depth["{"] += 1
            elif lexeme == "}" and depth["{"] > 0:
                depth["{"] -= 1
        return None

    def matching_index(self, start: int, open_lexeme: str, close_lexeme: str) -> Optional[int]:
        depth = 0
        for index in range(start, len(self.tokens)):
            lexeme = self.tokens[index].lexeme
            if lexeme == open_lexeme:
                depth += 1
            elif lexeme == close_lexeme:
                depth -= 1
                if depth == 0:
                    return index
        return None

    def lexemes(self, start: int, end: int) -> List[str]:
        return [token.lexeme for token in self.tokens[start:end]]

    def current(self) -> CppToken:
        return self.tokens[self.pos]

    def current_lexeme(self) -> str:
        if self.pos >= len(self.tokens):
            return ""
        return self.tokens[self.pos].lexeme

    def peek_lexeme(self, distance: int) -> str:
        index = self.pos + distance
        if index >= len(self.tokens):
            return ""
        return self.tokens[index].lexeme

    def peek_kind(self, distance: int) -> str:
        index = self.pos + distance
        if index >= len(self.tokens):
            return ""
        return self.tokens[index].kind
