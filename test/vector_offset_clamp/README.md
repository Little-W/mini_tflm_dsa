# 向量输出偏移的并行前缀加法

`vector_engine.sv` 将有符号舍入结果的低 32 位与输出偏移相加，再根据高 32 位的符号和范围执行限幅。低位加法采用 16 个二位分段，每个分段同时产生进位生成条件和进位传播条件。四层并行前缀计算各分段的输入进位，随后各分段并行形成两个结果位。

FPGA 实现使用 `LUT6_2` 的两个输出共享生成条件与传播条件，或共享相邻的两个和位。通用实现使用同一前缀关系。高位范围判断、上下限比较、限幅优先顺序和所有寄存更新周期保持一致。

## 固定源码与功能检查

参考提交为 `414099fad66a28e053ef85f51e41d38b3d883550`。测量所用 `vector_engine.sv` 的 SHA-256 为 `7f407f1b36a5d4570d69b1565c51090cc4b3a4013d4fd7a6fb2b69ba690dca0e`。完整摘要保存在 `measurement.json`。

`run.py` 从生产文件直接提取实际表达式，并检查表达式之外的源码与参考提交相同。两种实现均完成以下全输入证明：

- 任意 64 位舍入值和三项 32 位配置，共 160 位相关输入。
- 两个限幅条件及完整 32 位结果，共 34 位输出，与参考提交一致。
- 完整 32 位结果与提交 `1c081bca06076727fab1ed2e194195f4563bd5ee` 中的实际有符号 64 位加法和限幅表达式一致。
- FPGA 分支使用工具附带的官方 `LUT6_2` 功能模型。

既有 `test/vector_round_carry/run_offset_formal.py` 的 64 位算术检查同时通过。该脚本显式选择通用组合实现，FPGA 原语实现由本目录的两种实现比较覆盖。

实际生产向量测试使用 `TILE=16`、`PE_COUNT=8`、128 个缓存集合、缓存策略 3、真实 DMA 和官方 FPGA 原语模型。独立整数模型检查全部输出。

| 总线宽度 | 任务数 | 检查输出数 | 任务总周期 |
|---|---:|---:|---:|
| 32 位 | 592 | 169,487 | 3,017,541 |
| 64 位 | 592 | 168,601 | 2,979,488 |

## 综合测量

完整向量模块采用 `TILE=16`、`BUS_WIDTH=64`、`DMA_SIZE=64`、`PE_COUNT=8`，通过相同的原生 Xilinx 映射流程比较。除 `vector_engine.sv` 中的组合替换外，综合输入文件内容相同。路径分析保留完整逐位连接和 DSP 内部组合运算计数。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT 单元 | 11,040 | 10,921 |
| 分布式存储 LUT | 248 | 248 |
| 触发器 | 6,029 | 6,029 |
| DSP48E1 | 17 | 17 |
| CARRY4 | 693 | 675 |
| 完整模块最长寄存路径 | 15 | 15 |
| 全部输出偏移位到 `result_buf` 的最大路径 | 15 | 14 |
| 输出偏移第 10 位到 `result_buf` 的最大路径 | 14 | 14 |
| `q_rounded` 到 `result_buf` 的最大路径 | 14 | 14 |

独立偏移及限幅运算从 175 个逻辑 LUT、12 级变为 176 个逻辑 LUT、11 级。完整模块的测量包含最终结果选择和存储更新逻辑。上述面积为映射单元数量，整机物理面积和跨模块路径由完整 SoC 测量给出。

## 复现命令

以下命令在仓库根目录执行，Python 环境需要提供 `pyosys`，生产数值测试需要支持当前源码的 Verilator。

```bash
python3 test/vector_offset_clamp/run.py \
  --reference 414099fa --out build/vector_offset/final_formal
python3 test/vector_round_carry/run_offset_formal.py \
  --out build/vector_offset/original_offset_formal
python3 test/vector_offset_clamp/synthesis.py \
  --reference 414099fa --out build/vector_offset/prefix_synthesis

python3 test/vector_input_banks/prepare_measurement.py \
  --reference 414099fa --out build/vector_offset/full_measurement
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/vector_offset/full_measurement/cases.json \
  --cases vector_reference vector_current \
  --out build/vector_offset/full_measurement/synthesis \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 test/vector_offset_clamp/paths.py \
  --reference build/vector_offset/full_measurement/synthesis/vector_reference \
  --current build/vector_offset/full_measurement/synthesis/vector_current \
  --proof build/vector_offset/final_formal/summary.json \
  --out build/vector_offset/full_paths.json

python3 test/vector_engine/run.py --xilinx --bus-width 32 --pes 8 --jobs 1 \
  --verilator verilator-modern --out build/vector_offset/fpga32
python3 test/vector_engine/run.py --xilinx --bus-width 64 --pes 8 --jobs 1 \
  --verilator verilator-modern --out build/vector_offset/fpga64
```
