"""命令行编译入口。

这个文件只负责把完整编译流水线串起来：
源码文件 -> 词法分析 -> 语法分析 -> 语义分析 -> 汇编生成 -> 写出 .s 文件。

真正的词法/语法逻辑在 intermediate.py，语义检查在 semantic.py，汇编生成在 codegen.py。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codegen import CodegenError, generate_assembly
from intermediate import Lexer, Parser, ParserError
from semantic import SemanticAnalyzer


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令行参数。

    当前版本只支持 `-S`，即“生成汇编文件”。链接成 exe 的步骤交给 GCC/MinGW。
    """
    parser = argparse.ArgumentParser(
        prog="mycompiler.py",
        description="Compile a small C subset source file to Windows x86-64 assembly.",
    )
    parser.add_argument("source", help="source .c/.txt file")
    parser.add_argument("-S", action="store_true", help="emit assembly")
    parser.add_argument("-o", dest="output", help="output assembly path")
    return parser.parse_args(argv)


def default_output_path(source_path: Path) -> Path:
    """没有显式 `-o` 时，把输入文件后缀替换为 `.s`。"""
    return source_path.with_suffix(".s")


def read_source_text(source_path: Path) -> str:
    """读取源码文本。

    测试文件可能含中文注释且编码不统一，所以先尝试 UTF-8 BOM，再退回 GBK。
    """
    try:
        return source_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return source_path.read_text(encoding="gbk")


def compile_source(source_text: str) -> str:
    """把源码字符串编译成汇编字符串。

    这个函数是最核心的编译流水线。每一步都只在上一阶段成功后继续：
    1. Lexer 产生 token；
    2. Parser 产生 AST；
    3. SemanticAnalyzer 做语义检查；
    4. generate_assembly 生成最终汇编。
    """
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
    """统一包装编译阶段错误，方便命令行入口打印。"""
    pass


def main(argv: list[str] | None = None) -> int:
    """命令行入口，负责文件 I/O 和错误码。"""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.S:
        print("error: only -S assembly output is supported in v1", file=sys.stderr)
        return 2

    source_path = Path(args.source)
    output_path = Path(args.output) if args.output else default_output_path(source_path)

    try:
        source_text = read_source_text(source_path)
    except OSError as exc:
        print("error: cannot read %s: %s" % (source_path, exc), file=sys.stderr)
        return 1
    except UnicodeDecodeError as exc:
        print("error: cannot decode %s: %s" % (source_path, exc), file=sys.stderr)
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
