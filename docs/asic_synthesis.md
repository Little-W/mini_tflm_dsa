# ASIC 综合与路径优化

综合使用 SMIC40 RVT 标准单元和双端口 SRAM 时序库。启用 `ASIC_SRAM` 的存储模块通过 `asic/rtl/smic40_sram_1r1w.sv` 映射到 `RAMTP128X16` 或 `RAMTP1024X16`，宏的面积和时序均参与综合统计。

## 环境与初始综合

设置 `STD_ROOT` 与 `SRAM_ROOT`，分别指向标准单元库和 SRAM 库。默认采用 TT、1.1 V、25 ℃。

```sh
make -C asic/synthesis syn \
  STD_ROOT="$STD_ROOT" SRAM_ROOT="$SRAM_ROOT" \
  TARGET_FREQ_MHZ=50 COMPILE_MODE=quick MAX_CORES=1
```

初始综合采用 50 MHz、单进程和较低优化强度。Design Compiler 的 `compile` 执行标准映射，`quick` 使用较低的面积优化强度；`standard` 使用较高的映射优化强度；`ultra` 调用 `compile_ultra`。

默认硬件参数来自 `config/npu.mk`：16×16 阵列、64 位 AXI4、九个 2 KiB
共享 bank、`IA_CACHE_BLOCKS=2` 和 `PS_FRAME_COUNT=4`。该配置使用全并行
量化。生产 FPGA 参数保存在 `config/npu_fpga.mk`，包含七个 8 KiB 共享
bank、`IA_CACHE_BLOCKS=4` 和 `PS_FRAME_COUNT=16`，可通过 `NPU_CONFIG`
选择这份配置进行 ASIC 结构检查。

`prepare-rtl` 在构建目录生成综合输入，将带默认值的输入端口转换为显式连接。RTL 源码、生成文件和综合结果分别保存在源码目录、构建目录的 `sources/` 以及构建目录根部。

## 量化输出缓冲的 SRAM 实现

`requant_group_buffer` 在 `ASIC_SRAM` 配置下，通过
`smic40_sram_1r1w` 保存完整的量化输入行。每行包含所有通道的 INT32
数据和一个 tile 完成标记，读写地址、读使能及输出保持方式与模块接口
一致。控制状态在复位或 `i_clear` 时清空，SRAM 数据阵列保持独立。

生产 FPGA 的七个 8 KiB 共享 bank 配置采用两个量化计算通道，分组缓冲
参数为 `p_lanes=16`、`p_rows=512`。使用 ASIC 编译定义展开同一容量配置，
得到以下结构：

| 项目 | 数值 |
|---|---:|
| 每行逻辑位宽 | 513 bit |
| 逻辑深度 | 512 行 |
| 有效存储容量 | 262,656 bit，32,832 byte |
| SRAM 宏型号 | `RAMTP128X16` |
| 深度方向分组 | 4 组，每组 128 行 |
| 每组宽度方向宏数量 | 33 |
| SRAM 宏总数 | 132 |
| 物理存储容量 | 270,336 bit，33 KiB |

每行未使用的高 15 位补零，其写掩码关闭。读写双方使用原始行地址，
完整行数据和 tile 标记在同一同步读取边沿更新。`MACRO_DEPTH=128`
固定了该缓冲的宏深度；位宽和深度方向均按参数计算宏数量。
FPGA 和通用仿真配置继续使用同步读出的 `regfile`。

从仓库根目录运行对应的 ASIC 展开命令：

```sh
make -C asic/synthesis elaborate \
  NPU_CONFIG="$PWD/config/npu_fpga.mk" \
  STD_ROOT="$STD_ROOT" SRAM_ROOT="$SRAM_ROOT"
```

RTL 展开并链接库之后，综合流程生成
`npu_top_requant_storage.rpt`。报告逐一列出量化缓冲区的宏数量、物理
容量和 `regfile` 子实例数量。上述生产参数应显示 132 个宏、270,336
个物理存储位和零个 `regfile` 子实例。检查通过后再执行标准单元映射。

修改 RTL 后，从源码重新执行 `prepare-rtl`、分析和展开，以生成包含
SRAM 实例的新 DDC。分模块综合使用新生成的展开结果，并将公共 RTL、
存储器封装、模块参数和子模块结果共同纳入源文件检查。

## 前 100 条最大延时路径

每轮综合生成以下文件：

| 文件 | 内容 |
|---|---|
| `npu_top_top100_delay.csv` | 按单元和网络传播延时之和排序的 100 条路径 |
| `npu_top_top100_delay.rpt` | 对应路径的逐引脚到达时间、增量延时及单元型号 |
| `npu_top_top100_slack.rpt` | 按时序裕量排序的路径及完整约束信息 |
| `npu_top_summary.rpt` | 时钟周期、建立时间裕量和保持时间裕量 |
| `npu_top_area.rpt` | 总单元面积与各层次面积 |

延时排序包含满足约束的路径。每个受约束终点取最大延时路径，然后进行全局排序。优化对象为其中重复出现的组合逻辑结构，包括地址运算、选择网络、编解码和反馈控制。

```sh
python3 scripts/asic/analyze_top_paths.py --run "$SYN_OUTPUT"
```

分析程序生成 `top_paths.json` 和 `top_paths.md`，统计各逻辑区域在 100 条路径中的出现次数和延时贡献。

## 分阶段提高频率

完成路径分析和 RTL 修改后，先在相同的 50 MHz 条件下重新综合并运行功能仿真。比较修改前后的路径延时、逻辑级数、面积及周期数。随后依次采用 150 MHz、400 MHz 及更高目标频率。

设计未改变时，可使用已映射 DDC 进行增量优化：

```sh
make -C asic/synthesis syn \
  STD_ROOT="$STD_ROOT" SRAM_ROOT="$SRAM_ROOT" \
  TARGET_FREQ_MHZ=150 COMPILE_MODE=standard MAX_CORES=1 \
  DESIGN_CHECKPOINT="$MAPPED_DDC" DESIGN_INCREMENTAL=1
```

各阶段使用独立的 `PROJ_TEMP` 保存结果。RTL 改变后，重新执行分析和展开；已展开的 DDC 用于同一份 RTL 的约束或优化参数调整。

SDC 为时钟周期预留 10% 建立时间不确定度和不超过 0.125 ns 的保持时间不确定度，输入与输出的最大接口延时各为时钟周期的 20%。综合报告分别给出建立与保持检查结果。布局布线阶段继续使用真实时钟树、布线寄生和工艺角完成时序分析。

## 部分和存储比较

`scripts/asic/run_ps_synthesis.py` 提供固定 16×16 阵列、64 位 AXI 和共享数据 RAM 的完整 NPU 综合入口。通过 `--source-root` 指定实现所在的工作目录，直接 INT32 分支同时设置 `--force-raw`。通过 `--frequency` 与 `--compile-mode` 选择阶段参数。`--checkpoint` 复用 DDC，`--incremental` 对已映射结果进行增量优化。

比较时，两种实现采用相同频率、单元库、SRAM 库、接口约束和综合强度。目录 SRAM、编解码器、分配器和反馈控制均计入实现成本。性能测量另行记录共享数据 RAM 与目录 RAM 的物理字节数。


## 分模块综合

对于完整 NPU，先生成展开后的 DDC，再按依赖顺序综合各模块：

```sh
python3 scripts/asic/run_ps_synthesis.py --elaborate-only \
  --std-db "$PS_STD_DB" --libs "$MEM_DB_PATH" --out build/ps_cost/elaborated
python3 scripts/asic/partition_synthesis.py \
  --elab-ddc build/ps_cost/elaborated/npu_top_elab.ddc \
  --std-db "$PS_STD_DB" --libs "$MEM_DB_PATH" \
  --cache build/ps_cost/module_cache --out build/ps_cost/mapped
```

综合结果按源文件、模块参数、子模块结果、频率和时序库的摘要保存。相同模块可在不同的部分和实现中复用；相关源文件或子模块改变时，重新综合受影响的模块。默认每个模块最多运行 300 秒，常驻与交换内存合计限制为 8 GiB，可通过 `--timeout` 和 `--max-memory-gib` 调整。

每个模块保留接口功能并独立映射。完整设计的路径分析在组合后的 NPU 上执行，覆盖跨模块路径。逻辑缓存容量和 SRAM 宏物理容量分别统计，宏的深度与位宽填充计入物理容量和面积。
