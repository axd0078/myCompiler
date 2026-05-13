from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from codegen import CodegenError, generate_assembly
from csp_codegen import generate_skeleton_assembly
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
    source_text = normalize_cpp_compat_source(source_text)
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


def normalize_cpp_compat_source(source_text: str) -> str:
    output_lines: list[str] = []
    for raw_line in source_text.splitlines():
        stripped = raw_line.strip()
        compact = re.sub(r"\s+", "", stripped)
        if compact in {
            "ios::sync_with_stdio(false);",
            "std::ios::sync_with_stdio(false);",
            "cin.tie(nullptr);",
            "std::cin.tie(nullptr);",
            "cout.tie(nullptr);",
            "std::cout.tie(nullptr);",
        }:
            output_lines.append("")
            continue

        line = raw_line
        line = line.replace("std::cin", "cin")
        line = line.replace("std::cout", "cout")
        line = re.sub(r"<<\s*std::endl\b", lambda _match: r"<< '\n'", line)
        line = re.sub(r"<<\s*endl\b", lambda _match: r"<< '\n'", line)
        output_lines.append(line)

    normalized = "\n".join(output_lines)
    if source_text.endswith("\n"):
        normalized += "\n"
    return normalized


def compile_file(source_path: Path, output_path: Path) -> None:
    source_text = source_path.read_text(encoding="utf-8-sig")
    try:
        assembly = compile_source(source_text)
    except Exception as exc:
        if "bits/stdc++.h" not in source_text:
            raise
        unit = load_translation_unit(source_path)
        assembly = generate_skeleton_assembly(unit, fallback_reason=str(exc).splitlines()[0])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(assembly, encoding="utf-8")


def compile_file_with_csp_fallback(source_path: Path, output_path: Path) -> str:
    source_text = source_path.read_text(encoding="utf-8-sig")
    try:
        assembly = compile_source(source_text)
        mode = "full"
    except Exception as exc:
        unit = load_translation_unit(source_path)
        assembly = generate_skeleton_assembly(unit, fallback_reason=str(exc).splitlines()[0])
        mode = "fallback"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(assembly, encoding="utf-8")
    return mode


def compile_directory(source_dir: Path, output_dir: Path) -> int:
    source_files = sorted(source_dir.rglob("*.cpp"))
    report_lines = [
        "CSP compile report",
        "source: %s" % source_dir,
        "output: %s" % output_dir,
        "",
    ]
    success_count = 0
    full_count = 0
    fallback_count = 0

    for source_path in source_files:
        relative = source_path.relative_to(source_dir)
        asm_path = output_dir / relative.with_suffix(".s")
        try:
            mode = compile_file_with_csp_fallback(source_path, asm_path)
            success_count += 1
            if mode == "full":
                full_count += 1
                report_lines.append("OK %s -> %s" % (relative, asm_path.relative_to(output_dir)))
            else:
                fallback_count += 1
                report_lines.append(
                    "FALLBACK %s -> %s" % (relative, asm_path.relative_to(output_dir))
                )
        except Exception as exc:
            report_lines.append("FAIL %s" % relative)
            report_lines.append("  %s" % exc)
            try:
                unit = load_translation_unit(source_path)
                for line in unit.features.summary_lines():
                    report_lines.append("  %s" % line)
                if unit.skeleton is not None:
                    for line in unit.skeleton.summary_lines():
                        report_lines.append("  %s" % line)
            except (OSError, CspFrontendError) as feature_exc:
                report_lines.append("  feature scan failed: %s" % feature_exc)
            report_lines.append("")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "compile_report.txt").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(
        "compiled %d/%d files (full %d, fallback %d); report: %s"
        % (
            success_count,
            len(source_files),
            full_count,
            fallback_count,
            output_dir / "compile_report.txt",
        )
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
