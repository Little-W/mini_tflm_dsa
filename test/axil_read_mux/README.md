# AXI-Lite 配置读回与银行数量验证

`npu_axil_reg_if` 使用组合字表保存各地址对应的读回表达式，再由二进制地址选择读回数据。128 个表项覆盖现有 75 个寄存器地址，未分配表项为零；完整地址检查使范围外地址以及含未知值的地址保持原有零值行为。读响应仍由原有 `ar_accept` 条件写入 `rdata_q`，握手、响应保持、复位和写寄存器周期均保持不变。

共享银行数量的保存位宽由 `SHARED_IA_BANK_MASK` 能力位图确定。允许写入的值保留全部有效位，并在原有 32 位公开输出中补零。生产配置允许值为 1 和 2，因此高 30 位为常量零。能力位图允许更大的数值时，保存位宽可扩展到 5 位；原有字节写使能、非法配置响应及复位值继续有效。

## 已执行检查

[measurement.json](measurement.json) 保存源码摘要、完整参数、结果及日志摘要。固定参考提交为 `c70888842048247451c17bd8241d47f43c06d070`。

| 检查 | 范围 | 结果 |
| --- | --- | --- |
| 完整模块状态等价 | 8 组参数；全部公开输出和共有内部状态、信号；输入不作约束 | 全部通过 |
| 银行数量位宽证明 | 任意 32 位能力位图和任意 32 位待写值；验证所有允许值的完整保存 | 通过 |
| 逐周期数值比较 | AXI-Lite 数据宽度 32 和 64；每组 101,683 周期；全部 55 个公开输出，包含无效周期 | 全部通过 |
| 读回四态比较 | 两种数据宽度分别执行 11,264 组地址与数据检查；覆盖全部 4,096 个地址和 X、Z 输入 | 全部通过 |
| 银行数量四态比较 | 7 组能力位图，覆盖保存位宽 1 至 5；每组 100,004 次输入 | 全部通过 |
| LUT 重新映射验证 | 两份 `physical-cost` 网表分别执行 ABC9 `&verify` | 全部通过 |

完整状态等价使用 Yosys、Slang、`equiv_simple` 和 `equiv_induct`。数值比较使用 Verilator，四态比较使用 Icarus Verilog。四态脚本同时检查原有 77 条读回赋值表达式及其 75 个地址与当前字表一致。数值测试覆盖地址与数据分开到达、字节写使能、读响应暂停、非法银行分配、复位、完成通知和未分配地址。

## 局部综合结果

以下结果来自生产 AXI-Lite 配置参数，资源统计发生在布局之前。

| 映射方式 | 版本 | 逻辑 LUT | 触发器 | CARRY4 | 寄存器间最大组合级数 |
| --- | --- | ---: | ---: | ---: | ---: |
| 原生 Xilinx 映射 | 参考 | 985 | 1,387 | 6 | 8 |
| 原生 Xilinx 映射 | 当前 | 895 | 1,357 | 2 | 5 |
| `physical-cost`，`small-lut-area-cost=1` | 参考 | 905 | 1,387 | 6 | 8 |
| `physical-cost`，`small-lut-area-cost=1` | 当前 | 820 | 1,357 | 2 | 7 |

这四份网表均未使用 DSP、BRAM、分布式 RAM 或 SRL。单项综合的进程树峰值内存约 200 MiB。SoC 的物理 LUT 数量需要由完整设计布局测量；150 MHz 需要布线后的器件时序分析。

## 复现命令

在仓库根目录使用已配置的 Yosys Python 环境、Slang、Verilator 和 Icarus Verilog：

```bash
python3 test/axil_read_mux/run_formal.py \
  --out /tmp/npu_axil_read_mux/formal
python3 test/axil_read_mux/prove_bank_width.py \
  --out /tmp/npu_axil_read_mux/bank_width
python3 test/axil_read_mux/run.py \
  --out /tmp/npu_axil_read_mux/numeric
python3 test/axil_read_mux/run_four_state.py \
  --out /tmp/npu_axil_read_mux/four_state
python3 test/axil_read_mux/prepare_measurement.py \
  --out /tmp/npu_axil_read_mux/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config /tmp/npu_axil_read_mux/inputs/cases.json \
  --cases reference current --out /tmp/npu_axil_read_mux/native
python3 scripts/fpga/remap_fpga_luts.py \
  --source /tmp/npu_axil_read_mux/native/reference \
  --out /tmp/npu_axil_read_mux/cost1/reference \
  --mode physical-cost --small-lut-area-cost 1 --max-lut-inputs 6 \
  --wire-delay-ps 500 --delay-target-ps 6667
python3 scripts/fpga/remap_fpga_luts.py \
  --source /tmp/npu_axil_read_mux/native/current \
  --out /tmp/npu_axil_read_mux/cost1/current \
  --mode physical-cost --small-lut-area-cost 1 --max-lut-inputs 6 \
  --wire-delay-ps 500 --delay-target-ps 6667
```

`run.py` 默认调用 `verilator-modern`，可通过 `--verilator` 指定安装路径。测试输出目录保存当次源码、生成的测试代码、日志及结果，报告中的摘要可用于核对对应内容。
