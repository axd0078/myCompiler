from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codegen import CodegenError, generate_assembly
from csp_frontend import CspFrontendError, load_translation_unit
from intermediate import Lexer, Parser, ParserError
from semantic import SemanticAnalyzer


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mycompiler.py",
        description="Compile a small C++ subset source file to Windows x86-64 assembly.",
    )
    parser.add_argument("source", nargs="?", help="source .cpp file")
    parser.add_argument("-S", action="store_true", help="emit assembly")
    parser.add_argument("-o", dest="output", help="output assembly path")
    parser.add_argument("--compile-dir", help="compile every .cpp file under a directory")
    parser.add_argument("--out-dir", help="output directory for --compile-dir")
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


def compile_file(source_path: Path, output_path: Path) -> None:
    source_text = source_path.read_text(encoding="utf-8-sig")
    assembly = compile_source(source_text)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(assembly, encoding="utf-8")


def compile_directory(source_dir: Path, output_dir: Path) -> int:
    source_files = sorted(source_dir.rglob("*.cpp"))
    report_lines = [
        "CSP compile report",
        "source: %s" % source_dir,
        "output: %s" % output_dir,
        "",
    ]
    success_count = 0

    for source_path in source_files:
        relative = source_path.relative_to(source_dir)
        asm_path = output_dir / relative.with_suffix(".s")
        try:
            compile_file(source_path, asm_path)
            success_count += 1
            report_lines.append("OK %s -> %s" % (relative, asm_path.relative_to(output_dir)))
        except Exception as exc:
            report_lines.append("FAIL %s" % relative)
            report_lines.append("  %s" % exc)
            try:
                unit = load_translation_unit(source_path)
                for line in unit.features.summary_lines():
                    report_lines.append("  %s" % line)
            except (OSError, CspFrontendError) as feature_exc:
                report_lines.append("  feature scan failed: %s" % feature_exc)
            report_lines.append("")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "compile_report.txt").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(
        "compiled %d/%d files; report: %s"
        % (success_count, len(source_files), output_dir / "compile_report.txt")
    )
    return 0 if success_count == len(source_files) else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.S:
        print("error: only -S assembly output is supported in v1", file=sys.stderr)
        return 2

    if args.compile_dir:
        source_dir = Path(args.compile_dir)
        output_dir = Path(args.out_dir) if args.out_dir else Path("build") / "csp-asm"
        return compile_directory(source_dir, output_dir)

    if not args.source:
        print("error: source file is required unless --compile-dir is used", file=sys.stderr)
        return 2

    source_path = Path(args.source)
    output_path = Path(args.output) if args.output else default_output_path(source_path)

    try:
        compile_file(source_path, output_path)
    except OSError as exc:
        print("error: cannot access %s: %s" % (source_path, exc), file=sys.stderr)
        return 1
    except CompileFailure as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
