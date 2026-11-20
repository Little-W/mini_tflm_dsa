# 向量串行归约算术

`vector_reduce_alu` 在当前周期完成 INT32 求和、最大值或最小值选择。FPGA 实现使用一个 `DSP48E1`，输入及输出寄存器均旁路。通用实现使用对应的有符号加法与比较表达式。现有 8 个并行 PE、输入容量、状态机和归约结果写入边沿保持。

## 算术

两个 INT32 操作数分别扩展为 48 位有符号数。求和返回 DSP 结果的低 32 位；极值比较使用完整 `lhs-rhs` 的符号位，差值范围在 48 位内。`SUM`、`MAX`、`MIN` 共用同一算术单元，外部 `reduce_acc` 仍每个归约周期更新一次。

`run_formal.py` 直接提取当前及参考 `vector_engine.sv` 中的归约代码，比较全部 64 位操作数组合和全部 16 种操作码。FPGA 检查使用官方 DSP48E1 功能模型，通用实现单独检查。脚本同时检查归约范围外的引擎内容以及原有 PE 实现保持相同，因此组合结果相同对应原有寄存器更新周期相同。

## 已完成测量

参考提交为 `90ac3639`。完整向量参数为 `TILE=16`、`PE_COUNT=8`、`BUS_WIDTH=64`。

| 测量对象 | 参考实现 | DSP 归约 |
|---|---:|---:|
| 归约单元逻辑 LUT | 137 | 34 |
| 归约单元 CARRY4 | 21 | 0 |
| 归约单元 DSP | 0 | 1 |
| 完整向量逻辑 LUT | 11331 | 11399 |
| 完整向量 RAM LUT | 248 | 248 |
| 完整向量触发器 | 5994 | 5994 |
| 完整向量 DSP | 15 | 16 |
| 完整向量最长寄存器组合路径 | 15 | 15 |
| `state` 至 `reduce_acc` | 15 | 10 |

完整映射增加 68 个逻辑 LUT，归约路径减少 5 级。该实现作为时序优化候选保存，采用时需结合完整 SoC 的路径与物理 LUT 数量评估。上述级数统计包含 DSP 内部组合算术，实际 150 MHz 结果由目标器件布局布线确定。

BUS64 的实际 FPGA 原语完整向量测试通过 592 项、168601 个输出、2979488 个周期，包含卷积、池化、INT8/INT16 向量运算、Add 和 Softmax。测试中的数据与 AXI 随机等待共用随机数生成器，工作量汇总对应本次固定的完整 DMA 和引擎源码。归约前后同一输入序列的公开周期由实际代码形式等价证明检查。

`test/vector_pe_dsp/measure_paths.py` 按 `AREG=1`、`BREG=1` 识别原有 8 个寄存 PE，归约 DSP 独立统计。`measurement.json` 保存源码和映射哈希、完整路径、形式证明和数值结果。

## 重复执行

```bash
python3 test/vector_reduce_dsp/run_formal.py --out build/vector_reduce_dsp/formal
python3 test/vector_reduce_dsp/prepare_measurement.py --out build/vector_reduce_dsp/sources
python3 scripts/fpga/open_fpga_synth.py --out build/vector_reduce_dsp/synthesis --case-config build/vector_reduce_dsp/sources/cases.json --cases reduce_reference reduce_current vector_reference vector_current
python3 test/vector_reduce_dsp/measure_paths.py --reference build/vector_reduce_dsp/synthesis/vector_reference --current build/vector_reduce_dsp/synthesis/vector_current --out build/vector_reduce_dsp/paths.json
python3 test/vector_engine/run.py --out build/vector_reduce_dsp/numerical --bus-width 64 --pes 8 --xilinx --jobs 1 --verilator verilator
```
