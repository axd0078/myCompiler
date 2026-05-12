from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codegen import CodegenError, generate_assembly
from intermediate import Lexer, Parser, ParserError
from semantic import SemanticAnalyzer


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mycompiler.py",
        description="Compile a small C++ subset source file to Windows x86-64 assembly.",
    )
    parser.add_argument("source", help="source .cpp file")
    parser.add_argument("-S", action="store_true", help="emit assembly")
    parser.add_argument("-o", dest="output", help="output assembly path")
    return parser.parse_args(argv)


def default_output_path(source_path: Path) -> Path:
    return source_path.with_suffix(".s")


def compile_source(source_text: str) -> str:
    lexer = Lexer(source_text)
    tokens = lexer.tokenize()
    if lexer.errors:
        raise CompileFailure("lexical errors:\n" + "\n".join(lexer.errors))

    try:
        ast = Parser(tokens).parse()
    except ParserError as exc:
        raise CompileFailure(str(exc)) from exc

    semantic_result = SemanticAnalyzer(ast).analyze()
    if semantic_result.errors:
        formatted = "\n".join(
            "line %d semantic error %d" % (line, code)
            for line, code in semantic_result.errors
        )
        raise CompileFailure("semantic errors:\n" + formatted)

    try:
        return generate_assembly(ast)
    except CodegenError as exc:
        raise CompileFailure(str(exc)) from exc


class CompileFailure(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.S:
        print("error: only -S assembly output is supported in v1", file=sys.stderr)
        return 2

    source_path = Path(args.source)
    output_path = Path(args.output) if args.output else default_output_path(source_path)

    try:
        source_text = source_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print("error: cannot read %s: %s" % (source_path, exc), file=sys.stderr)
        return 1

    try:
        assembly = compile_source(source_text)
    except CompileFailure as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1

    try:
        output_path.write_text(assembly, encoding="utf-8")
    except OSError as exc:
        print("error: cannot write %s: %s" % (output_path, exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
