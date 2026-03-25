# myCompiler

自己动手实现一个编译器，包含词法分析、语法分析等功能。

## 项目简介

这是一个从零开始实现的编译器项目，旨在深入理解编译原理和程序语言设计的核心概念。目前项目已实现词法分析器（Scanner），后续将逐步添加语法分析、语义分析、中间代码生成、代码优化和目标代码生成等模块。

## 已实现功能

### 词法分析器 (scanner.py)

词法分析器负责将源代码转换为Token序列，目前支持以下特性：

#### 关键字
- 数据类型：`char`, `int`, `float`, `void`
- 控制流：`if`, `else`, `for`, `while`, `do`, `break`, `continue`, `return`
- 其他：`const`

#### 数据类型
- **整数**：支持十进制、八进制（以0开头）、十六进制（以0x/0X开头）
- **浮点数**：支持小数形式（如 `3.14`, `0.5`）
- **字符常量**：支持普通字符和转义字符（如 `'a'`, `'\n'`, `'\t'`）
- **字符串**：支持双引号字符串，包含转义字符处理（如 `"hello"`, `"line1\nline2"`）
- **标识符**：以字母或下划线开头，后跟字母、数字或下划线

#### 运算符
- 算术运算符：`+`, `-`, `*`, `/`, `%`
- 关系运算符：`<`, `<=`, `>`, `>=`, `==`, `!=`
- 逻辑运算符：`&&`, `||`, `!`
- 赋值运算符：`=`
- 其他：`.`（成员访问）

#### 界符
- 括号：`()`, `{}`, `[]`
- 分隔符：`;`, `,`

#### 注释支持
- 单行注释：`// 注释内容`
- 多行注释：`/* 注释内容 */`

#### 错误处理
词法分析器能够识别并报告以下错误：
- 非法字符（如 `@`, `#`, `$` 等）
- 无效的词法单元（如小数点后无数字）
- 未闭合的注释（缺少 `*/`）
- 未闭合的字符常量（缺少 `'`）
- 未闭合的字符串（缺少 `"`）

### 状态转换详解

词法分析器本质上是一个有限状态自动机（DFA），通过字符驱动在不同状态之间进行转换。以下是各个状态及其转换关系的详细说明。

#### 状态总览

| 状态名 | 对应方法 | 说明 |
|--------|----------|------|
| START | `get_next_token()` | 初始状态，根据当前字符分派到各子状态 |
| SKIP_WS | `skip_whitespace()` | 跳过空白字符 |
| SKIP_LINE_COMMENT | `skip_comment()` (单行) | 跳过 `//` 单行注释 |
| SKIP_BLOCK_COMMENT | `skip_comment()` (多行) | 跳过 `/* */` 多行注释 |
| IN_CHAR | `read_char_literal()` | 识别字符常量 |
| IN_STRING | `read_string()` | 识别字符串 |
| IN_NUMBER | `read_number()` | 识别整数和浮点数 |
| IN_HEX | `read_hex_number()` | 识别十六进制数 |
| IN_ID | `read_identifier()` | 识别标识符和关键字 |
| IN_OP | `read_operator()` | 识别运算符和界符 |

#### 1. START 状态（初始分派）

`get_next_token()` 方法是状态机的入口，根据当前字符决定进入哪个子状态：

```
START:
  ├─ 当前字符 ∈ {'@', '#', '$', 中文字符}
  │     → 报错 ILLEGAL_CHAR(101)，跳过所有连续非法字符，回到 START
  │
  ├─ 当前字符 ∈ {' ', '\t', '\n', '\r'}
  │     → 进入 SKIP_WS，跳过后回到 START
  │
  ├─ 当前字符为 '/' 且下一字符为 '/'
  │     → 进入 SKIP_LINE_COMMENT，跳过后回到 START
  │
  ├─ 当前字符为 '/' 且下一字符为 '*'
  │     → 进入 SKIP_BLOCK_COMMENT，跳过后回到 START
  │
  ├─ 当前字符为 '\''（单引号）
  │     → 进入 IN_CHAR，返回 CHAR_LITERAL Token 或报错
  │
  ├─ 当前字符为 '"'（双引号）
  │     → 进入 IN_STRING，返回 STRING Token 或报错
  │
  ├─ 当前字符为数字 [0-9]
  │     → 进入 IN_NUMBER，返回 NUMBER/FLOAT_NUM Token 或报错
  │
  ├─ 当前字符为字母或 '_'
  │     → 进入 IN_ID，返回 关键字/IDENTIFIER Token
  │
  ├─ 当前字符为运算符或界符字符
  │     → 进入 IN_OP，返回运算符/界符 Token 或报错
  │
  └─ 当前字符为 '\0'（文件结束）
        → 返回 EOF Token
```

#### 2. SKIP_WS 状态（跳过空白）

```
SKIP_WS:
  while 当前字符 ∈ {' ', '\t', '\n', '\r'}:
      advance()          // 前进，遇到 '\n' 时行号 +1
  → 回到 START
```

#### 3. SKIP_LINE_COMMENT 状态（单行注释 `//`）

```
SKIP_LINE_COMMENT:
  while 当前字符 ≠ '\0' 且 当前字符 ≠ '\n':
      advance()
  → 回到 START           // 到达行尾或文件末尾，注释结束
```

#### 4. SKIP_BLOCK_COMMENT 状态（多行注释 `/* */`）

```
SKIP_BLOCK_COMMENT:
  advance()               // 跳过 '/'
  advance()               // 跳过 '*'
  while 当前字符 ≠ '\0':
      ├─ 当前字符为 '*' 且下一字符为 '/'
      │     advance(); advance()    // 跳过 '*/'
      │     → 回到 START            // 注释正常闭合
      └─ 否则
            advance()               // 继续扫描
  → 若到达 '\0'：报错 UNCLOSED_COMMENT(103)
```

#### 5. IN_CHAR 状态（字符常量识别）

```
IN_CHAR:
  advance()                        // 跳过开头的 '
  ├─ 当前字符为 '\0'
  │     → 报错 UNCLOSED_CHAR(104)
  │
  ├─ 当前字符为 '\''（空字符常量 ''）
  │     → 报错 INVALID_TOKEN(102)，advance() 跳过第二个 '
  │
  ├─ 当前字符为 '\\'（转义字符）
  │     advance()
  │     ├─ 转义字符 ∈ {n, t, r, \, ', 0}
  │     │     → 记录转义值，advance()，进入检查闭合引号
  │     └─ 否则
  │           → 报错 INVALID_TOKEN(102)，跳至下一个 ' 或行尾
  │
  └─ 普通字符
        → 记录字符值，advance()，进入检查闭合引号

  检查闭合引号:
  ├─ 当前字符为 '\''
  │     advance()                  // 跳过闭合的 '
  │     → 返回 CHAR_LITERAL Token (类型码 500)
  ├─ 当前字符为字母（多字符字面量，如 'ab'）
  │     → 报错 INVALID_TOKEN(102)，跳至下一个 ' 或行尾
  └─ 否则
        → 报错 UNCLOSED_CHAR(104)
```

#### 6. IN_STRING 状态（字符串识别）

```
IN_STRING:
  advance()                        // 跳过开头的 "
  while 当前字符 ≠ '\0' 且 当前字符 ≠ '"':
      ├─ 当前字符为 '\\'（转义）
      │     advance()
      │     ├─ '\0' → 报错 UNCLOSED_STRING(105)，返回
      │     ├─ 转义字符 ∈ {n, t, r, \, "} → 追加转义值
      │     └─ 否则 → 报错 INVALID_TOKEN(102)，跳至 " 或行尾
      └─ 普通字符
            → 追加到 lexeme

  ├─ 当前字符为 '"'
  │     advance()                  // 跳过闭合的 "
  │     → 返回 STRING Token (类型码 600)
  └─ 否则（到达 '\0'）
        → 报错 UNCLOSED_STRING(105)
```

#### 7. IN_NUMBER 状态（数字识别）

数字识别是状态转换最复杂的部分，根据首字符分多条路径：

```
IN_NUMBER:
  ├─ 首字符为 '0':
  │     advance()
  │     ├─ 下一字符 ∈ {'x', 'X'}
  │     │     → 进入 IN_HEX（十六进制识别）
  │     │
  │     ├─ 下一字符 ∈ {'0'-'7'}（八进制）
  │     │     while 当前字符 ∈ {'0'-'7'}:
  │     │         追加到 lexeme, advance()
  │     │     → 返回 NUMBER Token (类型码 400)
  │     │
  │     ├─ 下一字符为 '.'（浮点数 0.xxx）
  │     │     → 进入 IN_FLOAT_DECIMAL（见下方浮点数小数部分）
  │     │
  │     ├─ 下一字符 ∈ {'8', '9'}
  │     │     → 报错 INVALID_TOKEN(102)  // 八进制中出现非法数字
  │     │
  │     ├─ 下一字符为字母
  │     │     → 报错 INVALID_TOKEN(102)  // 如 0abc
  │     │
  │     └─ 否则（单独的 '0'）
  │           → 返回 NUMBER Token (类型码 400, 值为 "0")
  │
  └─ 首字符为 '1'-'9'（十进制数）:
        while 当前字符为数字:
            追加到 lexeme, advance()
        ├─ 当前字符为字母或 '_'
        │     → 报错 INVALID_TOKEN(102)  // 如 8_it5
        │       跳过所有字母数字下划线
        │
        ├─ 当前字符为 '.'
        │     → 进入 IN_FLOAT_DECIMAL（浮点数小数部分）
        │
        └─ 否则
              → 返回 NUMBER Token (类型码 400)

  IN_FLOAT_DECIMAL（浮点数小数部分）:
        追加 '.' 到 lexeme, advance()
        ├─ 当前字符不是数字
        │     → 报错 INVALID_TOKEN(102)  // 小数点后无数字
        └─ 读取小数位:
              while 当前字符为数字:
                  追加到 lexeme, advance()
              ├─ 当前字符为 '.'
              │     → 报错 INVALID_TOKEN(102)  // 如 1.1.2
              ├─ 当前字符为字母
              │     → 报错 INVALID_TOKEN(102)  // 如 1.1a
              └─ 否则
                    → 返回 FLOAT_NUM Token (类型码 800)
```

#### 8. IN_HEX 状态（十六进制数识别）

```
IN_HEX:
  记录 "0x"/"0X" 前缀, advance()
  ├─ 当前字符不是十六进制字符 [0-9a-fA-F]
  │     → 报错 INVALID_TOKEN(102)     // 如 0x 后无有效字符
  │
  └─ while 当前字符 ∈ [0-9a-fA-F]:
        追加到 lexeme, advance()
      ├─ 当前字符为字母或数字（非十六进制有效字符）
      │     → 报错 INVALID_TOKEN(102) // 如 0x3g
      │       跳过所有字母数字
      └─ 否则
            → 返回 NUMBER Token (类型码 400)
```

#### 9. IN_ID 状态（标识符 / 关键字识别）

```
IN_ID:
  while 当前字符为字母、数字或 '_':
      追加到 lexeme, advance()
  ├─ lexeme ∈ KEYWORDS 字典
  │     → 返回对应关键字 Token（类型码 101-113）
  └─ 否则
        → 返回 IDENTIFIER Token (类型码 700)
```

支持的关键字映射：

| 关键字 | 类型码 | 关键字 | 类型码 |
|--------|--------|--------|--------|
| `char` | 101 | `void` | 107 |
| `int` | 102 | `continue` | 108 |
| `float` | 103 | `do` | 109 |
| `break` | 104 | `while` | 110 |
| `const` | 105 | `if` | 111 |
| `return` | 106 | `else` | 112 |
|  |  | `for` | 113 |

#### 10. IN_OP 状态（运算符和界符识别）

运算符分为 **双字符运算符**（需要超前查看）和 **单字符运算符**：

```
IN_OP:
  ├─ 双字符运算符（超前查看一个字符）:
  │     '=' → advance()
  │         ├─ 下一字符 '=' → advance(), 返回 '==' (EQ, 215)
  │         └─ 否则         → 返回 '='  (ASSIGN, 219)
  │
  │     '<' → advance()
  │         ├─ 下一字符 '=' → advance(), 返回 '<=' (LE, 212)
  │         └─ 否则         → 返回 '<'  (LT, 211)
  │
  │     '>' → advance()
  │         ├─ 下一字符 '=' → advance(), 返回 '>=' (GE, 214)
  │         └─ 否则         → 返回 '>'  (GT, 213)
  │
  │     '!' → advance()
  │         ├─ 下一字符 '=' → advance(), 返回 '!=' (NE, 216)
  │         └─ 否则         → 返回 '!'  (NOT, 205)
  │
  │     '&' → advance()
  │         ├─ 下一字符 '&' → advance(), 返回 '&&' (AND, 217)
  │         └─ 否则         → 报错 INVALID_TOKEN(102)  // 单独的 '&' 不合法
  │
  │     '|' → advance()
  │         ├─ 下一字符 '|' → advance(), 返回 '||' (OR, 218)
  │         └─ 否则         → 报错 INVALID_TOKEN(102)  // 单独的 '|' 不合法
  │
  └─ 单字符运算符和界符（直接匹配）:
        advance()
        '+' → PLUS(209)      '-' → MINUS(210)
        '*' → MULTIPLY(206)  '/' → DIVIDE(207)
        '%' → MOD(208)       ';' → SEMICOLON(303)
        '(' → LPAREN(201)    ')' → RPAREN(202)
        '{' → LBRACE(301)    '}' → RBRACE(302)
        '[' → LBRACKET(203)  ']' → RBRACKET(204)
        ',' → COMMA(304)     '.' → DOT(220)
        其他 → 报错 ILLEGAL_CHAR(101)
```

#### 状态转换图（简化）

```
                         ┌──────────────────────────┐
                         │                          │
                         ▼                          │
     ┌───────────── [ START ] ──────────────┐       │
     │    │    │    │    │    │    │    │    │       │
     │    │    │    │    │    │    │    │    │       │
     ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼       │
   空白  '//' '/*'  '''  '"'  数字  字母  运算符 非法字符  │
     │    │    │    │    │    │    │    │    │       │
     ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼       │
  SKIP  SKIP SKIP  IN   IN   IN   IN   IN  报错     │
  _WS  _LINE _BLK CHAR STR  NUM  _ID  _OP  跳过     │
     │  _CMT  _CMT  │    │    │    │    │    │       │
     │    │    │    ▼    ▼    ▼    ▼    ▼    │       │
     │    │    │  Token Token Token Token Token      │
     │    │    │  或报错 或报错 或报错       或报错      │
     └────┴────┴────────────────────────────────────┘
                    （回到 START）
```

#### 错误码汇总

| 错误码 | 枚举名 | 说明 | 触发场景 |
|--------|--------|------|----------|
| 101 | `ILLEGAL_CHAR` | 非法字符 | `@`, `#`, `$`, 中文字符，或无法识别的单字符 |
| 102 | `INVALID_TOKEN` | 不符合构词规则 | 空字符常量、非法转义、小数点后无数字、数字后跟字母、非法八进制/十六进制、单独的 `&` 或 `\|` |
| 103 | `UNCLOSED_COMMENT` | 注释未闭合 | `/*` 开头的注释在文件末尾未找到 `*/` |
| 104 | `UNCLOSED_CHAR` | 字符常量未闭合 | 单引号内的字符后缺少闭合的 `'` |
| 105 | `UNCLOSED_STRING` | 字符串未闭合 | 双引号字符串在行尾或文件末尾未找到闭合的 `"` |

## 项目结构

```
myCompiler/
├── scanner.py      # 词法分析器实现
├── .gitignore      # Git忽略文件配置
├── LICENSE         # MIT许可证
└── README.md       # 项目说明文档
```

## 使用方法

### 运行词法分析器

```bash
python scanner.py
```

词法分析器会读取当前目录下的 `1.txt` 文件，并输出识别到的Token序列。

### Token输出格式

```
lexeme          type_code    line
--------------------------------
int             102          1
main            700          1
(               201          1
)               202          1
{               301          1
```

## 开发计划

- [x] 词法分析器 (Lexical Analyzer)
- [ ] 语法分析器 (Parser)
- [ ] 语义分析 (Semantic Analysis)
- [ ] 中间代码生成 (Intermediate Code Generation)
- [ ] 代码优化 (Code Optimization)
- [ ] 目标代码生成 (Code Generation)

## 技术栈

- **语言**: Python 3
- **开发工具**: 任何支持Python的IDE或编辑器


## 许可证

本项目采用 [MIT License](LICENSE) 开源许可证。

## 贡献

欢迎提交Issue和Pull Request！如果你有任何建议或发现问题，请随时提出。

## 作者

- GitHub: [@axd0078](https://github.com/axd0078)

---

> 这是一个学习项目，旨在通过实践深入理解编译器的工作原理。
