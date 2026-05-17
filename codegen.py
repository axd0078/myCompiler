"""Windows x86-64 汇编代码生成器。

=============================================================================
本文件是编译器的最终阶段——代码生成（Code Generation）。
它直接遍历 Parser 生成的 AST，输出 GNU assembler (gas) 可接受的 Intel 语法汇编。

核心工作流程：
  1. collect_toplevel()  — 预扫描 AST，收集所有函数签名和全局变量
  2. emit_header()       — 输出汇编头部（外部符号声明、格式字符串）
  3. emit_globals()      — 输出 .data 段中的全局变量
  4. emit_text()         — 遍历每个函数定义，生成对应的机器指令

目标平台：Windows x86-64 (x64)
调用约定：Microsoft x64 calling convention
  - 前 4 个整数参数通过寄存器传递：rcx, rdx, r8, r9
  - 超过 4 个的参数放在栈上（调用者栈帧中 rsp+32 开始的位置）
  - 返回值放在 eax / rax 中
  - 调用者需要预留 32 字节的 shadow space

表达式求值约定：所有表达式的结果统一放在 eax 寄存器中。
这使得表达式可以自由组合——上层直接使用 eax 中的结果即可。
=============================================================================
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


# === 类型支持常量 =============================================================

# 变量值类型：当前后端只支持 int 和 char（float/double 词法能识别但后端不支持）
SUPPORTED_VALUE_TYPES = {"int", "char"}
# 函数返回类型：比变量类型多了 void
SUPPORTED_RETURN_TYPES = {"int", "char", "void"}

# === 比较运算符 → x86 条件置位指令映射 ==========================================
# 比较表达式的结果是 0（假）或 1（真），存放在 eax 中。
# 生成方式是：先 cmp 两个操作数，再用 setCC 根据标志位把 al 置为 0 或 1，
# 最后 movzx 把 al 零扩展到 eax。
RELATIONAL_JUMPS = {
    "==": "sete",   # equal → 等于
    "!=": "setne",  # not equal → 不等于
    "<": "setl",    # less → 有符号小于
    "<=": "setle",  # less or equal → 有符号小于等于
    ">": "setg",    # greater → 有符号大于
    ">=": "setge",  # greater or equal → 有符号大于等于
}

# === Windows x64 调用约定——参数寄存器 ==========================================
# 64 位传参（地址/指针用）
ARG_REGS_64 = ["rcx", "rdx", "r8", "r9"]
# 32 位传参（int 用）
ARG_REGS_32 = ["ecx", "edx", "r8d", "r9d"]
# 8 位传参（char 用）
ARG_REGS_8 = ["cl", "dl", "r8b", "r9b"]

# === 整数字面量正则 ===========================================================
# 支持十进制（123）、十六进制（0x1A）、八进制（0777）、带符号（+1、-5）
INT_LITERAL_RE = re.compile(r"[+-]?(?:0|[1-9]\d*|0[xX][0-9A-Fa-f]+|0[0-7]+)")


class CodegenError(Exception):
    """汇编生成阶段错误，携带可选的源码行号用于定位。

    当后端遇到不支持的特性或内部错误时抛出此异常。
    mycompiler.py 会捕获它并统一格式化为命令行错误输出。
    """

    def __init__(self, message: str, line: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.line = line

    def __str__(self) -> str:
        """有行号时格式化为 'Line N: message'，否则只输出消息。"""
        if self.line is None:
            return self.message
        return "Line %d: %s" % (self.line, self.message)


@dataclass
class FunctionInfo:
    """后端收集到的函数签名信息。

    在预扫描阶段 (collect_toplevel) 中收集，用于：
    1. 调用前确认函数是否已声明。
    2. 获取返回类型和参数类型以生成正确的调用代码。
    3. 区分"只声明未定义"和"已定义"。

    defined 字段的作用：C 允许先声明后定义。如果只有声明没有定义，
    则代码生成阶段跳过（不输出函数体）。如果有多次定义，以最后一次为准。
    """

    name: str               # 函数名
    return_type: str        # 返回类型，如 "int"、"void"
    param_types: List[str]  # 参数类型列表，如 ["int", "char"]
    defined: bool           # 是否有函数体（区分声明和定义）


@dataclass
class VariableInfo:
    """后端变量布局信息。

    每个变量在栈帧或数据段中都有一个存储位置：

    局部变量 + 参数：
      - 存放在函数栈帧中 [rbp - offset]
      - 每个变量分配 8 字节槽位（即使 int 只用 4 字节，简化对齐）
      - offset 由 prepare_frame() 按声明顺序从 8 开始递增分配

    全局变量：
      - 存放在 .data 段中，使用标签 (global_label) 寻址
      - 通过 RIP 相对寻址访问，如 .Lglob_a[rip]

    is_const 标志的影响：
      - 常量变量不能被赋值（emo_variable 中的 store_eax 会报错）
    """

    name: str                       # 变量名
    type_name: str                  # 类型："int" 或 "char"
    line: int                       # 声明行号
    offset: Optional[int] = None    # 局部变量：相对 rbp 的偏移（如 8, 16, 24...）
    global_label: Optional[str] = None  # 全局变量：.data 段标签
    is_const: bool = False          # 是否 const 声明

    @property
    def is_global(self) -> bool:
        """有全局标签说明在 .data 段，否则在栈帧中。"""
        return self.global_label is not None


@dataclass
class LoopLabels:
    """循环的 break 和 continue 跳转目标标签。

    每进入一层循环，就在 frame.loops 栈顶压入此结构。
    break 跳到循环出口之后，continue 跳到下一次条件判断处。

    对于不同循环类型，continue_label 指向的位置不同：
    - while:  指向条件判断开始
    - for:    指向 step 表达式（再跳回条件判断）
    - do-while: 指向条件判断
    """
    break_label: str       # break 跳到哪里（循环出口之后）
    continue_label: str    # continue 跳到哪里（下一次迭代开始）


@dataclass
class FunctionFrame:
    """单个函数的栈帧布局和代码生成状态。

    这个数据类承载了函数代码生成过程中的全部运行时状态。

    === 栈帧内存布局（从高地址到低地址）===

        [rbp+16]  ← 可能的栈上参数（第5个及以后）
        [rbp+8]   ← 返回地址（call 指令自动压入）
    rbp→[rbp]     ← 旧的 rbp（被 push rbp 保存）
        [rbp-8]   ← 第1个局部变量/参数
        [rbp-16]  ← 第2个局部变量/参数
        ...
        [rbp-N]   ← 临时槽位（表达式求值用）
        ...       ← 调用区（shadow space + 溢出参数）
    rsp→[...]

    === 栈帧组成 ===

    local_bytes  = 参数槽 + 局部变量槽 + 临时槽（8字节对齐，顺序分配）
    call_area    = 32字节 shadow space + 溢出参数空间（超过4个参数的调用用）
    frame_size   = local_bytes + call_area，对齐到 16 字节边界

    === 作用域栈 (scopes) ===

    每个 { } 复合语句块 push 一个作用域字典。声明变量时把 VariableInfo
    写入当前作用域。离开块时 pop。查找变量时从栈顶向栈底搜索，实现块级遮蔽。
    """

    name: str                                       # 函数名
    return_type: str                                # 返回类型
    return_label: str                               # 函数返回跳转标签（统一出口）
    frame_size: int = 0                             # sub rsp, frame_size 的总大小
    local_bytes: int = 0                            # 局部变量 + 参数 + 临时槽的字节数
    call_area_size: int = 32                        # 调用区的字节数（最少 32 字节 shadow space）
    temp_offsets: List[int] = field(default_factory=list)  # 临时槽的 [rbp-offset] 列表（索引即槽号）
    variables_by_node: Dict[int, VariableInfo] = field(default_factory=dict)  # AST 节点 id → VariableInfo
    params: List[VariableInfo] = field(default_factory=list)   # 参数列表（按声明顺序）
    label_counter: int = 0                          # 用于生成唯一标签的计数器
    scopes: List[Dict[str, VariableInfo]] = field(default_factory=list)  # 作用域栈
    loops: List[LoopLabels] = field(default_factory=list)        # 循环标签栈（嵌套 break/continue 用）
    temp_depth: int = 0                             # 当前临时槽使用深度


class AssemblyGenerator:
    """AST 到 Windows x64 汇编文本的生成器。

    这是整个后端的主类。使用方式很简单：
        assembly_text = AssemblyGenerator().generate(ast_root)

    内部流程分为三个阶段：
    1. 预扫描阶段 (collect_toplevel)
       - 不产生输出，只收集函数签名和全局变量信息
       - 因为函数调用可以出现在函数定义之前（先声明后定义），
         必须提前知道所有函数的返回类型和参数数量

    2. 数据段阶段 (emit_header + emit_globals)
       - .section .rdata：格式字符串（scanf/printf 用）
       - .data：全局变量的初始值

    3. 代码段阶段 (emit_text)
       - .text：每个函数的机器指令
       - 包括栈帧建立、参数保存、语句生成、栈帧销毁

    整个生成过程中，self.lines 是累积输出的汇编文本行列表，
    最终 join 成完整字符串。
    """

    def __init__(self) -> None:
        """初始化后端状态。

        functions:  函数名 → FunctionInfo（预扫描时填充）
        globals:    全局变量名 → VariableInfo
        global_order: 全局变量声明顺序（保证 .data 段的输出顺序）
        global_nodes: 全局变量名 → AST 节点（用于获取初始化值）
        lines:       汇编输出行缓存
        current:     当前正在生成代码的函数栈帧（非函数代码时为 None）
        """
        self.functions: Dict[str, FunctionInfo] = {}
        self.globals: Dict[str, VariableInfo] = {}
        self.global_order: List[VariableInfo] = []
        self.global_nodes: Dict[str, object] = {}
        self.lines: List[str] = []
        self.current: Optional[FunctionFrame] = None

    # =========================================================================
    # 主入口
    # =========================================================================

    def generate(self, root) -> str:
        """生成完整汇编文件文本。

        参数 root 是 parser 产出的 Program 节点。
        返回一个可以直接写入 .s 文件的完整汇编字符串（以换行结尾）。
        """
        if root.kind != "Program":
            raise CodegenError("AST root must be Program", root.line)

        # 阶段 1：预扫描——收集所有函数签名和全局变量
        self.collect_toplevel(root.children)
        # 重置输出缓冲区
        self.lines = []
        # 阶段 2：输出数据段
        self.emit_header()
        self.emit_globals()
        # 阶段 3：输出代码段
        self.emit_text(root.children)
        return "\n".join(self.lines) + "\n"

    # =========================================================================
    # 阶段 1：预扫描——收集函数签名和全局变量信息
    # =========================================================================

    def collect_toplevel(self, children: Sequence) -> None:
        """预扫描顶层节点，收集函数签名和全局变量。

        这个阶段不输出任何汇编指令，只为后续的 emit_text 和 emit_globals
        准备数据。必须在真正生成代码之前完成，因为：
        - 函数 A 可能调用在它后面定义的函数 B（需要先知道 B 的签名）
        - 全局变量需要在 .data 段统一输出
        """
        for node in children:
            if node.kind in {"FunctionDecl", "FunctionDef"}:
                self.collect_function_info(node)
            elif node.kind in {"VarDecl", "ConstDecl"}:
                self.collect_global(node)
            elif node.kind != "Empty":
                raise CodegenError("top-level statement is not supported", node.line)

    def collect_function_info(self, node) -> None:
        """收集单个函数声明/定义的签名信息。

        处理逻辑：
        - 首次遇到：记录签名和 defined 状态
        - 再次遇到（先声明后定义）：
          - 如果新节点是定义（有 body），更新 defined=True
          - 如果签名不匹配，由语义分析阶段报错（后端假设签名正确）
        """
        return_type = self.require_return_type(node.type_name or "", node.line)
        # 提取参数节点并获取类型列表
        params = [child for child in node.children if child.kind == "Param"]
        param_types = [self.require_value_type(param.type_name or "", param.line) for param in params]
        body = self.function_body(node)
        existing = self.functions.get(node.name or "")
        if existing is None:
            # 首次遇到：创建新记录
            self.functions[node.name or ""] = FunctionInfo(
                name=node.name or "",
                return_type=return_type,
                param_types=param_types,
                defined=body is not None,
            )
        elif body is not None:
            # 之前只有声明，现在有定义了
            existing.defined = True

    def collect_global(self, node) -> None:
        """收集全局变量信息。

        参数 node: VarDecl 或 ConstDecl AST 节点。
        全局变量会分配一个 .Lglob_<name> 标签，存储在 .data 段中。
        """
        type_name = self.require_value_type(node.type_name or "", node.line)
        label = ".Lglob_%s" % (node.name or "")
        variable = VariableInfo(
            name=node.name or "",
            type_name=type_name,
            line=node.line or 0,
            global_label=label,
            is_const=node.kind == "ConstDecl",
        )
        self.globals[variable.name] = variable
        self.global_order.append(variable)
        self.global_nodes[variable.name] = node

    # =========================================================================
    # 阶段 2：数据段——汇编头部与全局变量
    # =========================================================================

    def emit_header(self) -> None:
        """输出汇编头部、外部符号声明和格式字符串。

        生成内容：
        - .intel_syntax noprefix：使用 Intel 语法，寄存器不带 % 前缀
        - .extern printf / scanf：声明 C 运行时库函数（链接时解析）
        - .section .rdata：只读数据段，存放 scanf/printf 的格式字符串
        - .Lfmt_read_int / .Lfmt_write_int：内建 read()/write(expr) 用的 "%d"
        - .Lfmt_read_char / .Lfmt_write_char：char 版本格式串（已定义但未使用，
          因为语义分析阶段限制了 write 只接受 int 参数）
        """
        self.lines.extend(
            [
                ".intel_syntax noprefix",
                ".extern printf",
                ".extern scanf",
                ".section .rdata",
                ".Lfmt_read_int:",
                '    .asciz "%d"',
                ".Lfmt_read_char:",
                '    .asciz " %c"',
                ".Lfmt_write_int:",
                '    .asciz "%d"',
                ".Lfmt_write_char:",
                '    .asciz "%c"',
                "",
            ]
        )

    def emit_globals(self) -> None:
        """输出全局变量到 .data 段。

        顺序遍历 collect_global 记录的 global_order 列表，
        为每个有初始值的全局变量生成标签和数据定义。

        int 类型 → .long 4 字节
        char 类型 → .byte 1 字节（& 0xFF 取低 8 位）
        无初始化表达式 → 默认值 0
        """
        if not self.global_order:
            return
        self.lines.append(".data")
        for variable in self.global_order:
            # 计算初始值：优先从 AST 节点提取，否则默认为 0
            initializer = 0
            node = self.find_global_node(variable.name)
            if node is not None and node.children:
                initializer = self.constant_initializer_value(node.children[0], variable.type_name)
            self.lines.append("%s:" % variable.global_label)
            if variable.type_name == "char":
                self.lines.append("    .byte %d" % (initializer & 0xFF))
            else:
                self.lines.append("    .long %d" % initializer)
        self.lines.append("")

    def find_global_node(self, name: str):
        """根据变量名查找对应的全局声明 AST 节点。"""
        return self.global_nodes.get(name)

    # =========================================================================
    # 阶段 3：代码段——函数体生成
    # =========================================================================

    def emit_text(self, children: Sequence) -> None:
        """输出 .text 段并逐个生成有函数体的函数。

        只处理有函数体的 FunctionDef（包括先声明后定义的情况）。
        纯声明 (FunctionDecl) 不产生任何代码。
        """
        self.lines.append(".text")
        for node in children:
            if node.kind in {"FunctionDecl", "FunctionDef"} and self.function_body(node) is not None:
                self.emit_function(node)

    def emit_function(self, node) -> None:
        """输出单个函数的完整汇编代码。

        生成的函数结构：
            .globl function_name
            function_name:
                push rbp         ; 保存调用者的栈基址
                mov rbp, rsp     ; 建立当前函数的栈基址
                sub rsp, N       ; 分配栈帧空间
                ...              ; 保存参数、函数体
            .L_function_return:
                mov rsp, rbp     ; 释放栈帧
                pop rbp          ; 恢复调用者栈基址
                ret              ; 返回调用者

        main 函数特殊处理：如果返回类型是 int 且函数尾声之前没有 return，
        补一条 xor eax, eax（返回 0）。
        """
        frame = self.prepare_frame(node)
        previous = self.current
        self.current = frame

        # 函数开始：标签 + 序言
        self.lines.extend(
            [
                "",
                ".globl %s" % frame.name,
                "%s:" % frame.name,
                "    push rbp",           # 保存调用者的栈基址寄存器
                "    mov rbp, rsp",       # rbp = 当前栈顶，建立新栈帧基准
            ]
        )
        # 分配栈帧空间（局部变量 + 临时槽 + 调用区）
        if frame.frame_size:
            self.lines.append("    sub rsp, %d" % frame.frame_size)

        # 初始化最外层作用域，把参数加入其中
        frame.scopes.append({})
        for param in frame.params:
            frame.scopes[-1][param.name] = param
        # 把参数从寄存器/栈上保存到当前栈帧中（统一按局部变量访问）
        self.emit_param_stores(frame)
        # 生成函数体（Compound 节点）
        self.emit_compound(self.function_body(node), create_scope=False)

        # main 函数特殊处理：如果没有显式 return，补 xor eax, eax
        if frame.name == "main" and frame.return_type == "int":
            self.lines.append("    xor eax, eax")

        # 函数统一返回标签——所有 return 语句都跳转到这里
        self.lines.append("%s:" % frame.return_label)
        # 函数尾声：恢复栈帧并返回
        self.lines.extend(
            [
                "    mov rsp, rbp",       # 释放栈帧空间
                "    pop rbp",            # 恢复调用者栈基址
                "    ret",                # 返回调用者（从栈上弹出返回地址）
            ]
        )
        self.current = previous

    def prepare_frame(self, node) -> FunctionFrame:
        """计算函数栈帧布局：决定每个变量和临时槽的位置。

        这个函数不输出汇编——它只计算偏移量，填充 FunctionFrame 数据对象。

        栈帧布局计算方法：
        1. 先给每个参数分配 8 字节槽位（offset 从 8 递增）
        2. 遍历函数体中的 VarDecl/ConstDecl，给每个局部变量分配 8 字节槽位
        3. 根据表达式复杂度预留临时槽位（至少 1 个）
        4. 根据最大调用参数数预留调用区（shadow space 32 字节 + 溢出参数空间）
        5. 总大小 16 字节对齐（Windows x64 ABI 要求）
        """
        name = node.name or ""
        frame = FunctionFrame(
            name=name,
            return_type=node.type_name or "void",
            return_label=".L_%s_return" % self.sanitize_label(name),
        )
        offset = 0

        def allocate_variable(decl_node, role: str) -> VariableInfo:
            """为参数或局部声明分配一个栈槽。

            每个槽固定 8 字节——即使 int 实际只用 4 字节。
            这样布局简单，且自动满足 8 字节对齐。

            嵌套函数使用 nonlocal offset，确保所有槽位按顺序递增。
            """
            nonlocal offset
            type_name = self.require_value_type(decl_node.type_name or "", decl_node.line)
            offset += 8
            variable = VariableInfo(
                name=decl_node.name or "",
                type_name=type_name,
                line=decl_node.line or 0,
                offset=offset,
                is_const=decl_node.kind == "ConstDecl",
            )
            # 用 id(decl_node) 做键——同一个声明节点在不同阶段被访问时能找回 VariableInfo
            frame.variables_by_node[id(decl_node)] = variable
            if role == "param":
                frame.params.append(variable)
            return variable

        # 先收集所有参数的槽位
        for child in node.children:
            if child.kind == "Param":
                allocate_variable(child, "param")

        # 再递归收集函数体中的局部变量
        body = self.function_body(node)
        if body is not None:
            self.collect_local_variables(body, allocate_variable)

        # 预留临时槽——表达式求值需要暂存中间结果（如二元运算左操作数）
        # 至少保留 1 个，即使函数没有复杂表达式
        temp_count = max(self.needed_temp_slots(body), 1)
        for _ in range(temp_count):
            offset += 8
            frame.temp_offsets.append(offset)

        frame.local_bytes = offset
        # 调用区 = 32 字节 shadow space + 溢出参数空间
        # max(2, max_args) 是因为 read/write 内建调用也至少需要 2 个参数位置
        max_args = max(2, self.max_call_args(body))
        frame.call_area_size = 32 + max(0, max_args - 4) * 8
        # 总栈帧大小，16 字节对齐
        frame.frame_size = self.align16(frame.local_bytes + frame.call_area_size)
        return frame

    def collect_local_variables(self, node, allocate_variable) -> None:
        """递归遍历函数体 AST，收集所有局部变量声明。

        遇到 VarDecl 或 ConstDecl 就调用 allocate_variable 分配栈槽。
        注意：这里只收集声明节点的存在，不做初始化——初始化表达式
        在 emit_compound → emit_declaration 中处理。
        """
        if node.kind in {"VarDecl", "ConstDecl"}:
            allocate_variable(node, "local")
            return
        for child in node.children:
            self.collect_local_variables(child, allocate_variable)

    def emit_param_stores(self, frame: FunctionFrame) -> None:
        """把调用约定中的参数寄存器/栈参数保存到当前栈帧。

        Windows x64 调用约定：
        - 前 4 个整数参数：ecx/rcx, edx/rdx, r8d/r8, r9d/r9
        - 第 5 个起：放在调用者栈上 [rbp+48], [rbp+56], ...
          (48 = 返回地址8 + 旧rbp8 + shadow space32)

        把它们从原始位置移入函数自己的栈槽后，
        函数体就可以统一用 [rbp-offset] 方式访问所有参数。
        """
        for index, variable in enumerate(frame.params):
            if index < 4:
                # 前 4 个参数：从寄存器保存到栈帧
                if variable.type_name == "char":
                    self.lines.append("    mov %s, %s" % (self.byte_mem(variable), ARG_REGS_8[index]))
                else:
                    self.lines.append("    mov %s, %s" % (self.dword_mem(variable), ARG_REGS_32[index]))
                continue

            # 第 5 个及以后的参数：从调用者栈上取出再保存
            stack_offset = 48 + (index - 4) * 8
            if variable.type_name == "char":
                self.lines.append("    mov al, BYTE PTR [rbp+%d]" % stack_offset)
                self.lines.append("    mov %s, al" % self.byte_mem(variable))
            else:
                self.lines.append("    mov eax, DWORD PTR [rbp+%d]" % stack_offset)
                self.lines.append("    mov %s, eax" % self.dword_mem(variable))

    def emit_compound(self, node, create_scope: bool = True) -> None:
        """生成复合语句块 { ... } 的代码。

        create_scope=True 时，push 新的作用域字典；离开时 pop。
        函数体最外层花括号传入 create_scope=False，因为 parameters
        已经在 emit_function 中加入了最外层作用域。
        """
        frame = self.require_frame()
        if create_scope:
            frame.scopes.append({})
        for child in node.children:
            if child.kind in {"VarDecl", "ConstDecl"}:
                self.emit_declaration(child)
            else:
                self.emit_statement(child)
        if create_scope:
            frame.scopes.pop()

    def emit_declaration(self, node) -> None:
        """生成变量声明的代码。

        做两件事：
        1. 把变量名加入当前作用域（后续代码可以引用它）
        2. 如果有初始化表达式（如 int a = expr），先求值再写入变量槽
        """
        frame = self.require_frame()
        variable = frame.variables_by_node[id(node)]
        frame.scopes[-1][variable.name] = variable
        if node.children:
            # 有初始化表达式：求值 → eax → 存入变量内存
            self.emit_expression(node.children[0])
            self.store_eax(variable)

    def emit_statement(self, node) -> None:
        """按语句节点类型分派到具体代码生成逻辑。

        这是一个纯分派函数——根据 node.kind 调用对应的 emit_* 方法。
        每种语句生成的底层机制都是标签 + 条件/跳转指令的组合。
        """
        if node.kind == "Compound":
            self.emit_compound(node, create_scope=True)
            return
        if node.kind == "ExprStmt":
            if node.children:
                self.emit_expression(node.children[0])
            return
        if node.kind == "ReturnStmt":
            if node.children:
                self.emit_expression(node.children[0])
            else:
                self.lines.append("    xor eax, eax")  # return; → 返回 0
            # 跳转到函数统一返回标签（不直接 ret，保证只有一个出口）
            self.lines.append("    jmp %s" % self.require_frame().return_label)
            return
        if node.kind == "IfStmt":
            self.emit_if(node)
            return
        if node.kind == "WhileStmt":
            self.emit_while(node)
            return
        if node.kind == "ForStmt":
            self.emit_for(node)
            return
        if node.kind == "DoWhileStmt":
            self.emit_do_while(node)
            return
        if node.kind == "BreakStmt":
            frame = self.require_frame()
            if not frame.loops:
                raise CodegenError("break is not inside a loop", node.line)
            self.lines.append("    jmp %s" % frame.loops[-1].break_label)
            return
        if node.kind == "ContinueStmt":
            frame = self.require_frame()
            if not frame.loops:
                raise CodegenError("continue is not inside a loop", node.line)
            self.lines.append("    jmp %s" % frame.loops[-1].continue_label)
            return
        if node.kind == "Empty":
            return
        raise CodegenError("unsupported statement '%s'" % node.kind, node.line)

    # =========================================================================
    # 控制流语句生成
    #
    # 所有控制流（if/while/for/do-while）的底层原理完全一致：
    #   高级语言的嵌套控制结构 → 扁平化为标签 + 条件/无条件跳转指令。
    #
    # 每条语句都会创建自己的 start/end/step 等标签，并用 new_label()
    # 生成唯一标签名。嵌套循环通过 frame.loops 栈管理 break/continue 跳转目标。
    # =========================================================================

    def emit_if(self, node) -> None:
        """生成 if / if-else 语句。

        AST 结构: IfStmt.children = [条件, then分支, (else分支?)]

        生成的控制流（有 else）：
            cmp eax, 0
            je  .L_else       ; 条件为假 → 跳到 else 标签
            ...then 分支...
            jmp .L_endif      ; then 执行完 → 跳到结束
        .L_else:
            ...else 分支...
        .L_endif:

        没有 else 时，je 直接跳到 .L_endif，省略中间的 .L_else 块。
        """
        else_label = self.new_label("else")
        end_label = self.new_label("endif")

        # 条件表达式求值 → eax
        self.emit_expression(node.children[0])
        # if (eax == 0) → 假分支
        self.lines.append("    cmp eax, 0")
        self.lines.append("    je %s" % else_label)

        # then 分支
        self.emit_statement(node.children[1])
        self.lines.append("    jmp %s" % end_label)

        # else 分支（可选）
        self.lines.append("%s:" % else_label)
        if len(node.children) > 2:
            self.emit_statement(node.children[2])

        self.lines.append("%s:" % end_label)

    def emit_while(self, node) -> None:
        """生成 while 循环。

        AST 结构: WhileStmt.children = [条件, 循环体]

        生成的控制流：
        .L_while_start:
            ...条件求值 → eax...
            cmp eax, 0
            je  .L_while_end    ; 条件为假 → 退出循环
            ...循环体...
            jmp .L_while_start  ; 无条件跳回，重新判断条件
        .L_while_end:

        break 跳到 .L_while_end，continue 跳到 .L_while_start。
        """
        start_label = self.new_label("while_start")
        end_label = self.new_label("while_end")
        frame = self.require_frame()

        self.lines.append("%s:" % start_label)
        # 条件判断
        self.emit_expression(node.children[0])
        self.lines.append("    cmp eax, 0")
        self.lines.append("    je %s" % end_label)

        # 压入循环标签，循环体内的 break/continue 通过栈顶找到目标
        frame.loops.append(LoopLabels(break_label=end_label, continue_label=start_label))
        self.emit_statement(node.children[1])
        frame.loops.pop()

        # 无条件跳回条件判断
        self.lines.append("    jmp %s" % start_label)
        self.lines.append("%s:" % end_label)

    def emit_for(self, node) -> None:
        """生成 for 循环。

        AST 结构: ForStmt.children = [init, condition, step, body]
        空的部分（如 for(;;)）parser 会填 Empty 节点。

        执行顺序严格遵循 C 语义：
        1. init    — 执行一次
        2. start:  — 条件判断
        3. 如果条件为假 → 跳到 end
        4. body    — 循环体
        5. step:   — step 表达式
        6. 跳到 start（重新判断条件）
        7. end:

        break 跳到 end，continue 跳到 step（然后再回到条件）。
        """
        init, condition, step, body = self.for_parts(node)

        # init 在最前面执行一次
        if init is not None:
            self.emit_expression(init)

        start_label = self.new_label("for_start")
        step_label = self.new_label("for_step")
        end_label = self.new_label("for_end")
        frame = self.require_frame()

        # 条件判断
        self.lines.append("%s:" % start_label)
        if condition is not None:
            self.emit_expression(condition)
            self.lines.append("    cmp eax, 0")
            self.lines.append("    je %s" % end_label)

        # 循环体
        frame.loops.append(LoopLabels(break_label=end_label, continue_label=step_label))
        self.emit_statement(body)
        frame.loops.pop()

        # step 表达式（continue 跳到这里）
        self.lines.append("%s:" % step_label)
        if step is not None:
            self.emit_expression(step)
        # 跳回条件判断
        self.lines.append("    jmp %s" % start_label)
        self.lines.append("%s:" % end_label)

    def emit_do_while(self, node) -> None:
        """生成 do-while 循环。

        AST 结构: DoWhileStmt.children = [循环体, 条件]

        与 while 的差异：先执行循环体再判断条件（至少执行一次）。

        生成的控制流：
        .L_do_start:
            ...循环体...
        .L_do_cond:
            ...条件求值 → eax...
            cmp eax, 0
            jne .L_do_start     ; 条件为真 → 跳回循环体开头
        .L_do_end:
        """
        start_label = self.new_label("do_start")
        cond_label = self.new_label("do_cond")
        end_label = self.new_label("do_end")
        frame = self.require_frame()

        self.lines.append("%s:" % start_label)
        frame.loops.append(LoopLabels(break_label=end_label, continue_label=cond_label))
        self.emit_statement(node.children[0])
        frame.loops.pop()

        # 条件判断——在循环体之后
        self.lines.append("%s:" % cond_label)
        self.emit_expression(node.children[1])
        self.lines.append("    cmp eax, 0")
        self.lines.append("    jne %s" % start_label)  # 注意：为真时跳回
        self.lines.append("%s:" % end_label)

    # =========================================================================
    # 表达式生成
    #
    # 所有表达式生成函数遵循一条核心约定：
    #   ** 表达式的结果统一放在 eax 寄存器中 **
    #
    # 这个约定使得表达式可以自由嵌套组合：
    #   上层表达式调用下层 → 下层把结果放入 eax
    #   上层直接从 eax 中读取结果继续运算
    #
    # 临时值存储：
    #   二元运算在计算右操作数之前，用临时栈槽 (temp_offsets) 暂存左操作数。
    #   temp_depth 表示当前使用了几个临时槽，类似一个简单的栈分配器。
    # =========================================================================

    def emit_expression(self, node) -> None:
        """表达式生成入口，结果约定放在 eax。

        按 node.kind 分派：
        - Empty → 特殊处理，xor eax, eax
        - Leaf  → 变量加载或常量立即数
        - Call  → 函数调用（包括内建 read/write）
        - Operator:
            * 1 个子节点 → 一元运算 (!, -, +)
            * 2 个子节点:
              - value="="  → 赋值（先算右边，再写入左边变量）
              - value="&&" / "||" → 逻辑短路表达式
              - 其他 → 二元算术/比较运算
        """
        if node.kind == "Empty":
            self.lines.append("    xor eax, eax")
            return
        if node.kind == "Leaf":
            self.emit_leaf(node)
            return
        if node.kind == "Call":
            self.emit_call(node)
            return
        if node.kind != "Operator":
            raise CodegenError("unsupported expression '%s'" % node.kind, node.line)

        # --- 一元运算符 (!, -, +) ---
        if len(node.children) == 1:
            self.emit_unary(node)
            return

        # --- 赋值 (=) ---
        if node.value == "=":
            target = node.children[0]
            # 赋值目标必须是单个变量名（当前语言不支持 *(ptr) = x 等复杂左值）
            if target.kind != "Leaf":
                raise CodegenError("assignment target must be a variable", node.line)
            variable = self.lookup_variable(target.value or "", target.line)
            # 先算右侧表达式（结果在 eax），再写入左侧变量的内存槽
            self.emit_expression(node.children[1])
            self.store_eax(variable)
            return

        # --- 逻辑短路 (&& / ||) ---
        if node.value in {"&&", "||"}:
            self.emit_logical(node)
            return

        # --- 二元算术/比较 ---
        self.emit_binary(node)

    def emit_leaf(self, node) -> None:
        """生成 Leaf 节点代码——变量加载或常量立即数。

        判断顺序：
        1. 字符串字面量 — 当前 v1 不支持，直接报错
        2. 字符字面量 'a' — mov eax, 97
        3. 整数字面量 123 — mov eax, 123
        4. 都不是 → 按变量名查找，从栈帧或全局段加载
        """
        text = node.value or ""
        if self.is_string_literal(text):
            raise CodegenError("string expressions are not supported in v1", node.line)
        if self.is_char_literal(text):
            self.lines.append("    mov eax, %d" % self.char_value(text))
            return
        if self.is_int_literal(text):
            self.lines.append("    mov eax, %d" % self.int_value(text))
            return
        # 变量引用：从作用域 → 栈帧偏移 或 全局标签
        variable = self.lookup_variable(text, node.line)
        self.load_variable(variable)

    def emit_unary(self, node) -> None:
        """生成一元运算符代码。

        +x: 什么也不做（结果已经在 eax 中）
        -x: neg eax — 二进制补码取负
        !x: cmp eax,0; sete al; movzx eax,al
            — 比较是否为 0，sete 把结果写入 al（0 或 1），再零扩展回 eax
        """
        self.emit_expression(node.children[0])

        if node.value == "+":
            return  # eax 不变
        if node.value == "-":
            self.lines.append("    neg eax")
            return
        if node.value == "!":
            # 逻辑非：eax == 0 ? 1 : 0
            self.lines.append("    cmp eax, 0")
            self.lines.append("    sete al")       # setCC 只操作 8 位寄存器
            self.lines.append("    movzx eax, al")  # 零扩展到 32 位
            return
        raise CodegenError("unsupported unary operator '%s'" % node.value, node.line)

    def emit_binary(self, node) -> None:
        """生成二元算术和比较运算代码。

        执行步骤（对算术运算）：
        1. 计算左操作数 → eax
        2. cdqe 符号扩展 rax
        3. 保存 rax 到临时栈槽（因为右操作数计算会覆盖 eax）
        4. 计算右操作数 → eax
        5. 把右操作数移到 r10d
        6. 从临时槽恢复左操作数到 eax
        7. 执行运算（add/sub/imul/idiv/cmp+setCC）

        比较运算（<, <=, >, >=, ==, !=）：
        用 cmp + setCC 指令，结果为 0 或 1 放入 al，再零扩展到 eax。

        除法和取模：
        idiv 是 64÷32 位有符号除法，被除数在 edx:eax 中。
        cdq 把 eax 符号扩展到 edx:eax。
        除法结果：商在 eax，余数在 edx。
        所以 % 运算需要在 idiv 后额外把 edx 移到 eax。
        """
        # 左操作数
        self.emit_expression(node.children[0])
        slot = self.reserve_temp()                        # 保留一个临时槽
        self.lines.append("    cdqe")                     # 符号扩展到 64 位
        self.lines.append("    mov QWORD PTR %s, rax" % self.temp_mem(slot))  # 暂存左值

        # 右操作数
        self.emit_expression(node.children[1])
        self.lines.append("    mov r10d, eax")            # 右值移到 r10d

        # 恢复左值
        self.lines.append("    mov eax, DWORD PTR %s" % self.temp_mem(slot))
        self.release_temp()                               # 释放临时槽

        # 根据运算符执行对应指令
        if node.value == "+":
            self.lines.append("    add eax, r10d")
        elif node.value == "-":
            self.lines.append("    sub eax, r10d")
        elif node.value == "*":
            self.lines.append("    imul eax, r10d")       # 有符号乘法
        elif node.value == "/":
            self.lines.append("    cdq")                  # eax → edx:eax
            self.lines.append("    idiv r10d")            # 有符号除法，商在 eax
        elif node.value == "%":
            self.lines.append("    cdq")
            self.lines.append("    idiv r10d")
            self.lines.append("    mov eax, edx")         # 余数在 edx，移到 eax
        elif node.value in RELATIONAL_JUMPS:
            self.lines.append("    cmp eax, r10d")
            self.lines.append("    %s al" % RELATIONAL_JUMPS[node.value])
            self.lines.append("    movzx eax, al")
        else:
            raise CodegenError("unsupported binary operator '%s'" % node.value, node.line)

    def emit_logical(self, node) -> None:
        """生成 && / || 逻辑短路表达式。

        && 的短路语义 — 左边为假则整体为假，不计算右边：
            左边求值 → cmp eax,0 → je logic_false
            右边求值 → cmp eax,0 → je logic_false
            mov eax,1; jmp end
            logic_false: xor eax,eax
            end:

        || 的短路语义 — 左边为真则整体为真，不计算右边：
            左边求值 → cmp eax,0 → jne logic_true
            右边求值 → cmp eax,0 → jne logic_true
            logic_false: xor eax,eax; jmp end
            logic_true: mov eax,1
            end:
        """
        false_label = self.new_label("logic_false")
        true_label = self.new_label("logic_true")
        end_label = self.new_label("logic_end")

        if node.value == "&&":
            # a && b：任意一个为 0 就跳到 false
            self.emit_expression(node.children[0])
            self.lines.append("    cmp eax, 0")
            self.lines.append("    je %s" % false_label)
            self.emit_expression(node.children[1])
            self.lines.append("    cmp eax, 0")
            self.lines.append("    je %s" % false_label)
            # 两个都为真 → 返回 1
            self.lines.append("%s:" % true_label)
            self.lines.append("    mov eax, 1")
            self.lines.append("    jmp %s" % end_label)
            self.lines.append("%s:" % false_label)
            self.lines.append("    xor eax, eax")
            self.lines.append("%s:" % end_label)
            return

        # a || b：任意一个非 0 就跳到 true
        self.emit_expression(node.children[0])
        self.lines.append("    cmp eax, 0")
        self.lines.append("    jne %s" % true_label)
        self.emit_expression(node.children[1])
        self.lines.append("    cmp eax, 0")
        self.lines.append("    jne %s" % true_label)
        # 两个都为假 → 返回 0
        self.lines.append("%s:" % false_label)
        self.lines.append("    xor eax, eax")
        self.lines.append("    jmp %s" % end_label)
        self.lines.append("%s:" % true_label)
        self.lines.append("    mov eax, 1")
        self.lines.append("%s:" % end_label)

    # =========================================================================
    # 函数调用生成
    # =========================================================================

    def emit_call(self, node) -> None:
        """生成函数调用代码。

        分三种情况：
        1. read() — 内建输入，调用 scanf("%d", &temp)
        2. write(expr) — 内建输出，调用 printf("%d", expr)
        3. 普通函数调用 — 遵循 Windows x64 调用约定

        === 普通函数调用流程 ===

        1. 依次计算每个实参 → eax
        2. 把每个 eaax 符号扩展到 rax，存入临时槽
           （必须全部存完再恢复，因为后面的计算会覆盖 eax）
        3. 从临时槽取回，按调用约定放置：
           - 前 4 个 → rcx, rdx, r8, r9
           - 第 5 个起 → [rsp+32], [rsp+40], ...
        4. call 函数名
        5. 返回值在 eax（调用约定规定）

        temp_depth 在这里的特殊用法：用连续的临时槽保存实参。
        从 base_depth 开始依次使用，调用完成后恢复 base_depth。
        """
        name = node.name or ""
        if name == "read":
            self.emit_builtin_read(node)
            return
        if name == "write":
            self.emit_builtin_write(node)
            return

        # 检查函数是否已声明
        info = self.functions.get(name)
        if info is None:
            raise CodegenError("function '%s' is not declared" % name, node.line)
        if info.return_type not in SUPPORTED_RETURN_TYPES:
            raise CodegenError("function return type '%s' is not supported" % info.return_type, node.line)

        frame = self.require_frame()
        base_depth = frame.temp_depth
        # 为每个实参预留临时槽
        frame.temp_depth += len(node.children)
        if frame.temp_depth > len(frame.temp_offsets):
            raise CodegenError("internal error: not enough temporary stack slots", node.line)

        # 步骤 1-2：计算每个实参并保存到临时槽
        for index, child in enumerate(node.children):
            self.emit_expression(child)
            self.lines.append("    cdqe")
            self.lines.append("    mov QWORD PTR %s, rax" % self.temp_mem(base_depth + index))

        # 步骤 3：按调用约定放置实参
        for index in range(len(node.children)):
            source = self.temp_mem(base_depth + index)
            if index < 4:
                # 前 4 个参数通过寄存器传递
                self.lines.append("    mov %s, QWORD PTR %s" % (ARG_REGS_64[index], source))
            else:
                # 溢出参数放在栈上（shadow space 之上）
                stack_offset = 32 + (index - 4) * 8
                self.lines.append("    mov rax, QWORD PTR %s" % source)
                self.lines.append("    mov QWORD PTR [rsp+%d], rax" % stack_offset)

        # 恢复 temp_depth 并生成调用指令
        frame.temp_depth = base_depth
        self.lines.append("    call %s" % name)

    def emit_builtin_read(self, node) -> None:
        """生成内建 read() 调用。

        read() 等价于 scanf("%d", &temp)，temp 是当前栈帧中的临时槽。

        生成的汇编：
            lea rdx, [rbp-offset]   ; 第二个参数 = 临时槽地址（scanf 写入目标）
            lea rcx, .Lfmt_read_int[rip]  ; 第一个参数 = "%d" 格式串
            xor eax, eax             ; varargs 约定：al = 使用的向量寄存器数量（这里为 0）
            call scanf
            mov eax, [rbp-offset]    ; 把 scanf 写入的值加载为表达式结果
        """
        if node.children:
            raise CodegenError("read expects no arguments", node.line)
        slot = self.reserve_temp()
        self.lines.append("    lea rdx, %s" % self.temp_mem(slot))       # rdx = &temp
        self.lines.append("    lea rcx, .Lfmt_read_int[rip]")           # rcx = "%d"
        self.lines.append("    xor eax, eax")                           # 没有浮点参数
        self.lines.append("    call scanf")
        self.lines.append("    mov eax, DWORD PTR %s" % self.temp_mem(slot))  # 结果加载到 eax
        self.release_temp()

    def emit_builtin_write(self, node) -> None:
        """生成内建 write(expr) 调用。

        write(expr) 等价于 printf("%d", expr)。

        生成的汇编：
            计算 expr → eax
            mov edx, eax            ; 第二个参数 = 要输出的值
            lea rcx, .Lfmt_write_int[rip]  ; 第一个参数 = "%d" 格式串
            xor eax, eax            ; 没有浮点参数
            call printf
        """
        if len(node.children) != 1:
            raise CodegenError("write expects one argument", node.line)
        type_name = self.expression_type(node.children[0])
        if type_name != "int":
            raise CodegenError("write supports only int expressions", node.children[0].line or node.line)
        self.emit_expression(node.children[0])
        self.lines.append("    mov edx, eax")                           # edx = 表达式的值
        self.lines.append("    lea rcx, .Lfmt_write_int[rip]")         # rcx = "%d"
        self.lines.append("    xor eax, eax")                           # 没有浮点参数
        self.lines.append("    call printf")

    # =========================================================================
    # 变量内存访问
    # =========================================================================

    def load_variable(self, variable: VariableInfo) -> None:
        """把变量值加载到 eax。

        int:  mov eax, DWORD PTR [rbp-offset]  （4 字节加载）
        char: movsx eax, BYTE PTR [rbp-offset] （1 字节加载 + 符号扩展）
        """
        if variable.type_name == "char":
            self.lines.append("    movsx eax, %s" % self.byte_mem(variable))
        else:
            self.lines.append("    mov eax, %s" % self.dword_mem(variable))

    def store_eax(self, variable: VariableInfo) -> None:
        """把 eax 写回变量内存位置。

        const 变量不能赋值 — 直接抛异常。
        int:  mov DWORD PTR [rbp-offset], eax
        char: mov BYTE PTR [rbp-offset], al  （只写入低 8 位）
        """
        if variable.is_const:
            raise CodegenError("cannot assign to const variable '%s'" % variable.name, variable.line)
        if variable.type_name == "char":
            self.lines.append("    mov %s, al" % self.byte_mem(variable))
        else:
            self.lines.append("    mov %s, eax" % self.dword_mem(variable))

    def load_address(self, register: str, variable: VariableInfo) -> None:
        """用 lea 把变量地址加载到指定寄存器。

        全局变量用 RIP 相对寻址，局部变量用 RBP 相对寻址。
        """
        if variable.is_global:
            self.lines.append("    lea %s, %s[rip]" % (register, variable.global_label))
        else:
            self.lines.append("    lea %s, [rbp-%d]" % (register, variable.offset or 0))

    # --- 内存操作数格式化辅助方法 ---

    def byte_mem(self, variable: VariableInfo) -> str:
        """生成 BYTE PTR 内存操作数字符串。"""
        return "BYTE PTR %s" % self.variable_address(variable)

    def dword_mem(self, variable: VariableInfo) -> str:
        """生成 DWORD PTR 内存操作数字符串。"""
        return "DWORD PTR %s" % self.variable_address(variable)

    def variable_address(self, variable: VariableInfo) -> str:
        """生成变量地址字符串（不带 PTR 限定符）。

        全局变量：.Lglob_a[rip]（RIP 相对寻址）
        局部变量：[rbp-offset]（栈帧相对寻址）
        """
        if variable.is_global:
            return "%s[rip]" % variable.global_label
        return "[rbp-%d]" % (variable.offset or 0)

    def temp_mem(self, index: int) -> str:
        """生成临时槽的内存操作数，如 [rbp-72]。"""
        frame = self.require_frame()
        return "[rbp-%d]" % frame.temp_offsets[index]

    # =========================================================================
    # 临时槽管理（简单的栈分配器）
    #
    # 表达式求值过程中需要暂存中间值。临时槽就是栈帧中预留的 [rbp-offset] 位置。
    # temp_depth 是当前使用深度——每次 reserve_temp 递增，release_temp 递减。
    # 嵌套表达式自然形成类似调用栈的分配/释放模式。
    # =========================================================================

    def reserve_temp(self) -> int:
        """分配一个临时槽，返回槽索引。

        temp_depth 递增，当前值表示"已使用几个槽"。
        """
        frame = self.require_frame()
        index = frame.temp_depth
        frame.temp_depth += 1
        if frame.temp_depth > len(frame.temp_offsets):
            raise CodegenError("internal error: expression temporaries exhausted")
        return index

    def release_temp(self) -> None:
        """释放最近分配的一个临时槽（temp_depth 递减）。"""
        frame = self.require_frame()
        frame.temp_depth -= 1

    # =========================================================================
    # 查找与类型推断
    # =========================================================================

    def lookup_variable(self, name: str, line: Optional[int]) -> VariableInfo:
        """按名称查找变量。

        查找顺序：
        1. 从当前函数的作用域栈顶向栈底搜索（先找局部变量，再找外层块）
        2. 找不到 → 搜索全局变量表
        3. 都找不到 → 抛出异常
        """
        frame = self.current
        if frame is not None:
            # 作用域栈从顶向底 = 从内层到外层
            for scope in reversed(frame.scopes):
                if name in scope:
                    return scope[name]
        if name in self.globals:
            return self.globals[name]
        raise CodegenError("variable '%s' is not declared" % name, line)

    def expression_type(self, node) -> Optional[str]:
        """静态推断表达式的类型。

        这不是语义分析——语义分析已经做过了。这里只是后端需要知道
        某些表达式的具体类型（如 write 参数必须是 int）。

        推断规则：
        - Leaf: 字面量按语法形式判断，变量查 VariableInfo.type_name
        - Call: read→int, write→void, 普通函数→FunctionInfo.return_type
        - Operator: 比较/逻辑→int, 赋值→左侧类型, 一元→子表达式类型, 其他→int
        """
        if node.kind == "Leaf":
            text = node.value or ""
            if self.is_string_literal(text):
                return "string"
            if self.is_char_literal(text):
                return "char"
            if self.is_int_literal(text):
                return "int"
            return self.lookup_variable(text, node.line).type_name
        if node.kind == "Call":
            if node.name == "read":
                return "int"
            if node.name == "write":
                return "void"
            info = self.functions.get(node.name or "")
            return info.return_type if info is not None else None
        if node.kind == "Operator":
            if node.value == "=" and node.children:
                return self.expression_type(node.children[0])
            if node.value in {"&&", "||", "!", "==", "!=", "<", "<=", ">", ">="}:
                return "int"
            if len(node.children) == 1:
                return self.expression_type(node.children[0])
            return "int"
        return None

    # =========================================================================
    # 栈帧计算辅助函数
    # =========================================================================

    def for_parts(self, node):
        """从 ForStmt 节点提取 init/condition/step/body 四部分。

        AST 中 for 的子节点顺序是 [init, cond, step, body]。
        但 parser 可能对省略的部分插入 Empty 节点（kind="Empty"），
        这里会把 Empty 转为 None 以简化调用方判断。
        """
        parts = node.children[:-1]
        body = node.children[-1]
        if len(parts) >= 3:
            init, condition, step = parts[0], parts[1], parts[2]
            return (
                None if init.kind == "Empty" else init,
                None if condition.kind == "Empty" else condition,
                None if step.kind == "Empty" else step,
                body,
            )
        init = parts[0] if len(parts) >= 1 else None
        condition = parts[1] if len(parts) >= 2 else None
        step = parts[2] if len(parts) >= 3 else None
        return init, condition, step, body

    def function_body(self, node):
        """从函数 AST 节点中提取 Compound 函数体。

        FunctionDef 的最后一个子节点如果是 Compound，就是函数体。
        FunctionDecl 没有 Compound 子节点，返回 None。
        """
        if node.children and node.children[-1].kind == "Compound":
            return node.children[-1]
        return None

    def max_call_args(self, node) -> int:
        """递归计算函数体中最大调用实参数，用于预留调用区。

        read/write 内建调用按 2 个参数计算（rcx + rdx），
        普通调用按实际参数数量计算。
        取所有调用中参数数量的最大值。
        """
        if node is None:
            return 0
        own = 0
        if node.kind == "Call":
            own = 2 if node.name in {"read", "write"} else len(node.children)
        return max([own] + [self.max_call_args(child) for child in node.children])

    def needed_temp_slots(self, node) -> int:
        """递归估计表达式求值需要的最大临时栈槽数。

        分析每种 AST 节点在最坏情况下需要的临时槽数量：
        - Leaf / Empty: 0（不需要中间存储）
        - Call: 保存所有实参需要 len(children) 个槽，再加上子表达式中的最大需求
        - read(): 1 个槽（scanf 写入目标）
        - 一元运算: 等于子表达式的需求
        - 赋值: 等于右侧表达式需求
        - 二元运算: max(左需求, 1 + 右需求) — 因为左操作数要先存起来再算右边
        - 其他节点: 子节点中需求的最大值
        """
        if node is None:
            return 0
        if node.kind in {"Leaf", "Empty"}:
            return 0
        if node.kind == "Call":
            if node.name == "read":
                return 1
            nested = [self.needed_temp_slots(child) for child in node.children]
            return len(node.children) + (max(nested) if nested else 0)
        if node.kind == "Operator":
            if len(node.children) == 1:
                return self.needed_temp_slots(node.children[0])
            if node.value == "=":
                return self.needed_temp_slots(node.children[1])
            # 二元运算：保存左操作数占 1 槽 + 右侧需求
            return max(
                self.needed_temp_slots(node.children[0]),
                1 + self.needed_temp_slots(node.children[1]),
                1,
            )
        child_needs = [self.needed_temp_slots(child) for child in node.children]
        return max(child_needs) if child_needs else 0

    # =========================================================================
    # 工具方法
    # =========================================================================

    def constant_initializer_value(self, node, type_name: str) -> int:
        """从 AST 节点提取全局变量的常量初始值。

        只接受字面量（Leaf），并且类型必须与声明类型匹配。
        """
        if node.kind != "Leaf":
            raise CodegenError("global initializer must be a literal", node.line)
        text = node.value or ""
        if type_name == "char" and self.is_char_literal(text):
            return self.char_value(text)
        if type_name == "int" and self.is_int_literal(text):
            return self.int_value(text)
        raise CodegenError("global initializer type does not match declaration", node.line)

    def require_return_type(self, type_name: str, line: Optional[int]) -> str:
        """验证函数返回类型是否被后端支持。

        void / int / char → 通过
        数组类型 / float / double → 抛异常
        """
        if type_name.endswith("[]"):
            raise CodegenError("arrays are not supported in v1", line)
        if type_name not in SUPPORTED_RETURN_TYPES:
            raise CodegenError("type '%s' is not supported by the assembly backend" % type_name, line)
        return type_name

    def require_value_type(self, type_name: str, line: Optional[int]) -> str:
        """验证变量值类型是否被后端支持。

        int / char → 通过
        数组 / void / float 等 → 抛异常
        """
        if type_name.endswith("[]"):
            raise CodegenError("arrays are not supported in v1", line)
        if type_name not in SUPPORTED_VALUE_TYPES:
            raise CodegenError("type '%s' is not supported by the assembly backend" % type_name, line)
        return type_name

    def new_label(self, hint: str) -> str:
        """生成当前函数内的唯一标签。

        格式：.L_<函数名>_<提示>_<计数器>
        如：.L_main_while_start_3

        每调用一次 label_counter 自增，保证标签不重复。
        """
        frame = self.require_frame()
        frame.label_counter += 1
        return ".L_%s_%s_%d" % (self.sanitize_label(frame.name), hint, frame.label_counter)

    def require_frame(self) -> FunctionFrame:
        """获取当前活跃的函数栈帧；没有则抛异常（表示内部错误）。"""
        if self.current is None:
            raise CodegenError("internal error: no active function")
        return self.current

    # --- 静态工具方法 ---

    @staticmethod
    def sanitize_label(name: str) -> str:
        """把函数名中的非字母数字字符替换为下划线，保证标签语法合法。"""
        return re.sub(r"\W", "_", name or "fn")

    @staticmethod
    def align16(value: int) -> int:
        """向上对齐到 16 字节边界（Windows x64 ABI 要求栈 16 字节对齐）。"""
        return (value + 15) // 16 * 16

    @staticmethod
    def is_string_literal(text: str) -> bool:
        """判断 token 文本是否为字符串字面量（以双引号包裏）。"""
        return len(text) >= 2 and text[0] == '"' and text[-1] == '"'

    @staticmethod
    def is_char_literal(text: str) -> bool:
        """判断 token 文本是否为字符字面量（以单引号包裏）。"""
        return len(text) >= 3 and text[0] == "'" and text[-1] == "'"

    @staticmethod
    def is_int_literal(text: str) -> bool:
        """判断 token 文本是否为合法整数字面量。"""
        return INT_LITERAL_RE.fullmatch(text or "") is not None

    @staticmethod
    def int_value(text: str) -> int:
        """把整数字面量文本转为 Python int。

        支持十进制、十六进制（0x）、八进制（以 0 开头）。
        八进制需要特殊处理：Python 的 int("0777", 0) 会按十进制解析，
        所以先用正则检测八进制格式再手动转换。
        """
        if re.fullmatch(r"[+-]?0[0-7]+", text or ""):
            sign = -1 if text.startswith("-") else 1
            digits = text[1:] if text[0] in "+-" else text
            return sign * int(digits, 8)
        return int(text, 0)

    @staticmethod
    def char_value(text: str) -> int:
        """把字符字面量文本转为 ASCII / 转义字符对应的整数。

        支持转义序列：\\n, \\t, \\r, \\0, \\\\, \\', \\"
        普通字符取 ord() 值。
        """
        body = text[1:-1]  # 去掉首尾的单引号
        escapes = {
            "n": 10,
            "t": 9,
            "r": 13,
            "0": 0,
            "\\": 92,
            "'": 39,
            '"': 34,
        }
        if body.startswith("\\"):
            key = body[1:]
            if key in escapes:
                return escapes[key]
            raise CodegenError("unsupported character escape '\\%s'" % key)
        if len(body) != 1:
            raise CodegenError("character literal must contain one character")
        return ord(body)


# =============================================================================
# 公开入口函数
# =============================================================================

def generate_assembly(root) -> str:
    """公开入口：AST → 汇编文本。

    这是 codegen.py 对外暴露的唯一函数。
    用法：assembly_text = generate_assembly(ast_root)
    """
    return AssemblyGenerator().generate(root)
