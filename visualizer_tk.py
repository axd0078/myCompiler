"""Tkinter 桌面版编译过程可视化工具。

复用编译器现有阶段函数，在左侧展示源码，
右侧按按钮展示 token、AST、语义分析结果、四元式和最终汇编。
"""

from __future__ import annotations

import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Dict, List, Tuple

from codegen import CodegenError, generate_assembly
from intermediate import ASTNode, IntermediateCodeGenerator, Lexer, Parser, ParserError, Token
from semantic import AnalysisResult, SemanticAnalyzer


ROOT_DIR = Path(__file__).resolve().parent
TEST_DIR = ROOT_DIR / "test"
BUILD_DIR = ROOT_DIR / "build"
DEFAULT_FILENAME = "custom.txt"


class StageFailure(Exception):
    """可视化阶段执行失败，用于把错误文本显示到右侧结果框。"""
    pass


def read_source_text(path: Path) -> str:
    """读取测试源码，兼容 UTF-8 BOM 和 GBK 中文注释。"""
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="gbk")


def tokenize_source(source: str) -> List[Token]:
    """执行词法分析；有错误时抛出 StageFailure。"""
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    if lexer.errors:
        raise StageFailure("词法分析失败：\n" + "\n".join(lexer.errors))
    return tokens


def parse_source(source: str) -> Tuple[List[Token], ASTNode]:
    """执行词法 + 语法分析，返回 token 和 AST。"""
    tokens = tokenize_source(source)
    try:
        ast = Parser(tokens).parse()
    except ParserError as exc:
        raise StageFailure("语法分析失败：\n%s" % exc) from exc
    return tokens, ast


def analyze_ast(ast: ASTNode) -> AnalysisResult:
    """执行语义分析。"""
    return SemanticAnalyzer(ast).analyze()


def ensure_semantic_ok(result: AnalysisResult) -> None:
    if result.errors:
        raise StageFailure(format_semantic_result(result))


def format_tokens(tokens: List[Token]) -> str:
    """把 token 列表排成适合界面阅读的表格文本。"""
    if not tokens:
        return "词法分析通过，但没有产生 token。\n"

    rows = ["序号   Lexeme                TokenCode   Line", "----   --------------------  ---------   ----"]
    for index, token in enumerate(tokens):
        lexeme = repr(token.lexeme)
        if len(lexeme) > 20:
            lexeme = lexeme[:17] + "..."
        rows.append("%-6d %-21s %-11d %d" % (index, lexeme, token.token_code, token.line))
    return "词法分析通过：共 %d 个 token。\n\n%s\n" % (len(tokens), "\n".join(rows))


def format_ast(node: ASTNode, indent: int = 0) -> str:
    """把 AST 转成缩进树文本。"""
    parts = [node.kind]
    if node.name:
        parts.append("name=%s" % node.name)
    if node.type_name:
        parts.append("type=%s" % node.type_name)
    if node.value is not None:
        parts.append("value=%s" % repr(node.value))
    if node.line is not None:
        parts.append("line=%d" % node.line)

    line = " " * indent + " ".join(parts)
    child_lines = [format_ast(child, indent + 2) for child in node.children]
    return "\n".join([line] + child_lines)


def format_table(title: str, content: str) -> str:
    body = content.rstrip() if content.strip() else "(空)"
    return "[%s]\n%s" % (title, body)


def format_semantic_result(result: AnalysisResult) -> str:
    sections: List[str] = []
    if result.errors:
        errors = "\n".join("line %d semantic error %d" % (line, code) for line, code in result.errors)
        sections.append("[语义错误]\n%s" % errors)
    else:
        sections.append("[语义错误]\n语义分析通过：没有发现语义错误。")

    sections.append(format_table("常量表", result.const_table))
    sections.append(format_table("变量表", result.var_table))
    sections.append(format_table("函数表", result.function_table))
    return "\n\n".join(sections) + "\n"


def safe_output_path(filename: str) -> Path:
    """根据当前源码文件名计算 build/<文件名>.s 输出路径。"""
    raw_name = Path(filename or DEFAULT_FILENAME).name
    stem = Path(raw_name).stem or "custom"
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._")
    if not safe_stem:
        safe_stem = "custom"
    return BUILD_DIR / ("%s.s" % safe_stem)


def run_stage(stage: str, source: str, filename: str) -> Dict[str, Any]:
    """执行一个可视化阶段。

    stage 可取 tokens/ast/semantic/ir/assembly。assembly 阶段会额外写出 .s 文件。
    """
    output_path = safe_output_path(filename)

    if stage == "tokens":
        tokens = tokenize_source(source)
        return {"status": "OK", "output": format_tokens(tokens)}

    if stage == "ast":
        _, ast = parse_source(source)
        return {"status": "OK", "output": "语法分析通过，AST 如下：\n\n%s\n" % format_ast(ast)}

    if stage == "semantic":
        _, ast = parse_source(source)
        result = analyze_ast(ast)
        status = "ERROR" if result.errors else "OK"
        return {"status": status, "output": format_semantic_result(result)}

    if stage == "ir":
        _, ast = parse_source(source)
        result = analyze_ast(ast)
        ensure_semantic_ok(result)
        ir = IntermediateCodeGenerator().generate(ast)
        if not ir.strip():
            ir = "(没有生成四元式)\n"
        output = (
            "辅助学习用四元式中间表示。\n"
            "说明：当前最终汇编由 codegen.py 直接基于 AST 生成，四元式用于观察中间过程。\n\n"
            + ir
        )
        return {"status": "OK", "output": output}

    if stage == "assembly":
        _, ast = parse_source(source)
        result = analyze_ast(ast)
        ensure_semantic_ok(result)
        try:
            assembly = generate_assembly(ast)
        except CodegenError as exc:
            raise StageFailure("汇编生成失败：\n%s" % exc) from exc

        BUILD_DIR.mkdir(exist_ok=True)
        output_path.write_text(assembly, encoding="utf-8")
        return {
            "status": "OK",
            "output": assembly,
            "output_path": str(output_path.relative_to(ROOT_DIR)),
        }

    raise StageFailure("未知阶段：%s" % stage)


DEFAULT_SOURCE = """int main() {
    int a = read();
    write(a + 1);
}
"""


class CompilerVisualizerApp(tk.Tk):
    """Tkinter 主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.title("编译过程可视化")
        self.geometry("1280x760")
        self.minsize(980, 600)

        self.sample_names: List[str] = []
        self.buttons: List[ttk.Button] = []

        self.configure(bg="#f6f7f9")
        self.create_widgets()
        self.load_samples()

    def create_widgets(self) -> None:
        """创建整体左右布局。"""
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        title_row = ttk.Frame(root)
        title_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(
            title_row,
            text="编译过程可视化",
            font=("Microsoft YaHei UI", 15, "bold"),
        ).pack(side=tk.LEFT)
        ttk.Label(
            title_row,
            text="源码 -> Token -> AST -> 语义 -> 四元式 -> 汇编",
            foreground="#667085",
        ).pack(side=tk.RIGHT)

        paned = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned, padding=(0, 0, 8, 0))
        right = ttk.Frame(paned, padding=(8, 0, 0, 0))
        paned.add(left, weight=1)
        paned.add(right, weight=1)

        self.create_source_panel(left)
        self.create_result_panel(right)

    def create_source_panel(self, parent: ttk.Frame) -> None:
        """创建左侧源码编辑区。"""
        controls = ttk.Frame(parent)
        controls.pack(fill=tk.X, pady=(0, 8))
        controls.configure(height=36)
        controls.pack_propagate(False)

        ttk.Label(controls, text="样例").pack(side=tk.LEFT, padx=(0, 6))
        self.sample_box = ttk.Combobox(controls, state="readonly", width=16)
        self.sample_box.pack(side=tk.LEFT, padx=(0, 12))
        self.sample_box.bind("<<ComboboxSelected>>", self.on_sample_selected)

        ttk.Label(controls, text="文件名").pack(side=tk.LEFT, padx=(0, 6))
        self.filename_var = tk.StringVar(value=DEFAULT_FILENAME)
        ttk.Entry(controls, textvariable=self.filename_var, width=22).pack(side=tk.LEFT)

        self.source_text = ScrolledText(
            parent,
            wrap=tk.NONE,
            undo=True,
            font=("Consolas", 11),
            background="#0f172a",
            foreground="#e5e7eb",
            insertbackground="#e5e7eb",
            borderwidth=0,
            padx=12,
            pady=12,
        )
        self.source_text.pack(fill=tk.BOTH, expand=True)

    def create_result_panel(self, parent: ttk.Frame) -> None:
        """创建右侧阶段按钮和输出区。"""
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, pady=(0, 8))
        top.configure(height=36)
        top.pack_propagate(False)

        actions = [
            ("1. 词法分析", "tokens"),
            ("2. 语法分析 AST", "ast"),
            ("3. 语义分析", "semantic"),
            ("4. 中间代码", "ir"),
            ("5. 生成汇编 .s", "assembly"),
        ]
        for label, stage in actions:
            button = ttk.Button(top, text=label, command=lambda s=stage: self.run_stage_async(s))
            button.pack(side=tk.LEFT, padx=(0, 6))
            self.buttons.append(button)

        clear = ttk.Button(top, text="清空结果", command=self.clear_result)
        clear.pack(side=tk.LEFT, padx=(6, 0))
        self.buttons.append(clear)

        self.stage_var = tk.StringVar(value="等待执行")
        self.status_var = tk.StringVar(value="")
        self.output_path_var = tk.StringVar(value="")

        self.result_text = ScrolledText(
            parent,
            wrap=tk.NONE,
            font=("Consolas", 10),
            background="#111827",
            foreground="#e5e7eb",
            insertbackground="#e5e7eb",
            borderwidth=0,
            padx=12,
            pady=12,
        )
        self.result_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.set_result("选择左侧源码，点击上方按钮查看每个编译阶段的文本结果。")

    def load_samples(self) -> None:
        """扫描 test/*.txt 并默认加载 test1.txt。"""
        if TEST_DIR.exists():
            self.sample_names = [path.name for path in sorted(TEST_DIR.glob("*.txt"))]
        else:
            self.sample_names = []

        self.sample_box["values"] = self.sample_names
        if self.sample_names:
            preferred = "test1.txt" if "test1.txt" in self.sample_names else self.sample_names[0]
            self.sample_box.set(preferred)
            self.load_sample(preferred)
        else:
            self.filename_var.set(DEFAULT_FILENAME)
            self.replace_source(DEFAULT_SOURCE)

    def on_sample_selected(self, _event: object) -> None:
        name = self.sample_box.get()
        if name:
            self.load_sample(name)

    def load_sample(self, filename: str) -> None:
        path = TEST_DIR / Path(filename).name
        try:
            source = read_source_text(path)
        except OSError as exc:
            self.stage_var.set("加载样例失败")
            self.status_var.set("ERROR")
            self.output_path_var.set("")
            self.set_result(str(exc))
            return

        self.filename_var.set(path.name)
        self.replace_source(source)
        self.stage_var.set("已加载 %s" % path.name)
        self.status_var.set("")
        self.output_path_var.set("")
        self.set_result("源码已加载。点击阶段按钮查看编译过程。")

    def replace_source(self, source: str) -> None:
        self.source_text.delete("1.0", tk.END)
        self.source_text.insert("1.0", source)

    def source(self) -> str:
        return self.source_text.get("1.0", tk.END).rstrip("\n")

    def filename(self) -> str:
        return self.filename_var.get().strip() or DEFAULT_FILENAME

    def clear_result(self) -> None:
        self.stage_var.set("等待执行")
        self.status_var.set("")
        self.output_path_var.set("")
        self.set_result("")

    def set_result(self, text: str) -> None:
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert("1.0", text)
        self.result_text.configure(state=tk.NORMAL)

    def set_buttons_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for button in self.buttons:
            button.configure(state=state)

    def run_stage_async(self, stage: str) -> None:
        """后台执行阶段，避免 Tkinter 界面在编译时卡住。"""
        labels = {
            "tokens": "1. 词法分析",
            "ast": "2. 语法分析 AST",
            "semantic": "3. 语义分析",
            "ir": "4. 中间代码",
            "assembly": "5. 生成汇编 .s",
        }
        self.stage_var.set(labels.get(stage, stage))
        self.status_var.set("RUNNING")
        self.output_path_var.set("")
        self.set_result("正在执行...")
        self.set_buttons_enabled(False)

        source = self.source()
        filename = self.filename()

        def work() -> None:
            try:
                result = run_stage(stage, source, filename)
            except Exception as exc:
                result = {"status": "ERROR", "output": str(exc) + "\n"}
            self.after(0, lambda: self.finish_stage(result))

        threading.Thread(target=work, daemon=True).start()

    def finish_stage(self, result: dict) -> None:
        """把后台执行结果安全更新回 Tkinter 主线程。"""
        status = str(result.get("status", "ERROR"))
        output = str(result.get("output", ""))
        output_path = str(result.get("output_path", ""))

        self.status_var.set(status)
        self.output_path_var.set(("输出: " + output_path) if output_path else "")
        self.set_result(output)
        self.set_buttons_enabled(True)


def main() -> int:
    app = CompilerVisualizerApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
