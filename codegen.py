from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


REAL_TYPES = {"float", "double"}
SUPPORTED_VALUE_TYPES = {"int", "char", "long long", "unsigned long long", "bool", "float", "double"}
SUPPORTED_RETURN_TYPES = {"int", "char", "long long", "unsigned long long", "bool", "float", "double", "void"}
BUILTIN_FUNCTIONS = {"abs", "llabs", "min", "max"}
RELATIONAL_JUMPS = {
    "==": "sete",
    "!=": "setne",
    "<": "setl",
    "<=": "setle",
    ">": "setg",
    ">=": "setge",
}
ARG_REGS_64 = ["rcx", "rdx", "r8", "r9"]
ARG_REGS_32 = ["ecx", "edx", "r8d", "r9d"]
ARG_REGS_8 = ["cl", "dl", "r8b", "r9b"]
INT_LITERAL_RE = re.compile(
    r"[+-]?(?:0|[1-9]\d*|0[xX][0-9A-Fa-f]+|0[0-7]+)(?:[uU]?[lL]{1,2}|[lL]{1,2}[uU]?)?"
)
FLOAT_LITERAL_RE = re.compile(r"[+-]?(?:(?:\d+\.\d*|\d*\.\d+)(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)")


class CodegenError(Exception):
    def __init__(self, message: str, line: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.line = line

    def __str__(self) -> str:
        if self.line is None:
            return self.message
        return "Line %d: %s" % (self.line, self.message)


@dataclass
class FunctionInfo:
    name: str
    return_type: str
    param_types: List[str]
    defined: bool


@dataclass
class VariableInfo:
    name: str
    type_name: str
    line: int
    offset: Optional[int] = None
    global_label: Optional[str] = None
    is_const: bool = False

    @property
    def is_global(self) -> bool:
        return self.global_label is not None


@dataclass
class LoopLabels:
    break_label: str
    continue_label: str


@dataclass
class FunctionFrame:
    name: str
    return_type: str
    return_label: str
    frame_size: int = 0
    local_bytes: int = 0
    call_area_size: int = 32
    temp_offsets: List[int] = field(default_factory=list)
    variables_by_node: Dict[int, VariableInfo] = field(default_factory=dict)
    params: List[VariableInfo] = field(default_factory=list)
    label_counter: int = 0
    scopes: List[Dict[str, VariableInfo]] = field(default_factory=list)
    loops: List[LoopLabels] = field(default_factory=list)
    temp_depth: int = 0


class AssemblyGenerator:
    def __init__(self) -> None:
        self.functions: Dict[str, FunctionInfo] = {}
        self.globals: Dict[str, VariableInfo] = {}
        self.global_order: List[VariableInfo] = []
        self.global_nodes: Dict[str, object] = {}
        self.string_literals: Dict[str, str] = {}
        self.real_literals: Dict[str, str] = {}
        self.lines: List[str] = []
        self.current: Optional[FunctionFrame] = None

    def generate(self, root) -> str:
        if root.kind != "Program":
            raise CodegenError("AST root must be Program", root.line)

        self.collect_toplevel(root.children)
        self.collect_string_literals(root)
        self.collect_real_literals(root)
        self.lines = []
        self.emit_header()
        self.emit_globals()
        self.emit_text(root.children)
        return "\n".join(self.lines) + "\n"

    def collect_toplevel(self, children: Sequence) -> None:
        for node in children:
            if node.kind in {"FunctionDecl", "FunctionDef"}:
                self.collect_function_info(node)
            elif node.kind in {"VarDecl", "ConstDecl"}:
                self.collect_global(node)
            elif node.kind != "Empty":
                raise CodegenError("top-level statement is not supported", node.line)

    def collect_function_info(self, node) -> None:
        return_type = self.require_return_type(node.type_name or "", node.line)
        params = [child for child in node.children if child.kind == "Param"]
        param_types = [self.require_value_type(param.type_name or "", param.line) for param in params]
        body = self.function_body(node)
        existing = self.functions.get(node.name or "")
        if existing is None:
            self.functions[node.name or ""] = FunctionInfo(
                name=node.name or "",
                return_type=return_type,
                param_types=param_types,
                defined=body is not None,
            )
        elif body is not None:
            existing.defined = True

    def collect_global(self, node) -> None:
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

    def emit_header(self) -> None:
        self.lines.extend(
            [
                ".intel_syntax noprefix",
                ".extern printf",
                ".extern scanf",
                ".section .rdata",
                ".Lfmt_read_int:",
                '    .asciz "%d"',
                ".Lfmt_read_i64:",
                '    .asciz "%lld"',
                ".Lfmt_read_double:",
                '    .asciz "%lf"',
                ".Lfmt_read_char:",
                '    .asciz " %c"',
                ".Lfmt_write_int:",
                '    .asciz "%d"',
                ".Lfmt_write_i64:",
                '    .asciz "%lld"',
                ".Lfmt_write_double:",
                '    .asciz "%f"',
                ".Lfmt_write_char:",
                '    .asciz "%c"',
                ".Lfmt_write_string:",
                '    .asciz "%s"',
            ]
        )
        for literal, label in self.string_literals.items():
            self.lines.append("%s:" % label)
            self.lines.append("    .asciz %s" % literal)
        for literal, label in self.real_literals.items():
            self.lines.append("%s:" % label)
            self.lines.append("    .quad 0x%016x" % self.double_bits(literal))
        self.lines.append("")

    def collect_string_literals(self, node) -> None:
        if node.kind == "Leaf" and self.is_string_literal(node.value or ""):
            if node.value not in self.string_literals:
                self.string_literals[node.value or ""] = ".Lstr_%d" % len(self.string_literals)
        for child in node.children:
            self.collect_string_literals(child)

    def collect_real_literals(self, node) -> None:
        if node.kind == "Leaf" and self.is_float_literal(node.value or ""):
            if node.value not in self.real_literals:
                self.real_literals[node.value or ""] = ".Lreal_%d" % len(self.real_literals)
        for child in node.children:
            self.collect_real_literals(child)

    def emit_globals(self) -> None:
        if not self.global_order:
            return
        self.lines.append(".data")
        for variable in self.global_order:
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
        return self.global_nodes.get(name)

    def emit_text(self, children: Sequence) -> None:
        self.lines.append(".text")
        for node in children:
            if node.kind in {"FunctionDecl", "FunctionDef"} and self.function_body(node) is not None:
                self.emit_function(node)

    def emit_function(self, node) -> None:
        frame = self.prepare_frame(node)
        previous = self.current
        self.current = frame
        self.lines.extend(
            [
                "",
                ".globl %s" % frame.name,
                "%s:" % frame.name,
                "    push rbp",
                "    mov rbp, rsp",
            ]
        )
        if frame.frame_size:
            self.lines.append("    sub rsp, %d" % frame.frame_size)

        frame.scopes.append({})
        for param in frame.params:
            frame.scopes[-1][param.name] = param
        self.emit_param_stores(frame)
        self.emit_compound(self.function_body(node), create_scope=False)
        self.lines.append("%s:" % frame.return_label)
        self.lines.extend(
            [
                "    mov rsp, rbp",
                "    pop rbp",
                "    ret",
            ]
        )
        self.current = previous

    def prepare_frame(self, node) -> FunctionFrame:
        name = node.name or ""
        frame = FunctionFrame(
            name=name,
            return_type=node.type_name or "void",
            return_label=".L_%s_return" % self.sanitize_label(name),
        )
        offset = 0

        def allocate_variable(decl_node, role: str) -> VariableInfo:
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
            frame.variables_by_node[id(decl_node)] = variable
            if role == "param":
                frame.params.append(variable)
            return variable

        for child in node.children:
            if child.kind == "Param":
                allocate_variable(child, "param")

        body = self.function_body(node)
        if body is not None:
            self.collect_local_variables(body, allocate_variable)

        temp_count = max(self.needed_temp_slots(body), 1)
        for _ in range(temp_count):
            offset += 8
            frame.temp_offsets.append(offset)

        frame.local_bytes = offset
        max_args = max(2, self.max_call_args(body))
        frame.call_area_size = 32 + max(0, max_args - 4) * 8
        frame.frame_size = self.align16(frame.local_bytes + frame.call_area_size)
        return frame

    def collect_local_variables(self, node, allocate_variable) -> None:
        if node.kind in {"VarDecl", "ConstDecl"}:
            allocate_variable(node, "local")
            return
        for child in node.children:
            self.collect_local_variables(child, allocate_variable)

    def emit_param_stores(self, frame: FunctionFrame) -> None:
        for index, variable in enumerate(frame.params):
            if index < 4:
                if variable.type_name == "char":
                    self.lines.append("    mov %s, %s" % (self.byte_mem(variable), ARG_REGS_8[index]))
                elif self.is_i64_type(variable.type_name):
                    self.lines.append("    mov %s, %s" % (self.qword_mem(variable), ARG_REGS_64[index]))
                else:
                    self.lines.append("    mov %s, %s" % (self.dword_mem(variable), ARG_REGS_32[index]))
                continue

            stack_offset = 48 + (index - 4) * 8
            if variable.type_name == "char":
                self.lines.append("    mov al, BYTE PTR [rbp+%d]" % stack_offset)
                self.lines.append("    mov %s, al" % self.byte_mem(variable))
            elif self.is_i64_type(variable.type_name):
                self.lines.append("    mov rax, QWORD PTR [rbp+%d]" % stack_offset)
                self.lines.append("    mov %s, rax" % self.qword_mem(variable))
            else:
                self.lines.append("    mov eax, DWORD PTR [rbp+%d]" % stack_offset)
                self.lines.append("    mov %s, eax" % self.dword_mem(variable))

    def emit_compound(self, node, create_scope: bool = True) -> None:
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
        frame = self.require_frame()
        variable = frame.variables_by_node[id(node)]
        frame.scopes[-1][variable.name] = variable
        if node.children:
            if self.is_real_type(variable.type_name):
                self.emit_real_expression(node.children[0])
                self.store_xmm0(variable)
            else:
                self.emit_expression(node.children[0])
                self.store_eax(variable)

    def emit_statement(self, node) -> None:
        if node.kind == "Compound":
            self.emit_compound(node, create_scope=True)
            return
        if node.kind == "ExprStmt":
            if node.children:
                self.emit_expression(node.children[0])
            return
        if node.kind == "InputStmt":
            self.emit_input(node)
            return
        if node.kind == "OutputStmt":
            self.emit_output(node)
            return
        if node.kind == "ReturnStmt":
            if node.children:
                self.emit_expression(node.children[0])
            else:
                self.lines.append("    xor eax, eax")
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

    def emit_input(self, node) -> None:
        for child in node.children:
            variable = self.lookup_variable(child.value or "", child.line)
            if variable.is_const:
                raise CodegenError("cin target must be assignable", child.line)
            if variable.type_name not in SUPPORTED_VALUE_TYPES:
                raise CodegenError("cin supports only integer scalar targets", child.line)
            self.load_address("rdx", variable)
            fmt = self.input_format(variable.type_name)
            self.lines.append("    lea rcx, %s[rip]" % fmt)
            self.lines.append("    xor eax, eax")
            self.lines.append("    call scanf")

    def emit_output(self, node) -> None:
        for child in node.children:
            type_name = self.expression_type(child)
            if type_name not in SUPPORTED_VALUE_TYPES and type_name != "string":
                raise CodegenError(
                    "cout supports only int, char, and string expressions",
                    child.line or node.line,
                )
            if type_name == "string":
                label = self.string_literals.get(child.value or "")
                if label is None:
                    raise CodegenError("unknown string literal", child.line or node.line)
                self.lines.append("    lea rdx, %s[rip]" % label)
                self.lines.append("    lea rcx, .Lfmt_write_string[rip]")
                self.lines.append("    xor eax, eax")
                self.lines.append("    call printf")
                continue
            if self.is_real_type(type_name):
                self.emit_real_expression(child)
                self.lines.append("    movq rdx, xmm0")
                self.lines.append("    movq xmm1, rdx")
                self.lines.append("    lea rcx, .Lfmt_write_double[rip]")
                self.lines.append("    xor eax, eax")
                self.lines.append("    call printf")
                continue
            self.emit_expression(child)
            if self.is_i64_type(type_name):
                self.lines.append("    mov rdx, rax")
            else:
                self.lines.append("    mov edx, eax")
            fmt = self.output_format(type_name or "int")
            self.lines.append("    lea rcx, %s[rip]" % fmt)
            self.lines.append("    xor eax, eax")
            self.lines.append("    call printf")

    def emit_if(self, node) -> None:
        else_label = self.new_label("else")
        end_label = self.new_label("endif")
        self.emit_expression(node.children[0])
        self.lines.append("    cmp eax, 0")
        self.lines.append("    je %s" % else_label)
        self.emit_statement(node.children[1])
        self.lines.append("    jmp %s" % end_label)
        self.lines.append("%s:" % else_label)
        if len(node.children) > 2:
            self.emit_statement(node.children[2])
        self.lines.append("%s:" % end_label)

    def emit_while(self, node) -> None:
        start_label = self.new_label("while_start")
        end_label = self.new_label("while_end")
        frame = self.require_frame()
        self.lines.append("%s:" % start_label)
        self.emit_expression(node.children[0])
        self.lines.append("    cmp eax, 0")
        self.lines.append("    je %s" % end_label)
        frame.loops.append(LoopLabels(break_label=end_label, continue_label=start_label))
        self.emit_statement(node.children[1])
        frame.loops.pop()
        self.lines.append("    jmp %s" % start_label)
        self.lines.append("%s:" % end_label)

    def emit_for(self, node) -> None:
        init, condition, step, body = self.for_parts(node)
        if init is not None:
            if init.kind in {"VarDecl", "ConstDecl"}:
                self.emit_declaration(init)
            else:
                self.emit_expression(init)

        start_label = self.new_label("for_start")
        step_label = self.new_label("for_step")
        end_label = self.new_label("for_end")
        frame = self.require_frame()

        self.lines.append("%s:" % start_label)
        if condition is not None:
            self.emit_expression(condition)
            self.lines.append("    cmp eax, 0")
            self.lines.append("    je %s" % end_label)
        frame.loops.append(LoopLabels(break_label=end_label, continue_label=step_label))
        self.emit_statement(body)
        frame.loops.pop()
        self.lines.append("%s:" % step_label)
        if step is not None:
            self.emit_expression(step)
        self.lines.append("    jmp %s" % start_label)
        self.lines.append("%s:" % end_label)

    def emit_do_while(self, node) -> None:
        start_label = self.new_label("do_start")
        cond_label = self.new_label("do_cond")
        end_label = self.new_label("do_end")
        frame = self.require_frame()
        self.lines.append("%s:" % start_label)
        frame.loops.append(LoopLabels(break_label=end_label, continue_label=cond_label))
        self.emit_statement(node.children[0])
        frame.loops.pop()
        self.lines.append("%s:" % cond_label)
        self.emit_expression(node.children[1])
        self.lines.append("    cmp eax, 0")
        self.lines.append("    jne %s" % start_label)
        self.lines.append("%s:" % end_label)

    def emit_expression(self, node) -> None:
        if node.kind == "Empty":
            self.lines.append("    xor eax, eax")
            return
        if node.kind == "Leaf":
            self.emit_leaf(node)
            return
        if node.kind == "Call":
            self.emit_call(node)
            return
        if node.kind == "Postfix":
            self.emit_postfix(node)
            return
        if node.kind == "Cast":
            self.emit_cast(node)
            return
        if node.kind == "Conditional":
            self.emit_conditional(node)
            return
        if node.kind != "Operator":
            raise CodegenError("unsupported expression '%s'" % node.kind, node.line)

        if len(node.children) == 1:
            self.emit_unary(node)
            return
        if node.value in RELATIONAL_JUMPS and (
            self.is_real_type(self.expression_type(node.children[0]))
            or self.is_real_type(self.expression_type(node.children[1]))
        ):
            self.emit_real_compare(node)
            return
        if node.value == "=":
            target = node.children[0]
            if target.kind != "Leaf":
                raise CodegenError("assignment target must be a variable", node.line)
            variable = self.lookup_variable(target.value or "", target.line)
            if self.is_real_type(variable.type_name):
                self.emit_real_expression(node.children[1])
                self.store_xmm0(variable)
            else:
                self.emit_expression(node.children[1])
                self.store_eax(variable)
            return
        if node.value in {"&&", "||"}:
            self.emit_logical(node)
            return
        self.emit_binary(node)

    def emit_cast(self, node) -> None:
        if not node.children:
            self.lines.append("    xor eax, eax")
            return
        target_type = node.type_name or ""
        source_type = self.expression_type(node.children[0])
        if self.is_real_type(target_type):
            self.emit_real_expression(node.children[0])
            return
        if self.is_real_type(source_type):
            self.emit_real_expression(node.children[0])
            self.lines.append("    cvttsd2si rax, xmm0")
            return
        self.emit_expression(node.children[0])

    def emit_conditional(self, node) -> None:
        if len(node.children) != 3:
            self.lines.append("    xor eax, eax")
            return
        else_label = self.new_label("ternary_else")
        end_label = self.new_label("ternary_end")
        self.emit_expression(node.children[0])
        self.lines.append("    cmp rax, 0")
        self.lines.append("    je %s" % else_label)
        self.emit_expression(node.children[1])
        self.lines.append("    jmp %s" % end_label)
        self.lines.append("%s:" % else_label)
        self.emit_expression(node.children[2])
        self.lines.append("%s:" % end_label)

    def emit_real_expression(self, node) -> None:
        if node.kind == "Cast":
            if not node.children:
                self.lines.append("    pxor xmm0, xmm0")
                return
            if self.is_real_type(node.type_name):
                self.emit_real_expression(node.children[0])
                return
            self.emit_expression(node)
            self.lines.append("    cvtsi2sd xmm0, rax")
            return
        if node.kind == "Leaf":
            text = node.value or ""
            if self.is_float_literal(text):
                label = self.real_literals.get(text)
                if label is None:
                    label = ".Lreal_%d" % len(self.real_literals)
                    self.real_literals[text] = label
                self.lines.append("    movsd xmm0, QWORD PTR %s[rip]" % label)
                return
            if self.is_int_literal(text) or self.is_char_literal(text):
                self.emit_expression(node)
                self.lines.append("    cvtsi2sd xmm0, rax")
                return
            variable = self.lookup_variable(text, node.line)
            if self.is_real_type(variable.type_name):
                self.lines.append("    movsd xmm0, %s" % self.qword_mem(variable))
                return
            self.load_variable(variable)
            self.lines.append("    cvtsi2sd xmm0, rax")
            return
        if node.kind == "Operator" and len(node.children) == 2 and node.value in {"+", "-", "*", "/"}:
            self.emit_real_expression(node.children[0])
            slot = self.reserve_temp()
            self.lines.append("    movsd QWORD PTR %s, xmm0" % self.temp_mem(slot))
            self.emit_real_expression(node.children[1])
            self.lines.append("    movsd xmm1, QWORD PTR %s" % self.temp_mem(slot))
            self.release_temp()
            if node.value == "+":
                self.lines.append("    addsd xmm1, xmm0")
            elif node.value == "-":
                self.lines.append("    subsd xmm1, xmm0")
            elif node.value == "*":
                self.lines.append("    mulsd xmm1, xmm0")
            elif node.value == "/":
                self.lines.append("    divsd xmm1, xmm0")
            self.lines.append("    movapd xmm0, xmm1")
            return
        if node.kind == "Operator" and len(node.children) == 1:
            self.emit_real_expression(node.children[0])
            if node.value == "-":
                self.lines.append("    xorpd xmm1, xmm1")
                self.lines.append("    subsd xmm1, xmm0")
                self.lines.append("    movapd xmm0, xmm1")
            return
        self.emit_expression(node)
        self.lines.append("    cvtsi2sd xmm0, rax")

    def emit_real_compare(self, node) -> None:
        self.emit_real_expression(node.children[0])
        slot = self.reserve_temp()
        self.lines.append("    movsd QWORD PTR %s, xmm0" % self.temp_mem(slot))
        self.emit_real_expression(node.children[1])
        self.lines.append("    movsd xmm1, QWORD PTR %s" % self.temp_mem(slot))
        self.release_temp()
        self.lines.append("    ucomisd xmm1, xmm0")
        jump = {
            "==": "sete",
            "!=": "setne",
            "<": "setb",
            "<=": "setbe",
            ">": "seta",
            ">=": "setae",
        }.get(node.value)
        if jump is None:
            raise CodegenError("unsupported real comparison '%s'" % node.value, node.line)
        self.lines.append("    %s al" % jump)
        self.lines.append("    movzx eax, al")

    def emit_leaf(self, node) -> None:
        text = node.value or ""
        if self.is_string_literal(text):
            raise CodegenError("string expressions are not supported in v1", node.line)
        if self.is_char_literal(text):
            self.lines.append("    mov eax, %d" % self.char_value(text))
            return
        if self.is_int_literal(text):
            self.lines.append("    mov rax, %d" % self.int_value(text))
            return
        if self.is_float_literal(text):
            self.emit_real_expression(node)
            self.lines.append("    cvttsd2si rax, xmm0")
            return
        variable = self.lookup_variable(text, node.line)
        self.load_variable(variable)

    def emit_unary(self, node) -> None:
        self.emit_expression(node.children[0])
        if node.value == "+":
            return
        if node.value == "-":
            self.lines.append("    neg eax")
            return
        if node.value == "!":
            self.lines.append("    cmp eax, 0")
            self.lines.append("    sete al")
            self.lines.append("    movzx eax, al")
            return
        raise CodegenError("unsupported unary operator '%s'" % node.value, node.line)

    def emit_binary(self, node) -> None:
        self.emit_expression(node.children[0])
        slot = self.reserve_temp()
        self.lines.append("    cdqe")
        self.lines.append("    mov QWORD PTR %s, rax" % self.temp_mem(slot))
        self.emit_expression(node.children[1])
        self.lines.append("    mov r10, rax")
        self.lines.append("    mov rax, QWORD PTR %s" % self.temp_mem(slot))
        self.release_temp()

        if node.value == "+":
            self.lines.append("    add rax, r10")
        elif node.value == "-":
            self.lines.append("    sub rax, r10")
        elif node.value == "*":
            self.lines.append("    imul rax, r10")
        elif node.value == "/":
            self.lines.append("    cqo")
            self.lines.append("    idiv r10")
        elif node.value == "%":
            self.lines.append("    cqo")
            self.lines.append("    idiv r10")
            self.lines.append("    mov rax, rdx")
        elif node.value in RELATIONAL_JUMPS:
            self.lines.append("    cmp rax, r10")
            self.lines.append("    %s al" % RELATIONAL_JUMPS[node.value])
            self.lines.append("    movzx eax, al")
        else:
            raise CodegenError("unsupported binary operator '%s'" % node.value, node.line)

    def emit_logical(self, node) -> None:
        false_label = self.new_label("logic_false")
        true_label = self.new_label("logic_true")
        end_label = self.new_label("logic_end")
        if node.value == "&&":
            self.emit_expression(node.children[0])
            self.lines.append("    cmp rax, 0")
            self.lines.append("    je %s" % false_label)
            self.emit_expression(node.children[1])
            self.lines.append("    cmp rax, 0")
            self.lines.append("    je %s" % false_label)
            self.lines.append("%s:" % true_label)
            self.lines.append("    mov eax, 1")
            self.lines.append("    jmp %s" % end_label)
            self.lines.append("%s:" % false_label)
            self.lines.append("    xor eax, eax")
            self.lines.append("%s:" % end_label)
            return

        self.emit_expression(node.children[0])
        self.lines.append("    cmp rax, 0")
        self.lines.append("    jne %s" % true_label)
        self.emit_expression(node.children[1])
        self.lines.append("    cmp rax, 0")
        self.lines.append("    jne %s" % true_label)
        self.lines.append("%s:" % false_label)
        self.lines.append("    xor eax, eax")
        self.lines.append("    jmp %s" % end_label)
        self.lines.append("%s:" % true_label)
        self.lines.append("    mov eax, 1")
        self.lines.append("%s:" % end_label)

    def emit_call(self, node) -> None:
        name = node.name or ""
        if name in BUILTIN_FUNCTIONS:
            self.emit_builtin_call(node)
            return
        info = self.functions.get(name)
        if info is None:
            raise CodegenError("function '%s' is not declared" % name, node.line)
        if info.return_type not in SUPPORTED_RETURN_TYPES:
            raise CodegenError("function return type '%s' is not supported" % info.return_type, node.line)

        frame = self.require_frame()
        base_depth = frame.temp_depth
        frame.temp_depth += len(node.children)
        if frame.temp_depth > len(frame.temp_offsets):
            raise CodegenError("internal error: not enough temporary stack slots", node.line)

        for index, child in enumerate(node.children):
            self.emit_expression(child)
            self.lines.append("    cdqe")
            self.lines.append("    mov QWORD PTR %s, rax" % self.temp_mem(base_depth + index))

        for index in range(len(node.children)):
            source = self.temp_mem(base_depth + index)
            if index < 4:
                self.lines.append("    mov %s, QWORD PTR %s" % (ARG_REGS_64[index], source))
            else:
                stack_offset = 32 + (index - 4) * 8
                self.lines.append("    mov rax, QWORD PTR %s" % source)
                self.lines.append("    mov QWORD PTR [rsp+%d], rax" % stack_offset)

        frame.temp_depth = base_depth
        self.lines.append("    call %s" % name)

    def emit_builtin_call(self, node) -> None:
        name = node.name or ""
        if name in {"abs", "llabs"}:
            if len(node.children) != 1:
                raise CodegenError("builtin '%s' expects one argument" % name, node.line)
            done_label = self.new_label("abs_done")
            self.emit_expression(node.children[0])
            self.lines.append("    cmp rax, 0")
            self.lines.append("    jge %s" % done_label)
            self.lines.append("    neg eax")
            self.lines.append("%s:" % done_label)
            return

        if name in {"min", "max"}:
            if len(node.children) != 2:
                raise CodegenError("builtin '%s' expects two arguments" % name, node.line)
            slot = self.reserve_temp()
            self.emit_expression(node.children[0])
            self.lines.append("    cdqe")
            self.lines.append("    mov QWORD PTR %s, rax" % self.temp_mem(slot))
            self.emit_expression(node.children[1])
            self.lines.append("    mov r10, rax")
            self.lines.append("    mov rax, QWORD PTR %s" % self.temp_mem(slot))
            self.release_temp()
            self.lines.append("    cmp rax, r10")
            if name == "min":
                self.lines.append("    cmovg rax, r10")
            else:
                self.lines.append("    cmovl rax, r10")
            return

        raise CodegenError("unsupported builtin '%s'" % name, node.line)

    def emit_postfix(self, node) -> None:
        if not node.children or node.children[0].kind != "Leaf":
            raise CodegenError("increment target must be a variable", node.line)
        variable = self.lookup_variable(node.children[0].value or "", node.line)
        slot = self.reserve_temp()
        self.load_variable(variable)
        self.lines.append("    cdqe")
        self.lines.append("    mov QWORD PTR %s, rax" % self.temp_mem(slot))
        self.load_variable(variable)
        if node.value == "++":
            self.lines.append("    add eax, 1")
        elif node.value == "--":
            self.lines.append("    sub eax, 1")
        else:
            raise CodegenError("unsupported postfix operator '%s'" % node.value, node.line)
        self.store_eax(variable)
        self.lines.append("    mov rax, QWORD PTR %s" % self.temp_mem(slot))
        self.release_temp()

    def load_variable(self, variable: VariableInfo) -> None:
        if variable.type_name == "char":
            self.lines.append("    movsx eax, %s" % self.byte_mem(variable))
        elif self.is_i64_type(variable.type_name):
            self.lines.append("    mov rax, %s" % self.qword_mem(variable))
        else:
            self.lines.append("    mov eax, %s" % self.dword_mem(variable))

    def store_eax(self, variable: VariableInfo) -> None:
        if variable.is_const:
            raise CodegenError("cannot assign to const variable '%s'" % variable.name, variable.line)
        if variable.type_name == "char":
            self.lines.append("    mov %s, al" % self.byte_mem(variable))
        elif self.is_i64_type(variable.type_name):
            self.lines.append("    mov %s, rax" % self.qword_mem(variable))
        else:
            self.lines.append("    mov %s, eax" % self.dword_mem(variable))

    def store_xmm0(self, variable: VariableInfo) -> None:
        if variable.is_const:
            raise CodegenError("cannot assign to const variable '%s'" % variable.name, variable.line)
        self.lines.append("    movsd %s, xmm0" % self.qword_mem(variable))

    def load_address(self, register: str, variable: VariableInfo) -> None:
        if variable.is_global:
            self.lines.append("    lea %s, %s[rip]" % (register, variable.global_label))
        else:
            self.lines.append("    lea %s, [rbp-%d]" % (register, variable.offset or 0))

    def byte_mem(self, variable: VariableInfo) -> str:
        return "BYTE PTR %s" % self.variable_address(variable)

    def dword_mem(self, variable: VariableInfo) -> str:
        return "DWORD PTR %s" % self.variable_address(variable)

    def qword_mem(self, variable: VariableInfo) -> str:
        return "QWORD PTR %s" % self.variable_address(variable)

    def variable_address(self, variable: VariableInfo) -> str:
        if variable.is_global:
            return "%s[rip]" % variable.global_label
        return "[rbp-%d]" % (variable.offset or 0)

    def temp_mem(self, index: int) -> str:
        frame = self.require_frame()
        return "[rbp-%d]" % frame.temp_offsets[index]

    def reserve_temp(self) -> int:
        frame = self.require_frame()
        index = frame.temp_depth
        frame.temp_depth += 1
        if frame.temp_depth > len(frame.temp_offsets):
            raise CodegenError("internal error: expression temporaries exhausted")
        return index

    def release_temp(self) -> None:
        frame = self.require_frame()
        frame.temp_depth -= 1

    def lookup_variable(self, name: str, line: Optional[int]) -> VariableInfo:
        frame = self.current
        if frame is not None:
            for scope in reversed(frame.scopes):
                if name in scope:
                    return scope[name]
        if name in self.globals:
            return self.globals[name]
        raise CodegenError("variable '%s' is not declared" % name, line)

    def expression_type(self, node) -> Optional[str]:
        if node.kind == "Leaf":
            text = node.value or ""
            if self.is_string_literal(text):
                return "string"
            if self.is_char_literal(text):
                return "char"
            if self.is_float_literal(text):
                return "double"
            if self.is_int_literal(text):
                return "long long" if any(ch in text.lower() for ch in "lu") else "int"
            return self.lookup_variable(text, node.line).type_name
        if node.kind == "Call":
            if node.name in BUILTIN_FUNCTIONS:
                return "int"
            info = self.functions.get(node.name or "")
            return info.return_type if info is not None else None
        if node.kind == "Postfix":
            return self.expression_type(node.children[0]) if node.children else None
        if node.kind == "Operator":
            if node.value == "=" and node.children:
                return self.expression_type(node.children[0])
            if node.value in {"&&", "||", "!", "==", "!=", "<", "<=", ">", ">="}:
                return "int"
            if len(node.children) == 1:
                return self.expression_type(node.children[0])
            if self.is_real_type(self.expression_type(node.children[0])) or self.is_real_type(
                self.expression_type(node.children[1])
            ):
                return "double"
            if self.is_i64_type(self.expression_type(node.children[0])) or self.is_i64_type(
                self.expression_type(node.children[1])
            ):
                return "long long"
            return "int"
        if node.kind == "Cast":
            return node.type_name
        if node.kind == "Conditional" and len(node.children) == 3:
            left = self.expression_type(node.children[1])
            right = self.expression_type(node.children[2])
            if self.is_real_type(left) or self.is_real_type(right):
                return "double"
            if self.is_i64_type(left) or self.is_i64_type(right):
                return "long long"
            return left or right
        return None

    def for_parts(self, node):
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
        if node.children and node.children[-1].kind == "Compound":
            return node.children[-1]
        return None

    def max_call_args(self, node) -> int:
        if node is None:
            return 0
        own = 0
        if node.kind == "Call":
            own = len(node.children)
        elif node.kind in {"InputStmt", "OutputStmt"}:
            own = 2
        return max([own] + [self.max_call_args(child) for child in node.children])

    def needed_temp_slots(self, node) -> int:
        if node is None:
            return 0
        if node.kind in {"Leaf", "Empty"}:
            return 0
        if node.kind == "Call":
            nested = [self.needed_temp_slots(child) for child in node.children]
            return len(node.children) + (max(nested) if nested else 0)
        if node.kind == "Postfix":
            return 1
        if node.kind in {"Cast", "Conditional"}:
            child_needs = [self.needed_temp_slots(child) for child in node.children]
            return max(child_needs) if child_needs else 0
        if node.kind == "Operator":
            if len(node.children) == 1:
                return self.needed_temp_slots(node.children[0])
            if node.value == "=":
                return self.needed_temp_slots(node.children[1])
            return max(
                self.needed_temp_slots(node.children[0]),
                1 + self.needed_temp_slots(node.children[1]),
                1,
            )
        child_needs = [self.needed_temp_slots(child) for child in node.children]
        return max(child_needs) if child_needs else 0

    def constant_initializer_value(self, node, type_name: str) -> int:
        if node.kind != "Leaf":
            raise CodegenError("global initializer must be a literal", node.line)
        text = node.value or ""
        if type_name == "char" and self.is_char_literal(text):
            return self.char_value(text)
        if type_name in {"int", "long long", "unsigned long long", "bool"} and self.is_int_literal(text):
            return self.int_value(text)
        raise CodegenError("global initializer type does not match declaration", node.line)

    def require_return_type(self, type_name: str, line: Optional[int]) -> str:
        if type_name.endswith("[]"):
            raise CodegenError("arrays are not supported in v1", line)
        if type_name not in SUPPORTED_RETURN_TYPES:
            raise CodegenError("type '%s' is not supported by the assembly backend" % type_name, line)
        return type_name

    def require_value_type(self, type_name: str, line: Optional[int]) -> str:
        if type_name.endswith("[]"):
            raise CodegenError("arrays are not supported in v1", line)
        if type_name not in SUPPORTED_VALUE_TYPES:
            raise CodegenError("type '%s' is not supported by the assembly backend" % type_name, line)
        return type_name

    def new_label(self, hint: str) -> str:
        frame = self.require_frame()
        frame.label_counter += 1
        return ".L_%s_%s_%d" % (self.sanitize_label(frame.name), hint, frame.label_counter)

    def require_frame(self) -> FunctionFrame:
        if self.current is None:
            raise CodegenError("internal error: no active function")
        return self.current

    @staticmethod
    def sanitize_label(name: str) -> str:
        return re.sub(r"\W", "_", name or "fn")

    @staticmethod
    def align16(value: int) -> int:
        return (value + 15) // 16 * 16

    @staticmethod
    def is_string_literal(text: str) -> bool:
        return len(text) >= 2 and text[0] == '"' and text[-1] == '"'

    @staticmethod
    def is_char_literal(text: str) -> bool:
        return len(text) >= 3 and text[0] == "'" and text[-1] == "'"

    @staticmethod
    def is_int_literal(text: str) -> bool:
        return INT_LITERAL_RE.fullmatch(text or "") is not None

    @staticmethod
    def int_value(text: str) -> int:
        text = re.sub(r"(?:[uU]?[lL]{1,2}|[lL]{1,2}[uU]?)$", "", text or "")
        if re.fullmatch(r"[+-]?0[0-7]+", text or ""):
            sign = -1 if text.startswith("-") else 1
            digits = text[1:] if text[0] in "+-" else text
            return sign * int(digits, 8)
        return int(text, 0)

    @staticmethod
    def is_i64_type(type_name: Optional[str]) -> bool:
        return type_name in {"long long", "unsigned long long"}

    def input_format(self, type_name: str) -> str:
        if type_name == "char":
            return ".Lfmt_read_char"
        if self.is_real_type(type_name):
            return ".Lfmt_read_double"
        if self.is_i64_type(type_name):
            return ".Lfmt_read_i64"
        return ".Lfmt_read_int"

    def output_format(self, type_name: str) -> str:
        if type_name == "char":
            return ".Lfmt_write_char"
        if self.is_real_type(type_name):
            return ".Lfmt_write_double"
        if self.is_i64_type(type_name):
            return ".Lfmt_write_i64"
        return ".Lfmt_write_int"

    @staticmethod
    def is_real_type(type_name: Optional[str]) -> bool:
        return type_name in REAL_TYPES

    @staticmethod
    def is_float_literal(text: str) -> bool:
        return FLOAT_LITERAL_RE.fullmatch(text or "") is not None

    @staticmethod
    def double_bits(text: str) -> int:
        return struct.unpack("<Q", struct.pack("<d", float(text)))[0]

    @staticmethod
    def char_value(text: str) -> int:
        body = text[1:-1]
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


def generate_assembly(root) -> str:
    return AssemblyGenerator().generate(root)
