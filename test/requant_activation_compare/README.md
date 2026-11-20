# 量化激活边界比较

`requant_activation_compare` 将完整 36 位有符号量化结果分别与两个 32 位有符号激活边界比较，输出严格小于最小值和严格大于最大值的条件。INT8 与 INT16 输出共用这两个条件，边界选择顺序和结果寄存周期保持一致。

低 32 位分成四个 8 位无符号比较组，最高 4 位采用有符号比较。各组独立产生相等条件和大小关系，再按高位优先合并。实现使用普通 SystemVerilog 运算，分组输出保留为组合边界。

## 形式验证

`run_formal.py` 对结果、最小边界和最大边界共 100 个不受约束的定义输入位执行 SAT 证明。FPGA 与通用配置均通过，覆盖全部有符号取值、边界相等及任意边界次序。

```sh
python3 test/requant_activation_compare/run_formal.py \
  --out build/requant_activation_compare/formal
```

Python 环境需要支持 `read_slang` 的 `pyosys`。`measurement.json` 保存对应 RTL 和工具原语库的 SHA-256，以及两项配置的形式检查结果。

完整量化通道的数值、暂停、清空与局部组合深度检查见 [量化激活比较的组合深度](../requant_activation_timing/README.md)。
