# myCompiler

一个用 Python 编写的最小 C 子集编译器。当前实现面向教学和算法题式的小程序，输入类 C 源码，输出 Windows x86-64 汇编。

当前目标不是覆盖完整 C 语言，而是把一条清晰、可读、可验证的编译链路跑通：

```text
source text -> token stream -> AST -> semantic checks -> x86-64 assembly
```

如果你想看更细的实现拆解，可以继续读 [docs/compile-to-assembly.md](docs/compile-to-assembly.md)。README 先给出项目能力和核心算法。

## 当前能力

当前已经支持的核心语法和功能：

- `main()` 和 `int main()`
- `int` / `char` / `void`
- 全局变量、局部变量、`const`
- 函数声明、函数定义、递归调用
- `if` / `else`
- `while` / `for` / `do while`
- `break` / `continue` / `return`
- 整数与字符常量
- 表达式：`+`、`-`、`*`、`/`、`%`
- 比较与逻辑：`<`、`<=`、`>`、`>=`、`==`、`!=`、`&&`、`||`、`!`
- 内建输入 `read()`
- 内建输出 `write(expr)`

当前不支持：

- `#include`、宏展开、预处理器
- 指针、结构体、数组代码生成
- `float` / `double` 代码生成
- 源码级 `scanf` / `printf`
- `cin` / `cout`
- 完整标准库

## 算法实现

编译入口在 `mycompiler.py`。主流程是：

1. `Lexer.tokenize()` 把源码字符流切成 token。
2. `Parser.parse()` 用递归下降把 token 流整理成 AST。
3. `SemanticAnalyzer.analyze()` 做作用域、符号表和语义约束检查。
4. `generate_assembly()` 直接基于 AST 生成 Windows x86-64 汇编。

### 1. 词法分析

词法分析器在 `intermediate.py` 的 `Lexer` 中，采用单指针线性扫描：

- 从左到右读取源码字符。
- 跳过空白符、单行注释、多行注释，以及 `#` 开头的整行。
- 遇到字母或下划线时读取标识符，再查关键字表决定是关键字还是普通名字。
- 遇到数字时读取整数字面量。
- 遇到 `'` 或 `"` 时分别读取字符常量和字符串常量。
- 遇到运算符时优先匹配双字符运算符，再回退到单字符运算符。

这个阶段的关键点不是“把字符拆开”，而是尽早完成最便宜的分类工作。后续语法分析不再关心原始字符，只处理已经分类好的 token。

### 2. 语法分析

语法分析器也在 `intermediate.py`，核心方法是手写递归下降。

主要策略：

- 顶层先区分“声明”和“定义”。
- 表达式按优先级分层解析：赋值、逻辑或、逻辑与、相等、关系、加减、乘除模、一元、后缀。
- 每个语法结构都直接生成 AST 节点，而不是先构造临时文本表示。

这种写法的优点是可控。我们可以明确决定每一层优先级如何结合，也能在出错时把报错位置压到当前 token 附近。

### 3. 语义分析

语义分析在 `semantic.py`，输入是 AST，输出是错误列表和几张符号表文本。

核心算法是“作用域栈 + 符号登记 + AST 递归检查”：

- 进入函数或复合语句块时创建新作用域。
- 声明变量、常量、参数时登记到当前作用域。
- 查找名字时从当前作用域逐层向父作用域回溯。
- 分析表达式时同步推导类型，检查赋值、运算、函数调用是否合法。

当前重点检查：

- 名字重定义
- 标识符未声明
- 函数声明/定义不一致
- 函数参数个数或类型不匹配
- `const` 被赋值
- `break` / `continue` 是否出现在循环中
- `return` 是否匹配函数返回类型
- `read()` / `write(expr)` 是否满足内建函数约束

### 4. 代码生成

汇编生成在 `codegen.py`，当前后端不经过独立 IR，而是直接遍历 AST 输出汇编。

主要做法：

- 预扫描顶层 AST，收集函数签名和全局变量。
- 为每个函数建立栈帧，给参数、局部变量、临时槽分配偏移。
- 表达式求值统一把结果放进寄存器，再按节点类型继续组合。
- 控制流通过自动生成标签实现，例如 `if`、循环、`break`、`continue`。
- 函数调用遵循 Windows x64 调用约定。
- `read()` / `write()` 最终映射到 `scanf("%d", ...)` 和 `printf("%d", ...)`。

这个后端的核心取舍是“先保证结构正确，再考虑优化”。所以当前更强调可读性和可验证性，而不是指令级优化。

## 项目结构

```text
myCompiler/
├── mycompiler.py                 # 命令行入口，串联完整编译流程
├── intermediate.py               # 词法分析、递归下降语法分析、AST、辅助 IR
├── semantic.py                   # 语义分析与符号表检查
├── codegen.py                    # Windows x86-64 汇编生成
├── visualizer_tk.py              # Tkinter 可视化界面
├── docs/
│   └── compile-to-assembly.md    # 更详细的算法实现说明
├── .gitignore
└── README.md
```

说明：

- `visualizer_tk.py` 是辅助学习工具，可以查看 token、AST、语义结果、四元式和最终汇编。
- 本地 `test/` 目录不再作为仓库内容同步；可视化工具在没有 `test/` 时会回退到内置示例源码。

## 使用方法

生成汇编：

```powershell
python mycompiler.py -S example.c -o build\example.s
```

链接为可执行文件：

```powershell
gcc build\example.s -o build\example.exe
```

示例源码：

```c
int sum(int x, int y) {
    return x + y;
}

int main() {
    int a = read();
    int b = read();
    write(sum(a, b));
}
```

如果源码包含中文注释，编译器会优先按 `utf-8-sig` 读取，失败后回退到 `gbk`。

## 可视化工具

运行：

```powershell
python visualizer_tk.py
```

它会把源码分阶段展示为：

- token 列表
- AST
- 语义分析结果
- 辅助四元式
- 最终 `.s` 汇编

这个界面不参与正式编译，只用于观察每个阶段的中间结果。

## 许可证

本项目使用 [MIT License](LICENSE)。
