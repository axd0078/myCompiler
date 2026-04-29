from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Union


IDENTIFIER_CODE = 700
CONSTANT_CODES = {400, 500, 600, 800}
EOF_CODE = 0
TYPE_KEYWORDS = {"int", "float", "char", "void"}
RELATIONAL_OPERATORS = {"<", ">", "<=", ">=", "==", "!="}


class Token:
    def __init__(self, lexeme: str, token_code: int, line: int):
        self.lexeme = lexeme
        self.token_code = int(token_code)
        self.line = int(line)


class ParserError(Exception):
    pass


@dataclass
class ASTNode:
    kind: str
    line: Optional[int] = None
    value: Optional[str] = None
    type_name: Optional[str] = None
    name: Optional[str] = None
    children: List["ASTNode"] = field(default_factory=list)


class Lexer:
    KEYWORDS = {
        "char": 101,
        "int": 102,
        "float": 103,
        "break": 104,
        "const": 105,
        "return": 106,
        "void": 107,
        "continue": 108,
        "do": 109,
        "while": 110,
        "if": 111,
        "else": 112,
        "for": 113,
    }

    SINGLE_TOKENS = {
        "(": 201,
        ")": 202,
        "[": 203,
        "]": 204,
        "!": 205,
        "*": 206,
        "/": 207,
        "%": 208,
        "+": 209,
        "-": 210,
        "<": 211,
        ">": 213,
        "=": 219,
        "{": 301,
        "}": 302,
        ";": 303,
        ",": 304,
    }

    DOUBLE_TOKENS = {
        "<=": 212,
        ">=": 214,
        "==": 215,
        "!=": 216,
        "&&": 217,
        "||": 218,
    }

    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.errors: List[str] = []

    def tokenize(self) -> List[Token]:
        tokens: List[Token] = []
        while not self.at_end():
            self.skip_whitespace_and_comments()
            if self.at_end():
                break

            ch = self.current()
            if ch.isalpha() or ch == "_":
                tokens.append(self.read_identifier())
            elif ch.isdigit():
                tokens.append(self.read_number())
            elif ch == "'":
                token = self.read_char()
                if token is not None:
                    tokens.append(token)
            elif ch == '"':
                token = self.read_string()
                if token is not None:
                    tokens.append(token)
            else:
                token = self.read_operator()
                if token is not None:
                    tokens.append(token)

        return tokens

    def at_end(self) -> bool:
        return self.pos >= len(self.source)

    def current(self) -> str:
        if self.at_end():
            return "\0"
        return self.source[self.pos]

    def peek(self) -> str:
        index = self.pos + 1
        if index >= len(self.source):
            return "\0"
        return self.source[index]

    def advance(self) -> str:
        ch = self.current()
        self.pos += 1
        if ch == "\n":
            self.line += 1
        return ch

    def skip_whitespace_and_comments(self) -> None:
        while not self.at_end():
            if self.current() in " \t\r\n":
                self.advance()
                continue
            if self.current() == "/" and self.peek() == "/":
                while not self.at_end() and self.current() != "\n":
                    self.advance()
                continue
            if self.current() == "/" and self.peek() == "*":
                start_line = self.line
                self.advance()
                self.advance()
                while not self.at_end():
                    if self.current() == "*" and self.peek() == "/":
                        self.advance()
                        self.advance()
                        break
                    self.advance()
                else:
                    self.errors.append("%d 103" % start_line)
                continue
            break

    def read_identifier(self) -> Token:
        start = self.pos
        line = self.line
        while not self.at_end() and (self.current().isalnum() or self.current() == "_"):
            self.advance()
        lexeme = self.source[start:self.pos]
        return Token(lexeme, self.KEYWORDS.get(lexeme, IDENTIFIER_CODE), line)

    def read_number(self) -> Token:
        start = self.pos
        line = self.line

        if self.current() == "0" and self.peek() in {"x", "X"}:
            self.advance()
            self.advance()
            while not self.at_end() and (
                self.current().isdigit() or self.current().lower() in "abcdef"
            ):
                self.advance()
            return Token(self.source[start:self.pos], 400, line)

        while not self.at_end() and self.current().isdigit():
            self.advance()

        token_code = 400
        if not self.at_end() and self.current() == ".":
            token_code = 800
            self.advance()
            while not self.at_end() and self.current().isdigit():
                self.advance()

        return Token(self.source[start:self.pos], token_code, line)

    def read_char(self) -> Optional[Token]:
        line = self.line
        self.advance()
        if self.at_end() or self.current() == "\n":
            self.errors.append("%d 104" % line)
            return None

        if self.current() == "\\":
            self.advance()
            value = "\\" + self.advance()
        else:
            value = self.advance()

        if self.current() != "'":
            self.errors.append("%d 104" % line)
            while not self.at_end() and self.current() not in {"'", "\n"}:
                self.advance()
            if not self.at_end() and self.current() == "'":
                self.advance()
            return None

        self.advance()
        return Token(value, 500, line)

    def read_string(self) -> Optional[Token]:
        line = self.line
        self.advance()
        chars: List[str] = []
        while not self.at_end() and self.current() != '"':
            if self.current() == "\n":
                self.errors.append("%d 105" % line)
                return None
            if self.current() == "\\":
                self.advance()
                if self.at_end():
                    self.errors.append("%d 105" % line)
                    return None
                chars.append("\\" + self.advance())
            else:
                chars.append(self.advance())

        if self.at_end():
            self.errors.append("%d 105" % line)
            return None

        self.advance()
        return Token("".join(chars), 600, line)

    def read_operator(self) -> Optional[Token]:
        line = self.line
        two = self.current() + self.peek()
        if two in self.DOUBLE_TOKENS:
            self.advance()
            self.advance()
            return Token(two, self.DOUBLE_TOKENS[two], line)

        ch = self.advance()
        if ch in self.SINGLE_TOKENS:
            return Token(ch, self.SINGLE_TOKENS[ch], line)

        self.errors.append("%d 101" % line)
        return None


class Parser:
    def __init__(self, tokens: Sequence[Token]):
        self.tokens = list(tokens)
        eof_line = self.tokens[-1].line if self.tokens else 1
        self.tokens.append(Token("", EOF_CODE, eof_line))
        self.pos = 0

    def parse(self) -> ASTNode:
        children: List[ASTNode] = []
        while not self.is_eof():
            if self.current().lexeme == "const":
                children.extend(self.parse_const_decl())
            elif self.is_type_token(self.current()):
                children.extend(self.parse_toplevel_type_stmt())
            else:
                self.error("unexpected token at top level")
        return ASTNode("Program", children=children)

    def parse_toplevel_type_stmt(self) -> List[ASTNode]:
        type_token = self.expect_type()
        name_token = self.expect_identifier()
        self.parse_array_suffix()
        if self.match("("):
            params = self.parse_parameter_list_opt()
            self.expect(")")
            if self.match(";"):
                return [
                    ASTNode(
                        "FunctionDecl",
                        line=name_token.line,
                        type_name=type_token.lexeme,
                        name=name_token.lexeme,
                        children=params,
                    )
                ]
            body = self.parse_compound()
            return [
                ASTNode(
                    "FunctionDef",
                    line=name_token.line,
                    type_name=type_token.lexeme,
                    name=name_token.lexeme,
                    children=params + [body],
                )
            ]
        return self.parse_var_decl_rest(type_token.lexeme, name_token)

    def parse_parameter_list_opt(self) -> List[ASTNode]:
        params: List[ASTNode] = []
        if self.current().lexeme == ")":
            return params
        while True:
            type_token = self.expect_type()
            name_token = self.expect_identifier()
            self.parse_array_suffix()
            params.append(
                ASTNode(
                    "Param",
                    line=name_token.line,
                    type_name=type_token.lexeme,
                    name=name_token.lexeme,
                )
            )
            if not self.match(","):
                break
        return params

    def parse_const_decl(self) -> List[ASTNode]:
        self.expect("const")
        type_token = self.expect_type()
        decls = [self.parse_const_item(type_token.lexeme)]
        while self.match(","):
            decls.append(self.parse_const_item(type_token.lexeme))
        self.expect(";")
        return decls

    def parse_const_item(self, type_name: str) -> ASTNode:
        name_token = self.expect_identifier()
        self.parse_array_suffix()
        self.expect("=")
        expr = self.parse_expression()
        return ASTNode(
            "ConstDecl",
            line=name_token.line,
            type_name=type_name,
            name=name_token.lexeme,
            children=[expr],
        )

    def parse_var_decl_rest(self, type_name: str, first_name: Token) -> List[ASTNode]:
        decls = [self.parse_var_item(type_name, first_name)]
        while self.match(","):
            next_name = self.expect_identifier()
            decls.append(self.parse_var_item(type_name, next_name))
        self.expect(";")
        return decls

    def parse_var_item(self, type_name: str, name_token: Token) -> ASTNode:
        self.parse_array_suffix()
        children: List[ASTNode] = []
        if self.match("="):
            children.append(self.parse_expression())
        return ASTNode(
            "VarDecl",
            line=name_token.line,
            type_name=type_name,
            name=name_token.lexeme,
            children=children,
        )

    def parse_array_suffix(self) -> None:
        while self.match("["):
            if self.current().lexeme != "]":
                self.parse_expression()
            self.expect("]")

    def parse_compound(self) -> ASTNode:
        self.expect("{")
        children: List[ASTNode] = []
        while self.current().lexeme != "}":
            if self.is_eof():
                self.error("expected '}'")
            if self.current().lexeme == "const":
                children.extend(self.parse_const_decl())
            elif self.is_type_token(self.current()):
                children.extend(self.parse_local_var_decl())
            else:
                children.append(self.parse_statement())
        self.expect("}")
        return ASTNode("Compound", children=children)

    def parse_local_var_decl(self) -> List[ASTNode]:
        type_token = self.expect_type()
        name_token = self.expect_identifier()
        return self.parse_var_decl_rest(type_token.lexeme, name_token)

    def parse_statement(self) -> ASTNode:
        lexeme = self.current().lexeme
        if lexeme == "{":
            return self.parse_compound()
        if lexeme == "if":
            return self.parse_if_stmt()
        if lexeme == "while":
            return self.parse_while_stmt()
        if lexeme == "for":
            return self.parse_for_stmt()
        if lexeme == "do":
            return self.parse_do_while_stmt()
        if lexeme == "return":
            return self.parse_return_stmt()
        if lexeme == "continue":
            token = self.advance()
            self.expect(";")
            return ASTNode("ContinueStmt", line=token.line)
        if lexeme == "break":
            token = self.advance()
            self.expect(";")
            return ASTNode("BreakStmt", line=token.line)
        return self.parse_expr_stmt()

    def parse_if_stmt(self) -> ASTNode:
        self.expect("if")
        self.expect("(")
        cond = self.parse_expression()
        self.expect(")")
        then_branch = self.parse_statement()
        children = [cond, then_branch]
        if self.match("else"):
            children.append(self.parse_statement())
        return ASTNode("IfStmt", children=children)

    def parse_while_stmt(self) -> ASTNode:
        self.expect("while")
        self.expect("(")
        cond = self.parse_expression()
        self.expect(")")
        body = self.parse_statement()
        return ASTNode("WhileStmt", children=[cond, body])

    def parse_for_stmt(self) -> ASTNode:
        self.expect("for")
        self.expect("(")
        children: List[ASTNode] = []
        init = self.parse_expr_opt()
        self.expect(";")
        cond = self.parse_expr_opt()
        self.expect(";")
        step = self.parse_expr_opt()
        self.expect(")")
        for node in (init, cond, step):
            if node is not None:
                children.append(node)
        children.append(self.parse_statement())
        return ASTNode("ForStmt", children=children)

    def parse_do_while_stmt(self) -> ASTNode:
        self.expect("do")
        body = self.parse_statement()
        self.expect("while")
        self.expect("(")
        cond = self.parse_expression()
        self.expect(")")
        self.expect(";")
        return ASTNode("DoWhileStmt", children=[body, cond])

    def parse_return_stmt(self) -> ASTNode:
        token = self.expect("return")
        expr = self.parse_expr_opt()
        self.expect(";")
        children = [expr] if expr is not None else []
        return ASTNode("ReturnStmt", line=token.line, children=children)

    def parse_expr_stmt(self) -> ASTNode:
        expr = self.parse_expr_opt()
        self.expect(";")
        children = [expr] if expr is not None else []
        return ASTNode("ExprStmt", children=children)

    def parse_expr_opt(self) -> Optional[ASTNode]:
        if self.current().lexeme in {";", ")"}:
            return None
        return self.parse_expression()

    def parse_expression(self) -> ASTNode:
        return self.parse_assignment()

    def parse_assignment(self) -> ASTNode:
        left = self.parse_logical_or()
        if self.match("="):
            op = self.tokens[self.pos - 1]
            right = self.parse_assignment()
            return ASTNode("Operator", value=op.lexeme, line=op.line, children=[left, right])
        return left

    def parse_logical_or(self) -> ASTNode:
        node = self.parse_logical_and()
        while self.match("||"):
            op = self.tokens[self.pos - 1]
            rhs = self.parse_logical_and()
            node = ASTNode("Operator", value=op.lexeme, line=op.line, children=[node, rhs])
        return node

    def parse_logical_and(self) -> ASTNode:
        node = self.parse_equality()
        while self.match("&&"):
            op = self.tokens[self.pos - 1]
            rhs = self.parse_equality()
            node = ASTNode("Operator", value=op.lexeme, line=op.line, children=[node, rhs])
        return node

    def parse_equality(self) -> ASTNode:
        node = self.parse_relational()
        while self.current().lexeme in {"==", "!="}:
            op = self.advance()
            rhs = self.parse_relational()
            node = ASTNode("Operator", value=op.lexeme, line=op.line, children=[node, rhs])
        return node

    def parse_relational(self) -> ASTNode:
        node = self.parse_additive()
        while self.current().lexeme in {"<", ">", "<=", ">="}:
            op = self.advance()
            rhs = self.parse_additive()
            node = ASTNode("Operator", value=op.lexeme, line=op.line, children=[node, rhs])
        return node

    def parse_additive(self) -> ASTNode:
        node = self.parse_multiplicative()
        while self.current().lexeme in {"+", "-"}:
            op = self.advance()
            rhs = self.parse_multiplicative()
            node = ASTNode("Operator", value=op.lexeme, line=op.line, children=[node, rhs])
        return node

    def parse_multiplicative(self) -> ASTNode:
        node = self.parse_unary()
        while self.current().lexeme in {"*", "/", "%"}:
            op = self.advance()
            rhs = self.parse_unary()
            node = ASTNode("Operator", value=op.lexeme, line=op.line, children=[node, rhs])
        return node

    def parse_unary(self) -> ASTNode:
        token = self.current()
        if token.token_code not in CONSTANT_CODES and token.lexeme in {"!", "-", "+"}:
            op = self.advance()
            return ASTNode("Operator", value=op.lexeme, line=op.line, children=[self.parse_unary()])
        return self.parse_postfix()

    def parse_postfix(self) -> ASTNode:
        node = self.parse_primary()
        while self.match("("):
            args = self.parse_argument_list_opt()
            self.expect(")")
            if node.kind != "Leaf":
                self.error("call target must be identifier")
            node = ASTNode("Call", line=node.line, name=node.value, children=args)
        return node

    def parse_argument_list_opt(self) -> List[ASTNode]:
        args: List[ASTNode] = []
        if self.current().lexeme == ")":
            return args
        args.append(self.parse_expression())
        while self.match(","):
            args.append(self.parse_expression())
        return args

    def parse_primary(self) -> ASTNode:
        token = self.current()
        if self.match("("):
            expr = self.parse_expression()
            self.expect(")")
            return expr
        if token.token_code == IDENTIFIER_CODE:
            self.advance()
            return ASTNode("Leaf", value=token.lexeme, line=token.line)
        if token.token_code in CONSTANT_CODES:
            self.advance()
            return ASTNode("Leaf", value=token.lexeme, line=token.line)
        self.error("expected expression")

    def current(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        token = self.current()
        if not self.is_eof():
            self.pos += 1
        return token

    def match(self, lexeme: str) -> bool:
        if self.current().lexeme == lexeme:
            self.advance()
            return True
        return False

    def expect(self, lexeme: str) -> Token:
        if self.current().lexeme == lexeme:
            return self.advance()
        self.error("expected '%s'" % lexeme)

    def expect_identifier(self) -> Token:
        token = self.current()
        if token.token_code == IDENTIFIER_CODE:
            return self.advance()
        self.error("expected identifier")

    def expect_type(self) -> Token:
        token = self.current()
        if self.is_type_token(token):
            return self.advance()
        self.error("expected type")

    def is_type_token(self, token: Token) -> bool:
        return token.lexeme in TYPE_KEYWORDS

    def is_eof(self) -> bool:
        return self.current().token_code == EOF_CODE

    def error(self, message: str) -> None:
        token = self.current()
        got = token.lexeme or "EOF"
        raise ParserError("Line %s: %s, got '%s'" % (token.line, message, got))


QuadArg = Union[str, int]


@dataclass
class Quad:
    operator: str
    arg1: QuadArg = "_"
    arg2: QuadArg = "_"
    result: QuadArg = "_"


@dataclass
class BoolJumps:
    true_list: List[int]
    false_list: List[int]


@dataclass
class LoopContext:
    break_list: List[int]
    continue_list: List[int]
    continue_target: Optional[int] = None


class IntermediateCodeGenerator:
    def __init__(self) -> None:
        self.quads: List[Quad] = []
        self.temp_counter = 0
        self.loop_stack: List[LoopContext] = []

    def generate(self, root: ASTNode) -> str:
        if root.kind != "Program":
            raise ValueError("AST root must be Program")

        for child in root.children:
            self.generate_toplevel(child)

        return self.format_quads()

    def generate_toplevel(self, node: ASTNode) -> None:
        if node.kind in {"FunctionDef", "FunctionDecl"}:
            self.generate_function(node)
        elif node.kind in {"VarDecl", "ConstDecl"}:
            self.generate_declaration(node)

    def generate_function(self, node: ASTNode) -> None:
        body = self.function_body(node)
        if body is None:
            return

        self.emit(node.name or "_")
        self.generate_compound(body)

        if node.type_name == "void" and not self.ends_with_ret():
            self.emit("ret", "_", "_", "_")

        if node.name == "main" and not self.ends_with_sys():
            self.emit("sys")

    def function_body(self, node: ASTNode) -> Optional[ASTNode]:
        if node.children and node.children[-1].kind == "Compound":
            return node.children[-1]
        return None

    def generate_compound(self, node: ASTNode) -> None:
        for child in node.children:
            if child.kind in {"VarDecl", "ConstDecl"}:
                self.generate_declaration(child)
            else:
                self.generate_statement(child)

    def generate_declaration(self, node: ASTNode) -> None:
        if node.children:
            value = self.generate_expression(node.children[0])
            self.emit("=", value, "_", node.name or "_")

    def generate_statement(self, node: ASTNode) -> None:
        if node.kind == "Compound":
            self.generate_compound(node)
        elif node.kind == "ExprStmt":
            if node.children:
                self.generate_expression(node.children[0])
        elif node.kind == "ReturnStmt":
            value = self.generate_expression(node.children[0]) if node.children else "_"
            self.emit("ret", "_", "_", value)
        elif node.kind == "IfStmt":
            self.generate_if(node)
        elif node.kind == "WhileStmt":
            self.generate_while(node)
        elif node.kind == "ForStmt":
            self.generate_for(node)
        elif node.kind == "DoWhileStmt":
            self.generate_do_while(node)
        elif node.kind == "BreakStmt":
            self.generate_break()
        elif node.kind == "ContinueStmt":
            self.generate_continue()
        elif node.children:
            self.generate_expression(node)

    def generate_if(self, node: ASTNode) -> None:
        condition = node.children[0]
        then_branch = node.children[1]
        else_branch = node.children[2] if len(node.children) > 2 else None

        jumps = self.generate_bool(condition)
        self.backpatch(jumps.true_list, self.next_quad())
        self.generate_statement(then_branch)

        if else_branch is None:
            end_target = self.next_quad()
            self.backpatch(jumps.false_list, end_target)
            return

        after_then = self.emit("J", "_", "_", 0)

        false_target = self.next_quad()
        self.backpatch(jumps.false_list, false_target)
        self.generate_statement(else_branch)

        end_target = self.next_quad()
        self.backpatch([after_then], end_target)

    def generate_while(self, node: ASTNode) -> None:
        condition_start = self.next_quad()
        jumps = self.generate_bool(node.children[0])
        self.backpatch(jumps.true_list, self.next_quad())

        context = LoopContext(break_list=[], continue_list=[], continue_target=condition_start)
        self.loop_stack.append(context)
        if len(node.children) > 1:
            self.generate_statement(node.children[1])
        self.loop_stack.pop()

        self.emit("J", "_", "_", condition_start)
        end_target = self.next_quad()
        self.backpatch(jumps.false_list, end_target)
        self.backpatch(context.break_list, end_target)
        self.backpatch(context.continue_list, condition_start)

    def generate_for(self, node: ASTNode) -> None:
        body = node.children[-1] if node.children else None
        expressions = node.children[:-1]
        init = expressions[0] if len(expressions) >= 1 else None
        condition = expressions[1] if len(expressions) >= 2 else None
        step = expressions[2] if len(expressions) >= 3 else None

        if init is not None:
            self.generate_expression(init)

        condition_start = self.next_quad()
        jumps: Optional[BoolJumps] = None
        if condition is not None:
            jumps = self.generate_bool(condition)

        step_start = self.next_quad()
        if step is not None:
            self.generate_expression(step)

        self.emit("J", "_", "_", condition_start)
        body_start = self.next_quad()
        if jumps is not None:
            self.backpatch(jumps.true_list, body_start)

        context = LoopContext(break_list=[], continue_list=[], continue_target=step_start)
        self.loop_stack.append(context)
        if body is not None:
            self.generate_statement(body)
        self.loop_stack.pop()

        if body is not None and not self.ends_with_control_jump(body):
            self.emit("J", "_", "_", step_start)

        end_target = self.next_quad()
        if jumps is not None:
            self.backpatch(jumps.false_list, end_target)
        self.backpatch(context.break_list, end_target)

    def generate_do_while(self, node: ASTNode) -> None:
        body_start = self.next_quad()
        body = node.children[0] if node.children else None
        condition = node.children[1] if len(node.children) > 1 else None

        context = LoopContext(break_list=[], continue_list=[])
        self.loop_stack.append(context)
        if body is not None:
            self.generate_statement(body)
        self.loop_stack.pop()

        condition_start = self.next_quad()
        self.backpatch(context.continue_list, condition_start)
        if condition is not None:
            jumps = self.generate_bool(condition)
            self.backpatch(jumps.true_list, body_start)
            end_target = self.next_quad()
            self.backpatch(jumps.false_list, end_target)
        else:
            end_target = self.next_quad()

        self.backpatch(context.break_list, end_target)

    def generate_break(self) -> None:
        target = self.emit("J", "_", "_", 0)
        if self.loop_stack:
            self.loop_stack[-1].break_list.append(target)

    def generate_continue(self) -> None:
        target = self.emit("J", "_", "_", 0)
        if self.loop_stack:
            context = self.loop_stack[-1]
            if context.continue_target is None:
                context.continue_list.append(target)
            else:
                self.backpatch([target], context.continue_target)

    def generate_expression(self, node: ASTNode) -> str:
        if node.kind == "Leaf":
            return node.value or "_"

        if node.kind == "Call":
            args = [self.generate_expression(child) for child in node.children]
            for arg in args:
                self.emit("para", arg, "_", "_")
            result = self.new_temp()
            self.emit("call", node.name or "_", "_", result)
            return result

        if node.kind != "Operator":
            if node.children:
                return self.generate_expression(node.children[0])
            return "_"

        if len(node.children) == 1:
            value = self.generate_expression(node.children[0])
            if node.value == "+":
                return value
            result = self.new_temp()
            if node.value == "-":
                self.emit("-", "0", value, result)
            else:
                self.emit(node.value or "_", value, "_", result)
            return result

        if node.value == "=":
            right = self.generate_expression(node.children[1])
            left = self.expression_place(node.children[0])
            self.emit("=", right, "_", left)
            return left

        left = self.generate_expression(node.children[0])
        right = self.generate_expression(node.children[1])
        result = self.new_temp()
        self.emit(node.value or "_", left, right, result)
        return result

    def expression_place(self, node: ASTNode) -> str:
        if node.kind == "Leaf":
            return node.value or "_"
        return self.generate_expression(node)

    def generate_bool(self, node: ASTNode) -> BoolJumps:
        if node.kind == "Operator" and node.value == "&&" and len(node.children) >= 2:
            left = self.generate_bool(node.children[0])
            self.backpatch(left.true_list, self.next_quad())
            right = self.generate_bool(node.children[1])
            return BoolJumps(right.true_list, left.false_list + right.false_list)

        if node.kind == "Operator" and node.value == "||" and len(node.children) >= 2:
            left = self.generate_bool(node.children[0])
            self.backpatch(left.false_list, self.next_quad())
            right = self.generate_bool(node.children[1])
            return BoolJumps(left.true_list + right.true_list, right.false_list)

        if node.kind == "Operator" and node.value == "!" and len(node.children) == 1:
            child = self.generate_bool(node.children[0])
            return BoolJumps(child.false_list, child.true_list)

        if node.kind == "Operator" and node.value in RELATIONAL_OPERATORS and len(node.children) >= 2:
            left = self.generate_expression(node.children[0])
            right = self.generate_expression(node.children[1])
            true_jump = self.emit("J" + (node.value or ""), left, right, 0)
            false_jump = self.emit("J", "_", "_", 0)
            return BoolJumps([true_jump], [false_jump])

        value = self.generate_expression(node)
        true_jump = self.emit("Jnz", value, "_", 0)
        false_jump = self.emit("J", "_", "_", 0)
        return BoolJumps([true_jump], [false_jump])

    def new_temp(self) -> str:
        self.temp_counter += 1
        return "t%d" % self.temp_counter

    def next_quad(self) -> int:
        return len(self.quads)

    def emit(
        self,
        operator: str,
        arg1: QuadArg = "_",
        arg2: QuadArg = "_",
        result: QuadArg = "_",
    ) -> int:
        self.quads.append(Quad(operator, arg1, arg2, result))
        return len(self.quads) - 1

    def backpatch(self, targets: Sequence[int], value: int) -> None:
        for target in targets:
            self.quads[target].result = value

    def ends_with_sys(self) -> bool:
        return bool(self.quads and self.quads[-1].operator == "sys")

    def ends_with_ret(self) -> bool:
        return bool(self.quads and self.quads[-1].operator == "ret")

    def ends_with_control_jump(self, node: ASTNode) -> bool:
        if node.kind in {"BreakStmt", "ContinueStmt", "ReturnStmt"}:
            return True
        if node.kind == "Compound" and node.children:
            return self.ends_with_control_jump(node.children[-1])
        if node.kind == "IfStmt" and len(node.children) > 2:
            return self.ends_with_control_jump(node.children[1]) and self.ends_with_control_jump(node.children[2])
        return False

    def format_quads(self) -> str:
        if not self.quads:
            return ""
        return "\n".join(
            "%d: (%s, %s, %s, %s)"
            % (
                index,
                self.format_arg(quad.operator),
                self.format_arg(quad.arg1),
                self.format_arg(quad.arg2),
                self.format_arg(quad.result),
            )
            for index, quad in enumerate(self.quads)
        ) + "\n"

    @staticmethod
    def format_arg(value: QuadArg) -> str:
        if isinstance(value, int):
            return str(value)
        return "'%s'" % value


def generate_output(source_text: str, check_semantic: bool = False) -> str:
    del check_semantic
    lexer = Lexer(source_text)
    tokens = lexer.tokenize()
    if lexer.errors:
        return "\n".join(lexer.errors) + "\n"

    try:
        ast = Parser(tokens).parse()
    except ParserError as exc:
        return str(exc) + "\n"

    return IntermediateCodeGenerator().generate(ast)


def main() -> int:
    base_dir = Path.cwd()
    source_text = (base_dir / "input.txt").read_text(encoding="utf-8-sig")
    output_text = generate_output(source_text)
    (base_dir / "output.txt").write_text(output_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
