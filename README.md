# myCompiler

一个用 Python 编写的小型 C++ 子集编译器。当前实现面向教学和本地算法题程序，输入源码，完成词法分析、语法分析、语义检查，最终输出 Windows x86-64 汇编。

当前版本的目标不是覆盖完整 C++，而是稳定支持这一类程序：

- 单文件
- 无头文件或只写 `using namespace std;`
- `main()` / `int main()`
- 整数和字符运算
- `cin` / `cout`
- 或内建 `read()` / `write()`

## 当前能力

当前已经支持的核心语法和功能：

- `main()` 和 `int main()`
- `int` / `char` / `void`
- 局部变量和全局变量
- `const` 常量
- 函数声明和函数定义
- 函数声明允许省略参数名，例如 `int sum(int, int);`
- 函数定义要求参数有名字
- 普通函数调用、嵌套调用、递归
- `if` / `else`
- `while`
- `for`
- `do while`
- `break` / `continue`
- `return`
- 一元运算：`+`、`-`、`!`
- 二元运算：`+`、`-`、`*`、`/`、`%`
- 比较运算：`<`、`<=`、`>`、`>=`、`==`、`!=`
- 逻辑运算：`&&`、`||`
- `cin >> a >> b`
- `cout << expr << expr2`
- 内建 `read()`
- 内建 `write(expr)`

## 输入输出模型

当前版本支持两套输入输出接口。

### 1. C++ 风格 `cin` / `cout`

```cpp
using namespace std;

main() {
    int a, b;
    cin >> a >> b;
    cout << a + b;
    return 0;
}
```

约束：

- 只支持 `using namespace std;`
- 不支持 `std::cin` / `std::cout`
- `cin` 目前只支持把值读入变量
- `cout` 目前只支持输出 `int` / `char` 表达式

### 2. 内建 `read()` / `write()`

```cpp
main() {
    int a;
    a = read();
    write(a + 100);
    return 0;
}
```

语义规则：

- `read()` 不接收参数，返回 `int`
- `write(expr)` 只接收一个 `int`
- `write` 不自动输出空格或换行
- `read` 和 `write` 是内建函数，用户代码不能重新声明或定义

后端实现上，`cin` / `cout` 和 `read` / `write` 最终都会映射到 `scanf` / `printf` 调用。

## 不支持的内容

当前仍然不支持：

- `#include` 和预处理器展开
- 头文件依赖解析
- `std::` 前缀调用
- 类、模板、异常、`new` / `delete`
- 指针
- 数组代码生成
- 结构体
- `float` / `double` 后端代码生成
- 字符串表达式代码生成
- 多参数 `write`
- 完整 C / C++ 标准库

## 项目结构

```text
myCompiler/
├── mycompiler.py      # 命令行入口，串联前端、语义分析和汇编生成
├── intermediate.py    # 词法分析、递归下降语法分析、AST 和四元式生成
├── semantic.py        # 语义分析、作用域和符号表
├── codegen.py         # Windows x86-64 汇编生成
├── scanner.py         # 早期词法分析实验文件
├── parser.py          # 早期语法分析实验文件
├── .gitignore
└── README.md
```

当前完整编译流程以 `mycompiler.py` 为入口。`scanner.py` 和 `parser.py` 仍保留为早期实验代码，不参与主流程。

## 编译流程

主流程在 `mycompiler.py` 中：

1. `Lexer` 把源码切成 token
2. `Parser` 把 token 解析成 AST
3. `SemanticAnalyzer` 做语义检查
4. `generate_assembly()` 把 AST 转成 Windows x86-64 汇编

如果任一阶段报错，编译会直接失败，并把错误打印到标准错误输出。

## 词法与语法实现

`intermediate.py` 同时包含前端核心逻辑：

- `Lexer`：手写扫描器，支持关键字、标识符、整数字面量、字符/字符串字面量、注释和双字符运算符
- `Parser`：手写递归下降分析器
- `ASTNode`：统一语法树节点结构
- `IntermediateCodeGenerator`：把 AST 转成四元式

语法分析里的几个关键设计：

- 顶层 `type identifier` 前缀通过向后看 `(` / `{` / 其他符号区分“函数”和“变量声明”
- 表达式按优先级拆成多层递归函数：赋值、逻辑或、逻辑与、相等、关系、加减、乘除模、一元、后缀
- `cin` / `cout` 被单独解析为 `InputStmt` / `OutputStmt`
- `using namespace std;` 被显式识别，其余 `std::` 形式直接拒绝

`intermediate.py` 也保留了四元式生成能力，但主编译入口当前直接走 AST 到汇编的路径。

## 语义分析实现

`semantic.py` 以 AST 为输入，做三类核心工作：

### 1. 作用域和符号表

- 全局作用域
- 函数作用域
- 复合语句块作用域
- 普通变量、常量、函数分别建表

### 2. 语义检查

当前实现会检查：

- 标识符重定义
- 标识符未声明
- 函数重定义
- 函数未声明
- 函数参数个数不匹配
- 函数参数类型不匹配
- 返回值类型不匹配
- `break` 是否在循环中
- 常量赋值
- 算术操作数类型不匹配
- `cin` 输入目标是否合法
- `cout` 输出类型是否合法

### 3. 内建函数规则

`read` / `write` 在语义阶段按内建函数处理：

- `read()` 必须零参数，返回 `int`
- `write(expr)` 必须单参数，参数类型必须为 `int`

## 汇编后端实现

`codegen.py` 负责把 AST 生成为 Windows x86-64 汇编。当前后端特点：

- 输出 Intel 语法汇编
- 调用约定按 Windows x64 寄存器传参规则处理
- 支持全局变量和局部变量
- 支持 `char` / `int`
- 支持条件分支和循环标签生成
- 支持函数调用、参数传递、返回值处理
- `cin` / `cout` 和 `read` / `write` 最终映射到 `scanf` / `printf`

后端限制也比较明确：

- 数组语法可以被前端识别，但后端不生成数组访问代码
- `float` / `double` 不生成代码
- 字符串表达式不生成代码

## 使用方法

### 1. 生成汇编

```powershell
python mycompiler.py -S input.cpp -o build\program.s
```

如果不传 `-o`，默认输出到同名 `.s` 文件。

### 2. 链接为可执行文件

```powershell
gcc build\program.s -o build\program.exe
```

### 3. 运行

```powershell
@('3','5') | .\build\program.exe
```

源码读取编码策略：

- 优先按 `utf-8-sig` 读取
- 失败后回退到 `gbk`

## 示例

### 1. `cin` / `cout`

```cpp
using namespace std;

int sum(int a, int b) {
    return a + b;
}

main() {
    int x, y;
    cin >> x >> y;
    cout << sum(x, y);
    return 0;
}
```

### 2. `read` / `write`

```cpp
int sum(int, int);

main() {
    int a = read();
    int b = read();
    write(sum(a, b));
    return 0;
}

int sum(int x, int y) {
    return x + y;
}
```

## 当前限制

- 三地址码生成存在，但主流程没有把四元式作为后端输入
- `test/` 目录当前按本地文件处理，不随仓库提交
- 前端能识别的部分语法，后端不一定都能生成代码，尤其是数组和更复杂的类型
- 目前只面向 Windows x86-64 汇编输出
- 没有做优化阶段

## 后续方向

- 收紧“前端可接受但后端不支持”的语法范围，减少阶段间能力不一致
- 把四元式真正接入后端，而不是只作为独立实验能力保留
- 增加更稳定的本地测试入口
- 继续扩展类型系统和代码生成能力

## 许可证

本项目使用 [MIT License](LICENSE)。
