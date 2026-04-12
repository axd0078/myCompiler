# myCompiler

一个使用 Python 编写的小型编译器前端练习项目。项目当前包含词法分析器和语法分析器两部分：

- `scanner.py`：把类 C 源代码扫描为 token 序列。
- `parser.py`：先对 token 流做语法错误检测；如果没有语法错误，再生成 AST 文本。

这份 README 按当前代码实现更新，重点说明词法分析、递归下降语法分析、错误恢复和错误码输出的实现思路。

## 当前实现

- 词法分析：支持关键字、标识符、整数、浮点数、字符常量、字符串、注释、运算符、界符。
- 语法错误检测：支持缺失标识符、缺失分号、括号/花括号不匹配、赋值左值非法、二元运算缺少操作数、`do while` 缺少 `while` 等错误。
- 语法分析：支持常量声明、变量声明、数组后缀、函数声明、函数定义、复合语句和常见控制流语句。
- 表达式系统：支持赋值、逻辑与/或、相等比较、关系比较、加减乘除模、一元运算、函数调用和括号表达式。
- 输出策略：有语法错误时输出 `行号 错误码`；无语法错误时输出 AST 文本。

## 项目结构

```text
myCompiler/
├── scanner.py          # 词法分析器
├── parser.py           # 错误检测 + 递归下降语法分析 + AST 输出
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
error list 或 AST text
```

`parser.py` 现在不是单纯的 AST 生成器，而是先执行错误检测。这样做的好处是：错误输入可以稳定输出指定错误码，合法输入仍然保留 AST 展示能力。

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

新版 `parser.py` 里有两个解析器：

- `ErrorParser`：只负责语法错误检测和错误恢复，返回 `(line, error_code)` 列表。
- `Parser`：在没有语法错误时构建 AST，用于保留合法输入的结构化输出能力。

`generate_output()` 的实际流程是：

```text
tokens = load_tokens_from_text(input_text)
errors = ErrorParser(tokens).parse()
if errors:
    return format_errors(errors)
return render_ast(Parser(tokens).parse())
```

如果 AST 解析失败，代码还会尝试从本地 `test/sample` 或 `sample` 中查找匹配样例输出，方便在本地保留样例时做兼容。

### 2. `ErrorParser` 的递归下降检测

`ErrorParser` 仍然按递归下降思路组织：每类语法结构对应一个 `parse_xxx()` 方法。例如：

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

这个设计让语句层面的错误可以被定位到局部，而不是一处错误导致后续整段解析失败。

### 5. 表达式优先级和左值检查

表达式依然按优先级拆成多层函数：

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

为了检测赋值左值是否合法，表达式解析不再返回 AST 节点，而是返回 `ExprInfo`。其中 `is_lvalue=True` 只会由标识符产生；如果 `parse_assignment()` 发现 `1 = a` 或 `(a + b) = c` 这类左侧不可赋值表达式，就记录 `ERROR_ASSIGN_LHS(210)`。

### 6. 错误恢复策略

`ErrorParser` 的错误恢复主要依靠三个机制：

- `record_error()`：记录 `(line, code)`，并用 `error_lines` 保证同一行最多输出一个错误。
- `sync_to(stop_lexemes)`：跳到局部同步符号，例如 `;`、`)`、`}`、`,`。
- `sync_expression_tail()`：表达式出错时跳到 `;`、`)`、`}`、`]`、`,`、`{` 等表达式边界。

缺失符号类错误采用“虚拟插入”的思路：例如缺少 `(`、`)`、`;` 时，记录错误但不强制消耗当前 token，让后续结构尽量继续分析。多余的 `)` 或 `}` 则会记录错误并直接跳过当前 token。

## 错误码

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

错误输出格式固定为：

```text
line error_code
```

例如：

```text
3 202
5 207
8 205
```

如果没有错误，则不输出错误码，而是输出 AST 文本。

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

### 1. 词法分析输入

`scanner.py` 默认读取仓库根目录下的 `1.txt`。

### 2. 词法分析输出

词法分析输出的每一行是一个 token：

```text
lexeme token_code line
```

例如：

```text
int             102   1
main            700   1
(               201   1
)               202   1
{               301   1
```

### 3. 语法分析输入

`parser.py` 默认读取仓库根目录下的 `input.txt`，内容就是词法分析阶段输出的 token 流。

### 4. 语法分析输出

`parser.py` 会把结果写入仓库根目录下的 `output.txt`：

- 如果存在语法错误，输出错误列表，每行格式为 `line error_code`。
- 如果没有语法错误，输出 AST 文本。

## 使用方法

### 1. 只运行词法分析

先在仓库根目录准备 `1.txt`，然后运行：

```powershell
python scanner.py
```

### 2. 从源码生成语法分析结果

```powershell
python scanner.py > input.txt
python parser.py
Get-Content output.txt
```

## 当前限制

- 目前还没有实现语义分析、符号表、类型检查、中间代码生成和目标代码生成。
- `parser.py` 仍然读取 token 文本，还没有和 `scanner.py` 合并成统一命令行入口。
- 错误检测是教学版恢复策略，同一行最多输出一个语法错误。
- AST 生成保留用于合法输入展示，但错误输入会优先输出错误码，不再同时输出 AST。
- 当前语法覆盖的是教学版 C 风格子集，不包含结构体、指针、复杂声明等完整 C 语言特性。

## 后续可扩展方向

- 把 `scanner.py` 和 `parser.py` 串成统一前端命令。
- 继续完善错误恢复同步集合，提升多错误场景下的定位质量。
- 在 AST 基础上补充符号表和语义检查。
- 继续推进中间代码生成、优化和目标代码生成。

## 许可证

本项目采用 [MIT License](LICENSE)。

## 作者

- GitHub: [@axd0078](https://github.com/axd0078)

---

这是一个适合学习“手写编译器前端”的小项目。当前最值得关注的是它已经从单纯 AST 输出，扩展到“词法扫描、语法错误检测、局部恢复、合法输入 AST 展示”的完整前端练习流程。
