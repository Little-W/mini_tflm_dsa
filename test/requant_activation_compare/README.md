# 量化激活边界比较

`requant_activation_compare` 将完整 36 位有符号量化结果分别与两个 32 位有符号激活边界比较，输出严格小于最小值和严格大于最大值的条件。INT8 与 INT16 输出共用这两个条件，边界选择顺序和结果寄存周期保持一致。

FPGA 综合将两侧操作数符号扩展到 37 位，使用完整差值的符号位确定严格大小关系。普通减法表达式配合 `use_dsp` 属性推断算术资源。通用配置与事件仿真将低 32 位分成四个 8 位无符号比较组，最高 4 位采用有符号比较，各组关系按高位优先合并。

## 功能与资源检查

`run_formal.py` 对结果、最小边界和最大边界共 100 个不受约束的定义输入位执行 SAT 证明。FPGA 与通用配置均通过，覆盖全部有符号取值、边界相等及任意边界次序。

三种事件仿真配置共 196,608 组含未知值输入通过两个标志位的严格四态比较。完整量化通道在通用和 FPGA 配置下分别运行 1,057,997 个周期、检查 838,131 个有效输出，包括暂停、清空、复位、尾列屏蔽和全部移位编码；十二个使能边沿的延迟保持。

从实际 RTL 提取比较和 INT8／INT16 裁剪选择，在相同输入及输出寄存边界下测得：

| 指标 | 参考提交 | 当前 FPGA 表达式 |
| --- | ---: | ---: |
| LUT | 143 | 74 |
| 触发器 | 125 | 125 |
| DSP | 0 | 2 |
| 最长寄存器路径 | 6 | 5 |

此处为单个通道输出部分的独立映射。完整 SoC 的资源、跨模块路径和器件时序另行测量。

```sh
python3 test/requant_activation_compare/run_formal.py \
  --out build/requant_activation_compare/formal
python3 test/requant_activation_compare/check_four_state.py \
  --out build/requant_activation_compare/four_state
python3 test/requant_compute_lane/run.py --verilator verilator --jobs 1 \
  --out build/requant_activation_compare/numeric
python3 test/requant_activation_compare/prepare_measurement.py \
  --out build/requant_activation_compare/sources
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/requant_activation_compare/sources/cases.json --cases reference current \
  --rtl-dsp-attributes --wide-alu-dsp-budget 740 \
  --out build/requant_activation_compare/measure
```

Python 环境需要支持 `read_slang` 的 `pyosys`。[measurement.json](measurement.json) 保存对应源码及工具库的 SHA-256、形式检查、四态比较、数值回归和映射结果。

通用比较表达式的测量入口见 [量化激活比较的通用表达式](../requant_activation_timing/README.md)。
