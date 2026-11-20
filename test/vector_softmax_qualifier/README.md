# Softmax 累加器写入资格

## 设计与受测源码

`vector_engine.sv` 为每个累加器项生成组合信号 `soft_selected`，计算
`softmax_s8 && (soft_exp_index == entry)`，并使用 `keep` 属性保留该比较结果。
累加器的 Softmax 写入条件为 `soft_selected && soft_exp_we`。下标和操作模式可以先行计算，
随后到达的指数响应接收信号直接参与当前项的写入选择。

写入过程保持原有顺序：计算结果、偏置装载、初始化和 Softmax 指数结果按原顺序更新
`acc_buf`，同一过程中的 `rhs_buf` 写入也保持不变。该修改增加 0 位寄存器、0 个接口周期。

- 参考提交：`7ef39f0101ebf39184d11dbdc80a4042faee75c2`。
- 参考 `vector_engine.sv` SHA-256：`05db06ede48b737f15a7993c8ed55a94d04324ff9a01dda645f6509c00ed06a7`。
- 当前 `vector_engine.sv` SHA-256：`47e1d50185518ed33522e0993698fc2d8cb5d0b52c41df52c855b6570c8b823b`。
- 关联 `vector_softmax.sv` SHA-256：`ed184fce3d3e6538ff24fe4e446f1aa06c409c05ad2cd707e441faf6d487efd6`。

结构化结果见 [measurement.json](measurement.json)。报告生成程序核对受测源码、全部数值模型输入文件、
生成的比较模块、形式证明日志、映射网表、映射日志及仿真程序的 SHA-256。

## 完整写入过程证明

`run_formal.py` 从参考和当前 RTL 分别提取完整 `g_accumulator_write`，保留各项非阻塞赋值的优先顺序，
比较每个累加器和 RHS 项的次值及写使能。输入和原存储内容均为任意二态值，
覆盖所有状态编码、操作模式、同时写入、无效周期保持和复位期间保持。
提取范围以外的 `vector_engine.sv` 文本必须与参考完全一致。

| BUS_WIDTH | TILE | PE_COUNT | 通用实现 | FPGA 实现 | 两种实现合计比较位数 |
|---:|---:|---:|---|---|---:|
| 32 | 16 | 8 | 通过 | 通过 | 1,600 |
| 64 | 16 | 8 | 通过 | 通过 | 1,600 |
| 128 | 16 | 8 | 通过 | 通过 | 1,600 |
| 64 | 3 | 2 | 通过 | 通过 | 300 |
| 32 | 1 | 1 | 通过 | 通过 | 100 |
| 64 | 32 | 8 | 通过 | 通过 | 3,200 |

12 组证明共比较 8,400 位，全部通过。每项包含 32 位累加器次值、16 位 RHS 次值及两个写使能。
FPGA 分支采用工具包中的官方 Xilinx 原语模型。

## 局部寄存器间映射

测量采用 `TILE=16`、`PE_COUNT=8`、`BUS_WIDTH=64`，输出包含全部累加器与 RHS 寄存器的数据端和同步控制端。
全部映射均通过 ABC9 功能等价检查，组合图完整。

| 测量范围与映射方式 | 参考逻辑 LUT | 当前逻辑 LUT | 参考/当前 FF | 参考最长级数 | 当前最长级数 |
|---|---:|---:|---:|---:|---:|
| 完整写入过程，native | 1,509 | 1,358 | 1,773 / 1,773 | 6 | 5 |
| 完整写入过程，physical-cost | 1,193 | 1,209 | 1,773 / 1,773 | 5 | 5 |
| 实际 Softmax 接收条件与完整写入过程，physical-cost | 1,183 | 1,212 | 1,779 / 1,779 | 7 | 6 |

`physical-cost` 使用与生产流程相同的 8 输入映射设置、6,667 ps 目标和 300 ps 连线成本。
表中 LUT 数量为映射逻辑单元数量，物理 LUT 位置须由完整设计布局统计。

实际接收条件测量直接提取 `vector_engine` 的 `soft_lut_rsp_valid` 及 `vector_softmax` 的状态枚举、
`lut_accept_fire` 和 `exp_we` 表达式。它保留 `rd_raw_valid` 对原始数据与已保存数据的选择，
以及所选数据符号位对指数写使能的影响。`soft_exp_we` 在此范围内由组合逻辑产生；
`soft_state`、`rd_done` 和 `rd_error` 作为输入寄存器。两种设计均采用相同边界。

| 实际组合来源到 `acc_buf` 的最大级数 | 参考 | 当前 |
|---|---:|---:|
| `rd_raw_valid` | 7 | 4 |
| `rd_done` | 7 | 5 |
| `rd_error` | 7 | 6 |
| `soft_state`，对应 Softmax 的 `c_st` | 7 | 6 |
| 向量 `state` | 7 | 6 |
| `rd_raw_data` / `soft_lut_data` | 7 / 7 | 4 / 4 |
| `soft_exp_index` | 4 | 5 |
| `c` / `compute_index` | 6 / 6 | 5 / 5 |
| `active` | 3 | 3 |

实际接收条件范围的逻辑 LUT 增加 29 个。`rd_raw_valid` 最大路径在参考设计终止于扁平寄存器名
`acc_buf [64]` 的 `CE`，当前设计终止于同名寄存器的 `D`；比较均包含所有累加器的数据和控制端点。
`rhs_buf` 最大级数保持为 5。独立输入边界下的 `soft_exp_we→acc_buf` 路径为 4→3 级。
完整逐单元路径和原始网表哈希保存在结构化报告中。

这些结果覆盖所列实际组合表达式与写入过程。完整 SoC 面积与最长路径由对应固定 RTL 的整机测量确定，
150 MHz 仍须厂商完整布线后静态时序检查。

## 生产数值验证

使用实际 `vector_engine`、生产 DMA 和官方 Xilinx 原语模型重新编译并运行
`TILE=16`、`PE_COUNT=8`、`BUS_WIDTH=64` 的数值测试，结果如下。

| 项目 | 结果 |
|---|---:|
| 任务 | 592 项通过 |
| 输出值 | 168,601 个 |
| Add 任务 / 输出 | 143 / 135,305 |
| Softmax 任务 / 输出 | 273 / 2,188 |
| 任务周期合计 | 2,979,488 |
| 输入存储观察器周期 | 2,985,409 |
| 普通 / 窗口 / Pool 输入观察次数 | 17,684 / 68,838 / 3,044 |

592 项任务的每项周期和全部统计字段与已完成参考数值结果相同。
参考数值模型中的 `vector_engine.sv` 哈希与本次形式证明参考源码一致。

## 复现命令

先加载项目工具环境，然后在受测源码目录运行以下命令。
`--numeric-reference` 指向参考实现的 `test/vector_engine/run.py` 结果目录中的 `summary.json`。
当前记录使用 `worktrees/vector_r22_offset/build/vector_r22_offset/fpga64/summary.json`。

```bash
measure_out=build/vector_softmax_qualifier
synthesis_lock=/tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock

python3 test/vector_softmax_qualifier/run_formal.py --out "$measure_out/formal"
python3 test/vector_softmax_qualifier/prepare_measurement.py --out "$measure_out/local"
python3 scripts/fpga/open_fpga_synth.py --source-root . \
  --case-config "$measure_out/local/cases.json" --cases reference current \
  --out "$measure_out/local/results" --lock-file "$synthesis_lock"

python3 test/vector_softmax_qualifier/prepare_measurement.py \
  --out "$measure_out/connected" --softmax-control
python3 scripts/fpga/open_fpga_synth.py --source-root . \
  --case-config "$measure_out/connected/cases.json" --cases reference current \
  --through pre_lut --out "$measure_out/connected/pre" --lock-file "$synthesis_lock"

for label in reference current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source "$measure_out/local/results/$label" --out "$measure_out/cost/$label" \
    --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 \
    --max-lut-inputs 8 --lock-file "$synthesis_lock"
  python3 scripts/fpga/remap_fpga_luts.py \
    --source "$measure_out/connected/pre/$label" --out "$measure_out/connected/cost/$label" \
    --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 \
    --max-lut-inputs 8 --lock-file "$synthesis_lock"
done

python3 test/vector_softmax_qualifier/measure_paths.py \
  --build "$measure_out" --out "$measure_out/paths.json"
python3 -u test/vector_engine/run.py --out "$measure_out/fpga64" \
  --verilator verilator-modern --pes 8 --tile 16 --bus-width 64 --xilinx --jobs 2
python3 test/vector_softmax_qualifier/collect.py --build "$measure_out" \
  --numeric-reference ../vector_r22_offset/build/vector_r22_offset/fpga64/summary.json \
  --out test/vector_softmax_qualifier/measurement.json
```

已经压缩的中间文件可按 `build/vector_softmax_qualifier/intermediate_archive.json` 恢复。
`collect.py` 可直接读取相应 gzip 文件并核对解压内容的哈希。
