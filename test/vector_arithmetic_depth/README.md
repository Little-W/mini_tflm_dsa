# 向量算术寄存器路径检查

本目录验证 `vector_reduce_alu`、`vector_round_shift` 和 `registered_multiplier_s32` 的完整公开接口，并测量独立模块的寄存器间组合路径。参考提交为 `dde5e7c9836a71f0292d7c69040f8635840e6bad`，结果和源码 SHA-256 保存在 [measurement.json](measurement.json)。

## 当前设计

`vector_reduce_alu` 使用四位分组的 `parallel_prefix_add` 完成 INT32 求和。大小比较按八位字节并行计算，各字节的结果由更高字节是否全部相等来选择，符号位决定异号操作数的顺序。当 `i_max` 和 `i_min` 同时有效时，极小值操作优先。

`vector_round_shift` 将保护位和低字节的全一条件通过平衡前缀树组合，保留各层节点和字节进位边界。最低字节并行准备不递增与递增两个结果，由舍入条件选择；其他字节根据各自进位独立递增。中间移位寄存器、保护位、舍弃位和最近偶数舍入规则保持不变，原生定宽运算保留输入含 X、Z 时的四态行为。

`registered_multiplier_s32` 的四个部分积仍在原来的使能边沿写入寄存器。部分积经过压缩后，最后的 48 位求和使用八位分组的 `parallel_prefix_add`，并启用 `p_preserve_groups` 使用保存节点的平衡前缀树。输入寄存选项、使能暂停和完整 64 位结果的输出周期均保持不变。

## 验证结果

- 14 个完整模块形式等价配置全部通过。FPGA 与 ASIC 两种条件分别覆盖归约运算、舍入中间寄存器的启用和关闭，以及乘法器的四种输入寄存组合。检查全部公开输出，不限制操作数、使能或操作控制输入。
- 舍入模块完成 52,352 组严格四态刺激，分别比较中间寄存器启用和关闭时的 `result`、`floor_value`，覆盖全部 64 种移位量及 X、Z 数据。
- 标量乘法器完成 1,396,934 次数据比较，覆盖四种输入寄存组合、输入边界、连续输入和使能暂停。
- 实际量化通道在通用与 FPGA 两种条件下分别完成 1,057,997 个周期和 838,131 个输出检查，覆盖暂停、清空、复位、尾列屏蔽及保持期间清空。使能边沿延迟保持 12 拍。

## 局部映射结果

使用默认 `synth_xilinx -family xc7 -noiopad -noclkbuf -flatten`。归约模块在输入和输出两端加入测试寄存器；舍入模块使用生产配置的中间寄存器，并在公开输入、输出两端加入测试寄存器。标量乘法器保留实际寄存器结构。两份实现使用相同测试结构。

| 模块 | 逻辑 LUT：参考→当前 | 触发器：参考→当前 | CARRY4：参考→当前 | DSP：参考→当前 | 最长寄存器间组合路径：参考→当前 |
|---|---:|---:|---:|---:|---:|
| `vector_reduce_alu` | 122→187 | 98→98 | 14→15 | 0→0 | 10→7 |
| `vector_round_shift` | 342→368 | 267→267 | 16→16 | 0→0 | 9→8 |
| `registered_multiplier_s32` | 95→209 | 64→64 | 12→12 | 4→4 | 14→9 |

所有映射结果的组合图均完整。完整 SoC 的跨模块路径需要由整机映射重新检查；150 MHz 需要布局布线后的器件时序报告确认。

## 复现命令

从仓库根目录执行，需要 `pyosys`、Icarus Verilog 和 Verilator。

```bash
python3 test/vector_arithmetic_depth/run.py \
  --baseline-ref dde5e7c9 --synthesis \
  --out /tmp/npu_vector_arithmetic
python3 test/vector_arithmetic_depth/check_four_state.py \
  --reference-ref aa0a169c --out /tmp/npu_vector_arithmetic/four_state
python3 test/requant_four_dsp/run.py \
  --reference-rev dde5e7c9 --verilator verilator --jobs 1 \
  --out /tmp/npu_vector_arithmetic/scalar_function
python3 test/requant_compute_lane/run.py \
  --verilator verilator --jobs 1 --variants generic fpga \
  --out /tmp/npu_vector_arithmetic/requant_lane
python3 test/vector_arithmetic_depth/collect_report.py \
  --validation /tmp/npu_vector_arithmetic \
  --scalar /tmp/npu_vector_arithmetic/scalar_function \
  --requant /tmp/npu_vector_arithmetic/requant_lane \
  --four-state /tmp/npu_vector_arithmetic/four_state \
  --out /tmp/npu_vector_arithmetic/measurement.json
```

入口先保存实际 RTL 和公共加法器，再运行形式比较和综合。结果同时记录参考源码、当前源码、测试入口和映射文件的 SHA-256。
