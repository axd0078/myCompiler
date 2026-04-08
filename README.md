# myCompiler

一个使用 Python 编写的小型编译器前端练习项目。目前仓库已经完成两部分核心能力：

- `scanner.py`：把源代码扫描为 token 序列
- `parser.py`：把 token 流解析为抽象语法树（AST）

这份 README 按当前代码实现重新整理，重点说明词法分析和语法分析背后的算法设计，而不是只列功能清单。

## 当前实现

- 词法分析：支持关键字、标识符、整数、浮点数、字符常量、字符串、注释、运算符、界符
- 语法分析：支持常量声明、变量声明、函数声明、函数定义、复合语句
- 控制流语句：支持 `if/else`、`while`、`for`、`do while`、`break`、`continue`、`return`
- 表达式系统：支持赋值、逻辑与/或、相等比较、关系比较、加减乘除模、一元运算、函数调用
- AST 输出：使用缩进文本输出语法树，便于调试和样例比对
- 回归测试：`test/test.py` 会自动比对 `test/sample` 下的 5 组输入输出

## 项目结构

```text
myCompiler/
├── scanner.py          # 词法分析器
├── parser.py           # 递归下降语法分析器 + AST 输出
├── test/
│   ├── grammer.txt     # 当前语法定义（仓库文件名即 grammer）
│   ├── input.txt       # 语法分析示例输入
│   ├── output.txt      # 语法分析示例输出
│   ├── test.py         # 样例测试脚本
│   └── sample/         # 5 组 token 输入 / AST 输出样例
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
   │  构造: ASTNode(kind, value, type_name, name, children)
   ▼
AST text
```

项目目前把“词法分析”和“语法分析”分成两个独立阶段处理。这样的结构很适合教学和调试，因为我们可以先确认 token 是否正确，再观察 AST 是否正确。

## 词法分析算法实现

### 1. 单指针线性扫描

`scanner.py` 中的 `LexialAnalyzer` 维护 4 个核心状态：

- `source`：完整输入串
- `pos`：当前扫描位置
- `current_char`：当前位置字符
- `line`：当前行号

整个扫描过程是一次从左到右的线性遍历，不回退主指针。只有 `peek()` 会向前看 1 个字符，用于识别 `//`、`/*`、`==`、`<=`、`&&` 这类需要前瞻的模式。

核心调度逻辑在 `get_next_token()` 中，可以概括为：

```text
while current_char != '\0':
    先跳过空白和注释
    再根据当前字符分派到不同识别函数
        数字      -> read_number()
        标识符    -> read_identifier()
        字符常量  -> read_char_literal()
        字符串    -> read_string()
        运算符    -> read_operator()
        非法字符  -> 记录错误并恢复
```

这本质上是“有限状态机 + 手写分派器”的实现方式。状态没有显式写成图，而是拆散到了多个 `read_xxx()` 方法中。

### 2. 注释与空白的跳过策略

算法的第一步不是产出 token，而是消除无语义字符：

- `skip_whitespace()` 连续跳过空格、制表符、换行和回车
- `skip_comment()` 识别两类注释
- 单行注释 `//...`：一直跳到行尾
- 多行注释 `/*...*/`：一直扫描到 `*/`

多行注释的实现有一个关键点：它在循环里持续检查“当前字符是否为 `*` 且下一个字符是否为 `/`”。一旦直到文件结尾都没找到闭合符，就记录 `UNCLOSED_COMMENT(103)`。

### 3. 数字识别算法

`read_number()` 不是简单地“读到不是数字为止”，而是按前缀区分数值类别：

1. 以 `0` 开头
   - 后继是 `x` 或 `X`：进入 `read_hex_number()`，按十六进制读取
   - 后继是 `0-7`：按八进制连续读取
   - 后继是 `.`：按浮点数读取小数部分
   - 后继是 `8/9` 或字母：判为非法 token
   - 否则就是单独的 `0`
2. 以 `1-9` 开头
   - 先连续读取十进制整数部分
   - 如果后面接 `.`，继续读取小数部分并返回浮点数
   - 如果后面直接接字母或下划线，例如 `8_it5`，判为非法 token

这个实现的关键价值在于：它把“数值合法性检查”和“token 提取”合并在一次扫描里完成了，而不是先把字符串切出来再二次判断。

### 4. 字符常量和字符串的识别算法

#### 字符常量 `read_char_literal()`

字符常量的处理步骤是：

1. 先跳过开头的 `'`
2. 识别普通字符或转义字符
3. 检查是否存在合法的闭合 `'`
4. 若发现空字符常量、非法转义、多字符内容或缺失闭合，引发对应错误

当前实现支持的字符转义包括：`\n`、`\t`、`\r`、`\\`、`\'`、`\0`。

#### 字符串 `read_string()`

字符串扫描会一直读到下一个 `"` 或文件结束。它同样支持转义字符，并且在遇到非法转义时会向后跳过，直到字符串结束符、换行或文件结束，以避免同一处错误被重复上报。

### 5. 关键字与标识符识别

`read_identifier()` 的策略很直接：

- 只要当前字符属于“字母 / 数字 / 下划线”，就继续吸收
- 完整 lexeme 读出后，去 `KEYWORDS` 字典中查询
- 若命中关键字，返回关键字类型
- 否则返回 `IDENTIFIER(700)`

这属于典型的“最长匹配 + 保留字表查找”实现。

### 6. 运算符识别中的前瞻算法

`read_operator()` 先处理双字符运算符，再处理单字符运算符：

- 双字符：`==`、`<=`、`>=`、`!=`、`&&`、`||`
- 单字符：`+ - * / % = < > ! ( ) [ ] { } , ; .`

为什么要先判断双字符？因为如果先把 `=` 识别成单字符，就无法再组合出 `==`。这类问题本质上是词法分析里的“最长可匹配优先”。

### 7. 词法错误恢复策略

这份词法分析器不是“遇错即停”，而是尽量继续扫描：

- 非法字符会被批量跳过，避免一串非法字符触发多次相同报错
- 非法转义会跳到下一个引号或行尾，减少错误雪崩
- 所有错误都收集到 `self.errors` 中，最后统一输出

这是一种很适合教学项目的恢复方式，因为它既能给出错误位置，也能展示扫描器如何继续工作。

## 语法分析算法实现

### 1. 手写递归下降分析器

`parser.py` 使用的是手写递归下降（Recursive Descent Parser）。它的核心思想是：

- 每个非终结符对应一个 `parse_xxx()` 函数
- 当前 token 决定走哪条产生式
- 解析成功时返回 AST 节点
- 解析失败时通过 `ParserError` 立刻终止

这和 `test/grammer.txt` 中的语法定义是一一对应的。例如：

- `parse()` 对应 `<Program>`
- `parse_compound()` 对应 `<Compound>`
- `parse_statement()` 对应 `<Stmt>`
- `parse_expression()` 对应 `<Expr>`

### 2. 顶层声明的判定算法

C 风格语法里，顶层以类型关键字开头后，既可能是变量声明，也可能是函数声明/定义。`parse_toplevel_type_stmt()` 的处理方式是：

1. 先读取 `type`
2. 再读取标识符名称
3. 看下一个 token 是否为 `(`
   - 是：按函数继续分析
   - 否：按变量声明继续分析
4. 对函数再进一步区分
   - 参数列表后如果跟 `;`，说明是函数声明
   - 参数列表后如果跟复合语句 `{...}`，说明是函数定义

这一步实际上是在做“共享前缀消解”。因为变量和函数一开始都长得像 `type identifier`，必须读到更后面的符号才能决定产生式。

### 3. 语句解析的分派策略

`parse_statement()` 根据当前 token 的 `lexeme` 进行分派：

- `{` -> `parse_compound()`
- `if` -> `parse_if_stmt()`
- `while` -> `parse_while_stmt()`
- `for` -> `parse_for_stmt()`
- `do` -> `parse_do_while_stmt()`
- `return` -> `parse_return_stmt()`
- `continue` / `break` -> 直接构造对应语句节点
- 其他情况 -> 视为表达式语句 `parse_expr_stmt()`

这种做法的优点是结构清晰，几乎可以直接把文法翻译成代码。

### 4. 表达式优先级的实现方式

表达式不是用一条大文法一次性处理，而是拆成多层函数，每一层只负责一个优先级：

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
| 最高 | `parse_postfix()` / `parse_primary()` | 函数调用、字面量、标识符、括号表达式 | - |

这个设计非常重要，因为它把“优先级”和“结合性”直接编码进了控制流：

- 赋值使用递归 `left = parse_logical_or(); if '=' -> parse_assignment()`，因此是右结合
- 其他二元运算使用 `while` 循环不断吸收同级操作符，因此是左结合

例如表达式 `a - b - c` 会被构造成：

```text
- [line]
  - [line]
    a [line]
    b [line]
  c [line]
```

而 `a = b = c` 会被构造成右结合的赋值树。

### 5. `for` 和可选表达式的处理

`parse_for_stmt()` 对应的文法是：

```text
for (ExprOpt ; ExprOpt ; ExprOpt) Stmt
```

因此初始化、条件、更新三个位置都允许为空。代码里通过“先判断是否遇到分号或右括号”来决定是否调用 `parse_expression()`，这是一种很标准的可空产生式处理方式。

`return` 和普通表达式语句也用了同样的思路：

- `return;` 可以没有返回值
- 单独的 `;` 可以表示空表达式语句

### 6. 函数调用与后缀表达式

`parse_postfix()` 先解析基本表达式，再检查后面是否跟着 `(`。如果跟着，就进入函数调用分析：

1. 记录被调用者名字
2. 解析参数列表 `parse_argument_list_opt()`
3. 构造 `Call` 节点

这样 `foo(a, b + c)` 会生成一个 `Call(foo)` 节点，参数作为它的子节点保存。

### 7. AST 的构建方式

语法树节点统一由 `ASTNode` 表示，关键字段包括：

- `kind`：节点种类，例如 `FunctionDef`、`IfStmt`、`Operator`
- `line`：源代码行号
- `value`：运算符或叶子值
- `type_name`：声明相关节点的类型名
- `name`：函数名、变量名等
- `children`：子节点列表

解析器在“识别语法结构”的同时直接构造 AST，而不是先生成一棵具体语法树再二次压缩。这让实现更简洁，也更接近后续语义分析需要的结构。

### 8. AST 输出算法

`render_ast()` 的输出不是广度优先，也不是括号表达式，而是一次深度优先的先序遍历：

1. 访问当前节点
2. 根据缩进层级输出当前节点文本
3. 递归输出所有子节点

内部调用链是：

- `render_ast()` 创建结果列表
- `collect_lines()` 递归收集每一行
- `format_node()` 决定不同节点的字符串格式

因此输出结果既保留树结构，又非常方便人工阅读。样例如下：

```text
ExprStmt
  = [8]
    result [8]
    + [8]
      a [8]
      b [8]
```

## 当前支持的语法范围

详细文法见 `test/grammer.txt`，目前代码实际支持的核心结构如下：

```ebnf
Program        ::= TopLevel*
TopLevel       ::= ConstDecl | TypeLeadingDecl
TypeLeadingDecl::= type identifier ( FunctionTail | VarDeclRest )
FunctionTail   ::= "(" ParameterListOpt ")" ( ";" | Compound )
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
Postfix        ::= Primary [ "(" ArgumentListOpt ")" ]
Primary        ::= identifier | constant | "(" Expr ")"
```

## 输入与输出格式

### 1. 词法分析输入

`scanner.py` 默认读取仓库根目录下的 `1.txt`。

### 2. 词法分析输出

输出的每一行是一个 token，格式为：

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

`parser.py` 读取仓库根目录下的 `input.txt`，其内容就是上一步输出的 token 流。

### 4. 语法分析输出

`parser.py` 会把 AST 写入根目录下的 `output.txt`。

## 使用方法

### 1. 只运行词法分析

先在仓库根目录准备 `1.txt`，然后运行：

```powershell
python scanner.py
```

### 2. 从源码一路生成 AST

先准备源码文件 `1.txt`，再执行：

```powershell
python scanner.py > input.txt
python parser.py
Get-Content output.txt
```

这条命令链对应当前仓库的两阶段处理流程。

### 3. 运行样例测试

```powershell
python test/test.py
```

测试会对 `test/sample` 下的 5 组 token 输入和期望 AST 输出做逐组比对。

## 当前限制

- 目前还没有实现语义分析、符号表、类型检查、中间代码生成和目标代码生成
- 语法分析器当前直接读取 token 文本，而不是直接与 `scanner.py` 做进程级联动
- 语法错误采用 fail-fast 策略，遇到第一个语法错误就抛出 `ParserError`
- 当前语法覆盖的是一个教学版 C 风格子集，不包含数组、结构体、指针、复杂声明等特性

## 后续可扩展方向

- 把 `scanner.py` 与 `parser.py` 串成统一前端入口
- 在 AST 基础上补充符号表和语义检查
- 为 AST 节点增加更多语义属性
- 继续向中间代码生成、优化和目标代码生成推进

## 许可证

本项目采用 [MIT License](LICENSE)。

## 作者

- GitHub: [@axd0078](https://github.com/axd0078)

---

这是一个很适合学习“手写编译器前端”的小项目。当前代码最有价值的部分，不只是它支持了哪些语法，而是它把“扫描、前瞻、优先级、递归下降、AST 构造”这些经典算法都用非常直接的 Python 代码落了下来。
