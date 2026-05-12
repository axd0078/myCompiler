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
    return CspTranslationUnit(path=path, preprocessed=preprocessed, tokens=tokens, features=features)
