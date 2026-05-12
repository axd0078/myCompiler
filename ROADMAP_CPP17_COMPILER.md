# 自研 C++17 编译器长期路线

## 当前定位
- [ ] 最终目标：完全自研 C++17 编译器，输入 `.cpp`，输出 Windows x86-64 GNU assembly `.s`。
- [ ] 不调用 g++/clang 解析或编译用户源码。
- [ ] 允许使用 MinGW 的 assembler/linker 验证生成的 `.s`。
- [ ] 当前近期目标：让 CSP corpus 全部 62 个 `.cpp` 生成 `.s`。

## Phase 1：CSP 62/62 生成汇编
- [ ] 重构 `mycompiler.py`，让 CSP 编译走新的 C++ pipeline。
- [ ] 完成 C++17 子集 parser：函数、struct、引用、指针、成员访问、下标、range-for、lambda、初始化列表。
- [ ] 完成类型系统：`int/long long/unsigned long long/bool/char/float/double/string`。
- [ ] 完成 CSP 所需 STL 子集：`vector/string/pair/map/set/unordered_map/unordered_set/queue`。
- [ ] 完成内建函数：`sort/reverse/prev/lower_bound/min/max/abs/llabs/sin/cos/pow`。
- [ ] 完成 I/O：`cin/cout/endl/fixed/setprecision/scanf/printf`。
- [ ] `--compile-dir` 对 CSP corpus 返回 `OK 62/62`。

## Phase 2：标准 C++ 前端基础
- [ ] 实现真实预处理器：宏、条件编译、include 搜索、诊断位置映射。
- [ ] 建立完整 AST、符号表、作用域和 name lookup。
- [ ] 支持函数重载、构造/析构、成员函数、访问控制基础。
- [ ] 支持模板声明、实例化记录和基础函数模板/类模板。
- [ ] 建立标准错误诊断格式。

## Phase 3：IR 与代码生成扩展
- [ ] 设计类型保留 IR，覆盖值、地址、字段偏移、数组、调用、控制流。
- [ ] 完成 Win64 ABI：参数传递、返回值、栈对齐、结构体传参。
- [ ] 支持整数、浮点、指针、数组、struct/class 对象布局。
- [ ] 支持运行时符号管理和按需附加 runtime assembly。
- [ ] 建立 `.s` 输出稳定性测试。

## Phase 4：C++ 运行时与标准库子集
- [ ] 自研 string/vector/map/set/unordered_map/unordered_set/queue 运行时。
- [ ] 支持迭代器、range-for、容器成员函数和常用算法。
- [ ] 支持 new/delete 基础内存管理。
- [ ] 支持异常/RTTI 前先明确不支持并给清晰诊断。
- [ ] 逐步扩展到更多 STL 容器和算法。

## Phase 5：通用 C++17 兼容推进
- [ ] 引入公开 C++ 测试集作为长期回归。
- [ ] 分阶段覆盖 constexpr、namespace、ADL、模板偏特化、operator overload。
- [ ] 支持多文件编译和链接单元模型。
- [ ] 建立与 MinGW g++ 的行为对照测试。
- [ ] 定期记录不支持特性清单和兼容进度。

## 验收命令
- [ ] `python -m unittest discover -s test -p "test_*.py"`
- [ ] `python mycompiler.py --compile-dir D:\study\code\data_structure-study\programming\test\csp --out-dir build\csp-asm -S`
- [ ] 抽样：`gcc build\csp-asm\<case>.s -o build\csp-asm\<case>.exe`
