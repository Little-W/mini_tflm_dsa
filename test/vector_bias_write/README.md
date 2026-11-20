# 向量偏置的共享写入选择

`vector_engine` 将每拍的偏置数据字按目标索引分组。对于每拍 `B = BUS_WIDTH / 32` 个连续数据字，分组编号为目标索引对 `B` 取余。每组共用一个数据字选择器，各存储项独立检查目标索引及写入有效条件，保留同拍写入多个偏置的能力。

每个偏置使用一个 32 位、深度为 1 的 `REGFILE`，所有偏置保持并行异步读取。`TILE_INIT` 周期向全部存储项写入零值，`rst_n` 为零时保持原有内容。该结构保持写入、清零和读取的采样边沿，不增加流水级，也不指定存储映射属性。

## 完整状态比较

参考提交为主分支中的 `cd0455b`。`run_formal.py` 提取两份实际 `vector_engine.sv` 中的偏置逻辑，并直接使用当前 `REGFILE.v`。全部状态编码、装载类型、输入地址、有效通道数、复位值和 DMA 数据均为自由输入。

Yosys 的组合比较与时序归纳证明了所有偏置状态逐周期相同。8 组配置全部通过，包含 `BUS_WIDTH=32、64、96、128、256`，以及 `TILE=1、2、3、16、32` 的对应组合。源码检查同时确认偏置存储以外的逻辑保持相同。

## 向量数值回归

完整向量引擎与生产 DMA 联合运行，使用独立整数参考结果和 Xilinx 官方原语模型。两种总线配置均通过全部 592 项任务，编译输入逐文件核对与当前源码一致。

| 总线宽度 | 任务数 | 输出数 | 运行周期 | Add 任务 / 输出 | Softmax 任务 / 输出 |
|---|---:|---:|---:|---:|---:|
| 32 | 592 | 168,491 | 2,998,186 | 143 / 135,652 | 273 / 2,188 |
| 64 | 592 | 169,361 | 2,995,967 | 143 / 135,420 | 273 / 2,188 |

## 存储容量

完整生产 NPU 展开采用 `config/npu_fpga.mk`，两份设计的容量检查均通过。16 个偏置 `REGFILE` 共保存 512 位数据，容量脚本将这些实例归入 `vector_buffers`。

| 项目 | 参考设计 | 当前设计 |
|---|---:|---:|
| 全部顺序状态 | 798,153 位 | 798,153 位 |
| 向量缓冲 | 9,696 位 | 9,696 位 |
| 偏置存储 | 512 位 | 512 位 |
| `REGFILE` 实例 | 64 | 80 |

## 综合和组合路径

生产向量配置为 `TILE=16`、`PE_COUNT=8`、`BUS_WIDTH=64`。完整模块保留全部公开输出，使用相同的 Xilinx 七系列综合流程和官方原语模型。

| 项目 | 参考设计 | 当前设计 | 变化 |
|---|---:|---:|---:|
| 完整向量引擎逻辑 LUT | 13,219 | 12,785 | −434 |
| 完整向量引擎触发器 | 6,104 | 6,104 | 0 |
| CARRY4 | 872 | 872 | 0 |
| DSP48E1 | 16 | 16 | 0 |
| 分布式 RAM LUT | 248 | 248 | 0 |
| SRL LUT、RAMB18、RAMB36 | 0 | 0 | 0 |
| 偏置数据写入的最长寄存器路径 | 10 | 3 | −7 |
| 偏置写使能的最长寄存器路径 | 8 | 9 | +1 |
| 偏置读取的最长寄存器路径 | 2 | 2 | 0 |
| 全模块最长寄存器路径 | 19 | 18 | −1 |

独立偏置存储片段保留全部 512 位输出时，逻辑 LUT 为 1,142 和 118，触发器均为 512。完整模块的综合包含状态控制和公共逻辑优化，本次完整向量引擎的面积变化为减少 434 个逻辑 LUT。

路径长度统计寄存器之间实际经过的组合单元数量。150 MHz 目标由完整 SoC 布局布线后的时序分析检查。

## 复现

从仓库根目录运行，环境中需提供带 slang 插件的 Yosys Python 模块和 Verilator。

```bash
python test/vector_bias_write/run_formal.py \
  --out build/vector_bias_write/formal
python test/vector_bias_write/run_capacity.py \
  --out build/vector_bias_write/capacity --verilator verilator-modern
python test/vector_bias_write/prepare_measurement.py \
  --out build/vector_bias_write/inputs
python scripts/fpga/open_fpga_synth.py \
  --case-config build/vector_bias_write/inputs/cases.json \
  --cases storage_reference storage_bank_write vector_reference vector_bank_write \
  --out build/vector_bias_write/synthesis
python test/vector_bias_write/measure_paths.py \
  --reference build/vector_bias_write/synthesis/vector_reference \
  --candidate build/vector_bias_write/synthesis/vector_bank_write \
  --out build/vector_bias_write/paths.json
python test/vector_engine/run.py \
  --out build/vector_bias_write/interface_bus32 --bus-width 32 \
  --verilator verilator-modern --jobs 1 --xilinx
python test/vector_engine/run.py \
  --out build/vector_bias_write/interface_bus64 --bus-width 64 \
  --verilator verilator-modern --jobs 1 --xilinx
```
