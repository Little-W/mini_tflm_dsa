# 量化激活边界比较

`requant_activation_compare` 将完整三十六位有符号量化结果分别与两个三十二位有符号激活边界比较，输出严格小于最小值和严格大于最大值的条件。INT8 与 INT16 输出共用这两个条件，边界选择顺序和结果寄存周期保持一致。

FPGA 实现按每两个数据位划分比较组。一个 `LUT6_2` 同时产生该组的相等条件与大小结果，最高一组按有符号数解释。`CARRY4` 在相等的高位组上传递低位结果，遇到不相等的高位组后采用该组的大小关系。通用实现直接使用相同位宽的有符号比较。

## 完整模块综合

生产参数为 `BUS_WIDTH=64`、`VLEN=16`、`MAX_IA_REUSE=32`、`ENABLE_S16=1`，全部公开输出参与综合。参考版本为 `b58ac8bf`。使用 Yosys 0.71、ABC9 和 Xilinx 7 系列原语模型。

| 指标 | 参考实现 | 分组比较实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 7,596 | 7,400 |
| 分布式 RAM LUT | 800 | 800 |
| SRL LUT | 160 | 160 |
| 触发器 | 7,501 | 7,501 |
| DSP48E1 | 80 | 80 |
| RAMB18E1 | 2 | 2 |
| 最长寄存器间组合单元数 | 15 | 15 |

完整量化减少 196 个逻辑 LUT。结果的有效位、十二个寄存阶段、参数容量和每周期接收一组完整向量的能力保持一致。完整 SoC 的物理 LUT 位置与目标器件时序由整机实现统计。

## 功能验证

`run_formal.py` 对 36 位结果、32 位最小边界及 32 位最大边界共 100 个不受约束的输入位执行 SAT 证明，FPGA 原语与通用实现均通过。比较覆盖全部有符号取值、边界相等以及任意边界次序。

实际 FPGA 分支的完整量化接口比较覆盖 256 个场景和 528,662 个周期。18 个公开输出逐周期一致，共检查 209,001 个输出向量、958 个 DMA 命令和 6,496 个 DMA 返回拍。官方 `LUT6_2`、`CARRY4`、`DSP48E1` 和 `FDRE` 模型参与仿真。

`measurement.json` 保存正式源码、原语库、形式检查、接口比较及实际综合网表的 SHA-256，并记录完整寄存器路径。

## 复现命令

```sh
python3 test/requant_activation_compare/run_formal.py \
  --out build/requant_activation_compare/formal

python3 test/requant_pipeline/run_interface.py \
  --reference-rev b58ac8bf --xilinx --bus-width 64 \
  --verilator "$VERILATOR_BIN" --jobs 2 \
  --out build/requant_activation_compare/interface

python3 test/requant_sync_parameters/prepare_measurement.py \
  --reference-rev b58ac8bf --out build/requant_activation_compare/inputs

python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/requant_activation_compare/inputs/cases.json \
  --cases reference candidate --out build/requant_activation_compare/synthesis \
  --lock-file "$SYNTHESIS_LOCK"
```
