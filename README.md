# myCompiler

一个使用 Python 编写的小型编译器前端练习项目。当前仓库已经实现三个前端阶段：

- `scanner.py`：把类 C 源代码扫描为 token 序列。
- `parser.py`：先对 token 流做语法错误检测；如果没有语法错误，再生成 AST 文本。
- `semantic.py`：读取 AST 文本，执行语义分析，并输出错误列表与符号表结果。

这份 README 以当前代码为准，重点说明词法分析、递归下降语法分析、错误恢复和语义分析的实现思路。

## 当前实现

- 词法分析：支持关键字、标识符、整数、浮点数、字符常量、字符串、注释、运算符、界符。
- 语法错误检测：支持缺失标识符、缺失分号、括号/花括号不匹配、赋值左值非法、二元运算缺少操作数、`do while` 缺少 `while` 等错误。
- 语法分析：支持常量声明、变量声明、数组后缀、函数声明、函数定义、复合语句和常见控制流语句。
- 语义分析：支持重定义、未声明标识符、函数声明/定义冲突、参数个数/类型错误、返回值类型错误、`break` 误用、常量赋值、算术操作数类型不匹配等检查。
- 输出策略：
  - `parser.py` 有语法错误时输出 `行号 错误码`，无语法错误时输出 AST 文本。
  - `semantic.py` 输出语义错误列表，并额外生成常量表、变量表和函数表。

## 项目结构

```text
myCompiler/
├── scanner.py          # 词法分析器
├── parser.py           # 错误检测 + 递归下降语法分析 + AST 输出
├── semantic.py         # 语义分析 + 符号表输出
├── .gitignore
├── LICENSE
└── README.md
```

## 前端处理流程

```text
source code
   │
   ▼
scanner.py
   │  输出: lexeme token_code line
   ▼
token stream
   │
   ▼
parser.py
   │  1. ErrorParser 做语法错误检测
   │  2. 有错误: 输出 line error_code
   │  3. 无错误: Parser 构建 AST 并渲染
   ▼
AST text
   │
   ▼
semantic.py
   │  1. 读取 AST 文本
   │  2. 作用域/符号表分析
   │  3. 输出语义错误和符号表
   ▼
semantic errors + const.txt + var.txt + function.txt
```

当前三个阶段是解耦的。这样做的代价是输入输出文件需要人工衔接，但好处是每一层都可以单独验证和调试。

## 词法分析算法实现

### 1. 单指针线性扫描

`scanner.py` 中的 `LexialAnalyzer` 维护 `source`、`pos`、`current_char`、`line` 这几个核心状态。扫描过程从左到右推进，主指针不回退；只有 `peek()` 会向前看 1 个字符，用于判断 `//`、`/*`、`==`、`<=`、`&&` 等需要前瞻的模式。

核心分派逻辑在 `get_next_token()` 中：

```text
while current_char != '\0':
    跳过空白和注释
    数字      -> read_number()
    标识符    -> read_identifier()
    字符常量  -> read_char_literal()
    字符串    -> read_string()
    运算符    -> read_operator()
    非法字符  -> 记录错误并恢复
```

这相当于一个手写有限状态机：不同状态没有集中写成状态表，而是拆到多个 `read_xxx()` 方法里。

### 2. 注释和空白跳过

- `skip_whitespace()` 连续跳过空格、制表符、换行和回车。
- `skip_comment()` 支持 `//` 单行注释和 `/* ... */` 多行注释。
- 多行注释通过检查“当前字符为 `*` 且下一个字符为 `/`”来寻找闭合位置。
- 如果多行注释到文件末尾仍未闭合，会记录 `UNCLOSED_COMMENT(103)`。

### 3. 数字识别

`read_number()` 根据首字符分支处理：

- `0x` / `0X` 开头：进入 `read_hex_number()`，按十六进制读取。
- `0` 后接 `0-7`：按八进制读取。
- `0` 或普通十进制整数后接 `.`：读取浮点数小数部分。
- 数字后直接接字母或下划线，例如 `8_it5`：记录非法 token。
- 小数点后没有数字、十六进制后没有有效字符、八进制中出现 `8/9`：记录非法 token。

这个函数把 token 提取和数值合法性检查合在一次扫描中完成。

### 4. 字符和字符串

`read_char_literal()` 会检查空字符常量、非法转义、多字符常量和未闭合单引号。当前字符转义支持 `\n`、`\t`、`\r`、`\\`、`\'`、`\0`。

`read_string()` 会一直扫描到闭合双引号或文件结束。遇到非法转义时，会跳到下一个双引号、换行或文件结束，以减少同一处错误引发的重复报错。

### 5. 关键字、标识符和运算符

`read_identifier()` 使用“最长匹配 + 关键字表查询”：先连续读取字母、数字和下划线，再去 `KEYWORDS` 中判断是否为关键字；否则返回 `IDENTIFIER(700)`。

`read_operator()` 先处理双字符运算符，再处理单字符运算符。这样能保证 `==`、`<=`、`>=`、`!=`、`&&`、`||` 按最长匹配识别，而不会被提前拆成两个单字符 token。

## 语法分析算法实现

### 1. 双解析器结构

`parser.py` 里有两个解析器：

- `ErrorParser`：只负责语法错误检测和错误恢复，返回 `(line, error_code)` 列表。
- `Parser`：在没有语法错误时构建 AST，用于保留合法输入的结构化输出能力。

`generate_output()` 的核心流程是：

```text
tokens = load_tokens_from_text(input_text)
errors = ErrorParser(tokens).parse()
if errors:
    return format_errors(errors)
return render_ast(Parser(tokens).parse())
```

### 2. `ErrorParser` 的递归下降检测

`ErrorParser` 仍然按递归下降思路组织：每类语法结构对应一个 `parse_xxx()` 方法。

- `parse_type_leading_decl()`：处理以类型关键字开头的顶层或局部声明。
- `parse_const_decl()`：处理常量声明。
- `parse_compound()`：处理复合语句和块内项目。
- `parse_statement()`：按当前 token 分派到 `if`、`while`、`for`、`do while`、`return` 等语句。
- `parse_expression()`：进入表达式优先级链。

与旧版本不同的是，`ErrorParser` 不构造 AST，而是在发现错误时调用 `record_error()`，然后用同步集合跳过局部错误区域并继续分析。

### 3. 声明与函数的共享前缀消解

类 C 语法里，变量声明和函数声明/定义都以 `type identifier` 开头。当前实现的判定流程是：

```text
type identifier ArraySuffix
    后面是 '(' / ')' / '{' -> 按函数声明或函数定义处理
    否则                  -> 按变量声明处理
```

`parse_array_suffix()` 支持形如 `a[10]`、`a[]`、`a[x + 1]` 的数组后缀，并且在 `]`、`,`、`;`、`=`、`)`、`}` 等位置同步恢复。

### 4. 语句分派

`parse_statement()` 通过当前 token 的 `lexeme` 做分派：

- `{` -> 复合语句
- `if` -> `parse_if_stmt()`
- `while` -> `parse_while_stmt()`
- `for` -> `parse_for_stmt()`
- `do` -> `parse_do_while_stmt()`
- `return` -> `parse_return_stmt()`
- `continue` / `break` -> 读取关键字后检查分号
- `)` / `}` -> 记录多余右括号或右花括号
- 其他情况 -> 按表达式语句处理

这种做法的目的不是一次性中止，而是尽量把错误限制在局部结构里。

### 5. 表达式优先级和左值检查

表达式按优先级拆成多层函数：

| 优先级 | 对应函数 | 典型运算符 | 结合性 |
| --- | --- | --- | --- |
| 最低 | `parse_assignment()` | `=` | 右结合 |
|  | `parse_logical_or()` | `||` | 左结合 |
|  | `parse_logical_and()` | `&&` | 左结合 |
|  | `parse_equality()` | `==`, `!=` | 左结合 |
|  | `parse_relational()` | `<`, `>`, `<=`, `>=` | 左结合 |
|  | `parse_additive()` | `+`, `-` | 左结合 |
|  | `parse_multiplicative()` | `*`, `/`, `%` | 左结合 |
|  | `parse_unary()` | `!`, unary `+`, unary `-` | 右结合 |
| 最高 | `parse_postfix()` / `parse_primary()` | 函数调用、常量、标识符、括号表达式 | - |

为了检测赋值左值是否合法，表达式解析返回 `ExprInfo`。其中 `is_lvalue=True` 只会由标识符产生；如果 `parse_assignment()` 发现 `1 = a` 或 `(a + b) = c` 这类左侧不可赋值表达式，就记录 `ERROR_ASSIGN_LHS(210)`。

### 6. 错误恢复策略

`ErrorParser` 的错误恢复主要依靠三个机制：

- `record_error()`：记录 `(line, code)`，并用 `error_lines` 保证同一行最多输出一个错误。
- `sync_to(stop_lexemes)`：跳到局部同步符号，例如 `;`、`)`、`}`、`,`。
- `sync_expression_tail()`：表达式出错时跳到 `;`、`)`、`}`、`]`、`,`、`{` 等表达式边界。

缺失符号类错误采用“虚拟插入”的思路：例如缺少 `(`、`)`、`;` 时，记录错误但不强制消耗当前 token，让后续结构尽量继续分析。多余的 `)` 或 `}` 则会记录错误并直接跳过当前 token。

## 语法错误码

| 错误码 | 常量名 | 含义 |
| --- | --- | --- |
| 201 | `ERROR_MISSING_IDENTIFIER` | 缺少标识符 |
| 202 | `ERROR_MISSING_SEMICOLON` | 缺少分号 |
| 203 | `ERROR_EXTRA_RBRACE` | 多余的 `}` |
| 204 | `ERROR_MISSING_LBRACE` | 缺少 `{` |
| 205 | `ERROR_MISSING_RBRACE` | 缺少 `}` |
| 206 | `ERROR_EXTRA_RPAREN` | 多余的 `)` |
| 207 | `ERROR_MISSING_LPAREN` | 缺少 `(` |
| 208 | `ERROR_MISSING_RPAREN` | 缺少 `)` |
| 210 | `ERROR_ASSIGN_LHS` | 赋值号左侧不是合法左值 |
| 211 | `ERROR_BINARY_OPERAND` | 二元运算符或表达式位置缺少操作数 |
| 212 | `ERROR_DO_WHILE_MISSING_WHILE` | `do` 语句后缺少 `while` |

语法错误输出格式固定为：

```text
line error_code
```

如果没有语法错误，则输出 AST 文本。

## 语义分析算法实现

### 1. 输入模型

`semantic.py` 的输入不是 token 流，而是 AST 文本。它首先通过 `parse_ast_text()` 把缩进文本恢复成 `ASTNode` 树：

- `parse_ast_line()` 用正则识别 `FunctionDef(...)`、`VarDecl(...)`、`Call(...)`、`ReturnStmt[...]`、`Leaf`、`Operator` 等节点。
- `parse_ast_text()` 根据缩进深度维护栈，把每一行节点挂回父节点，重建树结构。

这一步的意义是把 parser 的文本输出转回可遍历的树，避免手动处理字符串级语义分析。

### 2. 作用域和符号表

语义分析器围绕四类数据结构组织：

- `Scope`：保存当前作用域编号、父作用域和名字表。
- `Symbol`：记录普通名字的类型、行号、作用域、种类和角色。
- `FunctionSymbol`：记录函数返回类型、参数类型和声明/定义状态。
- `FunctionContext`：跟踪当前函数的返回类型、结束行和 return 使用状态。

`SemanticAnalyzer.new_scope()` 会为全局作用域、函数体和复合语句创建新作用域。变量和常量通过 `declare_symbol()` 落到当前作用域；函数信息单独保存在 `self.functions` 中。

### 3. 顶层与函数分析

`analyze_toplevel()` 会把顶层节点分发到：

- `handle_const_decl()`
- `handle_var_decl()`
- `handle_function()`

`handle_function()` 的关键工作有三件：

1. 校验函数声明/定义是否与已有签名冲突。
2. 为参数建立函数级作用域符号。
3. 创建 `FunctionContext`，进入函数体递归分析，并在函数末尾统一判断返回值是否符合返回类型约束。

这意味着函数重定义和返回值错误不是在表达式阶段零散检查，而是在函数级别集中收口。

### 4. 语句与循环检查

`analyze_statement()` 负责递归遍历语句节点：

- `ExprStmt`：分析表达式。
- `ReturnStmt`：由 `handle_return()` 检查返回值类型。
- `IfStmt` / `WhileStmt` / `ForStmt` / `DoWhileStmt`：先检查条件表达式，再分析子语句。
- `BreakStmt`：如果 `loop_depth == 0`，记录 `ERROR_BREAK_USAGE(308)`。
- `Compound`：创建子作用域继续分析。

这里的 `loop_depth` 是语义分析里一个关键的上下文变量，它直接决定 `break` 是否合法。

### 5. 表达式类型传播

`analyze_expression()` 返回 `ExprResult`，其中包含：

- `type_name`：当前表达式推导出的类型。
- `symbol`：如果表达式直接对应某个符号，则返回该符号引用。
- `is_lvalue`：是否可作为赋值左值。

处理规则是：

- `Leaf`：优先查找作用域中的符号；找不到再判断是否为字面量；仍然不是则报未声明错误。
- `Call`：检查函数是否已声明，再检查参数个数和参数类型。
- `Operator`：
  - `=`：检查赋值目标是否为常量或不可赋值目标。
  - 算术运算：比较左右类型类别是否一致，不一致时报 `ERROR_OPERAND_TYPE(310)`。
  - 关系/逻辑运算：结果按 `int` 处理。

这里用 `type_category()` 把 `float` / `double` 统一归到 `real`，减少字面类型差异带来的误报。

### 6. 表和错误输出

`AnalysisResult` 最终包含四类结果：

- `errors`
- `const_table`
- `var_table`
- `function_table`

`write_result_files()` 会把这些结果写到当前目录：

- `output.txt`：语义错误列表，格式为 `line error_code`
- `const.txt`：常量表
- `var.txt`：变量表
- `function.txt`：函数表

如果没有语义错误，`output.txt` 为空串，但三张表仍然会照常输出。

## 语义错误码

| 错误码 | 常量名 | 含义 |
| --- | --- | --- |
| 301 | `ERROR_NAME_REDEFINED` | 标识符重定义 |
| 302 | `ERROR_NAME_UNDECLARED` | 标识符未声明 |
| 303 | `ERROR_FUNCTION_REDEFINED` | 函数重定义或声明/定义冲突 |
| 304 | `ERROR_FUNCTION_UNDECLARED` | 函数未声明 |
| 305 | `ERROR_ARGUMENT_COUNT` | 函数实参与形参数量不一致 |
| 306 | `ERROR_ARGUMENT_TYPE` | 函数实参与形参类型不一致 |
| 307 | `ERROR_RETURN_MISMATCH` | 返回值类型与函数声明不匹配 |
| 308 | `ERROR_BREAK_USAGE` | `break` 不在循环体内 |
| 309 | `ERROR_ASSIGN_TO_CONST` | 对常量赋值 |
| 310 | `ERROR_OPERAND_TYPE` | 算术操作数类型不匹配 |

## 当前支持的语法范围

核心语法结构如下：

```ebnf
Program        ::= TopLevel*
TopLevel       ::= ConstDecl | TypeLeadingDecl
TypeLeadingDecl::= type identifier ArraySuffix ( FunctionTail | VarDeclRest )
FunctionTail   ::= "(" ParameterListOpt ")" ( ";" | Compound )
ArraySuffix    ::= "[" ExprOpt "]" ArraySuffix | ε
Stmt           ::= Compound
                 | IfStmt
                 | WhileStmt
                 | ForStmt
                 | DoWhileStmt
                 | ReturnStmt
                 | ContinueStmt
                 | BreakStmt
                 | ExprStmt
Expr           ::= Assignment
Assignment     ::= LogicalOr [ "=" Assignment ]
LogicalOr      ::= LogicalAnd { "||" LogicalAnd }
LogicalAnd     ::= Equality { "&&" Equality }
Equality       ::= Relational { ("==" | "!=") Relational }
Relational     ::= Additive { ("<" | ">" | "<=" | ">=") Additive }
Additive       ::= Multiplicative { ("+" | "-") Multiplicative }
Multiplicative ::= Unary { ("*" | "/" | "%") Unary }
Unary          ::= ("!" | "+" | "-") Unary | Postfix
Postfix        ::= Primary { "(" ArgumentListOpt ")" }
Primary        ::= identifier | constant | "(" ExprOpt ")"
```

## 输入与输出格式

### 1. 词法分析输入与输出

`scanner.py` 默认读取仓库根目录下的 `1.txt`，输出格式为：

```text
lexeme token_code line
```

### 2. 语法分析输入与输出

`parser.py` 默认读取仓库根目录下的 `input.txt`（token 流文本），把结果写入 `output.txt`：

- 如果存在语法错误，输出 `line error_code`。
- 如果没有语法错误，输出 AST 文本。

### 3. 语义分析输入与输出

`semantic.py` 默认读取仓库根目录下的 `input.txt`（AST 文本），并写出：

- `output.txt`：语义错误列表
- `const.txt`：常量表
- `var.txt`：变量表
- `function.txt`：函数表

注意：`semantic.py` 的输入必须是 AST 文本，而不是 token 流，也不是 parser 的语法错误列表。

## 使用方法

### 1. 只运行词法分析

```powershell
python scanner.py
```

前提：仓库根目录已有 `1.txt`。

### 2. 运行语法分析

```powershell
python scanner.py > input.txt
python parser.py
Get-Content output.txt
```

### 3. 运行语义分析

先准备一份 AST 文本为 `input.txt`，再执行：

```powershell
python semantic.py
Get-Content output.txt
Get-Content const.txt
Get-Content var.txt
Get-Content function.txt
```

如果你要把 parser 的合法输出继续送入语义分析，需要先把 parser 生成的 AST 文本保存为 `semantic.py` 读取的 `input.txt`。

## 当前限制

- 三个阶段还没有打通成统一命令行流水线，文件需要人工衔接。
- `parser.py` 的错误检测是教学版恢复策略，同一行最多输出一个语法错误。
- `semantic.py` 依赖 AST 文本格式稳定，属于“文本 AST -> 树 -> 语义分析”的实现路径，不是直接复用 parser 内部 AST 对象。
- 目前还没有实现中间代码生成、优化和目标代码生成。
- 当前语法和语义规则覆盖的是教学版 C 风格子集，不包含结构体、指针、复杂声明等完整 C 语言特性。

## 后续可扩展方向

- 把 `scanner.py`、`parser.py`、`semantic.py` 串成统一前端命令。
- 让 `semantic.py` 直接复用 parser 内部 AST，而不是重新解析文本 AST。
- 在语义分析基础上继续推进中间代码生成、优化和目标代码生成。
- 补充更系统的测试输入和结果校验。

## 许可证

本项目采用 [MIT License](LICENSE)。

## 作者

- GitHub: [@axd0078](https://github.com/axd0078)

---

这个项目当前已经具备一个教学版编译器前端的完整骨架：词法扫描、语法错误检测、合法输入 AST 生成，以及基于 AST 文本的语义分析与符号表输出。
