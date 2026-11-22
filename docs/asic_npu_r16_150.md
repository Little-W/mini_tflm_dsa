# 150 MHz 完整 NPU ASIC 综合配置

`scripts/asic/run_ps_synthesis.py` 的 `npu_r16_150` 配置使用上传 DC 报告中的完整 NPU 容量，并显式指定十六个向量处理单元和十六路窗口输出。目标频率为 150 MHz，目标总单元面积为 `3500000`，存储采用 RAW 模式。

## 硬件与工具参数

| 项目 | 参数与取值 |
| --- | --- |
| 顶层 | `npu_top` |
| 计算阵列 | `SIZE=16`、`DATA_WIDTH=16`、`WEIGHT_WIDTH=16` |
| AXI 数据及内部地址 | `BUS_WIDTH=64`、`ADDR_WIDTH=19`、`REG_WIDTH=32` |
| 共享 RAM | `SHARED_BANK_BYTES=8192`、`SHARED_BANK_COUNT=7`，共 57,344 字节 |
| IA 缓存 | `IA_CACHE_BLOCKS=4` |
| im2col 缓存 | `IM2COL_CACHE_BYTES=4096`，两路、128 字节缓存行 |
| 部分和帧数 | `PS_FRAME_COUNT=16` |
| RAW 部分和空间 | `GEMMORA_PS_POOL_BYTES=49152`、`GEMMORA_PS_FORCE_RAW` |
| 向量与窗口并行度 | `DW_PE_COUNT=16`、`VECTOR_PE_COUNT=16`、`WINDOW_LANES=16` |
| AXI 未完成事务数量 | 读取和写入各四项 |
| 运行模式 | `ENABLE_IS_MODE=1`、`ENABLE_PER_CHANNEL=1` |
| 综合方式 | `standard`，默认最多四个核心 |
| 时钟 | 150 MHz，对应周期约 6.666667 ns |
| 面积目标 | 总单元面积不超过 `3500000`，单位沿用库及 `report_area` |

入口使用 `SYNTHESIS`、`ASIC_SYNTHESIS`、`ASIC_SRAM`、`GEMPACT_PS_COMPRESS` 及表中存储宏定义。`legacy_ps` 配置保留已有的 50 MHz、九组 2 KiB 共享 RAM、四帧部分和配置；选择 `npu_r16_150` 即可使用上述生产参数。命令行的频率、核心数、存储组数和 RAW 选项可以显式覆盖相应默认值，最终取值完整写入 `run.json`。

## 准备综合输入

以下命令保存 RTL、包含文件、SRAM 封装、原始约束副本、综合脚本和输入文件摘要，生成独立的 `run.tcl`。准备操作可以在缺少 DC 与工艺库的环境中运行。

```bash
python3 scripts/asic/run_ps_synthesis.py \
  --profile npu_r16_150 \
  --prepare-only \
  --out build/asic/npu_r16_150_prepare
```

输出目录包含：

| 文件或目录 | 内容 |
| --- | --- |
| `sources/` | 本次输入 RTL、可选端口展开结果、包含文件和 SRAM 封装 |
| `flow/scripts/` | 本次使用的 DC Tcl 脚本 |
| `flow/constraints/` | 与仓库内容相同的约束副本 |
| `run.tcl` | 完整环境参数和综合调用 |
| `environment.json` | 环境参数的结构化记录 |
| `run.json` | 配置、原文件及输入副本的 SHA-256、库状态和执行状态 |

准备操作的 `run.json` 写入 `dc_executed=false`、`execution_status=NOT_RUN`、`passed=null`。缺少的库文件列在 `missing_libraries`。准备过程的返回码为零表示输入准备完成。

## 执行 DC

标准单元库采用上传报告所用的 TT 1.1 V、25 °C 配置。存储库目录需要同时包含：

- `RAMTP128X16_tt_1p10v_1p10v_25c.db`
- `RAMTP1024X16_tt_1p10v_1p10v_25c.db`

在已安装 DC 和工艺库的环境中执行：

```bash
python3 scripts/asic/run_ps_synthesis.py \
  --profile npu_r16_150 \
  --std-db "$STD_DB_FILE" \
  --libs "$SRAM_DB_DIRECTORY" \
  --timeout 3600 --max-memory-gib 10 \
  --out build/asic/npu_r16_150
```

`STD_DB_FILE` 指向 `scc40nll_vhsc40_rvt_tt_v1p1_25c_basic.db`。实际执行前检查工具和三个库文件，执行后检查原文件、输入副本和库文件是否保持一致。库文件的 SHA-256 记录在 `library_sha256`。

`run_completed` 表示 DC 是否完整执行；`targets_met` 依据面积、建立时间、保持时间和两类端点报告数量共同计算。该生产配置只有在总面积满足目标、最差建立及保持裕量均非负、两类报告均包含至少各自请求数量的不同端点时，才将 `passed` 写为真。实际数值保存在 `targets`，详细时序约束和工具诊断保留在原报告中。

输出目录可以保存已经准备好的输入。存在 DC 日志、DDC 或时序面积报告时，入口要求选择新的输出目录，以保留已有结果并确保本次状态只来自当前运行。

`--report-only --checkpoint <mapped.ddc>` 可对已有映射结果重新导出报告，入口会检查已有记录中的硬件参数与源码摘要。`--elaborate-only` 用于只完成读取、展开和链接，不计算面积或时序目标是否达成。

## 路径及面积报告

生产配置默认请求 5,000 个不同的建立时间端点和 5,000 个不同的保持时间端点。每个端点保留最差裕量路径，按裕量排序。脚本按端点名称去重；存在重复端点时扩大候选数量。设计可用端点少于请求值时，导出实际数量并在覆盖报告中记录候选搜索是否已经完成。

| 报告 | 内容 |
| --- | --- |
| `npu_top_setup_paths.csv`、`.rpt` | 不同端点的建立时间路径、裕量、逻辑级数、逐引脚时间及单元类型 |
| `npu_top_hold_paths.csv`、`.rpt` | 不同端点的保持时间路径及逐引脚信息 |
| `npu_top_setup_paths_full.rpt` | DC 原生建立时间报告，包含转换时间、电容和网络信息 |
| `npu_top_hold_paths_full.rpt` | DC 原生保持时间报告 |
| `npu_top_path_coverage.tsv` | 每类路径的请求数量、导出数量、候选数量和搜索状态 |
| `npu_top_area.rpt` | 总面积、组合面积、时序面积、宏面积及分层面积 |
| `npu_top_check_design.rpt`、`npu_top_check_design_elab.rpt` | 链接后及综合后的设计检查 |
| `npu_top_check_timing.rpt`、`npu_top_constraints.rpt` | 时序完整性及约束检查 |
| `warnings.json` | 日志和检查报告中的警告、错误编号及相关上下文 |
| `npu_top_summary.rpt` | 频率、建立和保持裕量及整体时序状态 |

已有的 `top100_delay` 和 `top100_slack` 报告继续生成，可供现有分析脚本读取。通过 `--setup-paths` 和 `--hold-paths` 调整报告数量，生产配置的建立时间端点请求值至少为 5,000。

## SRAM 双时钟检查

`9_sram_clock_arcs.tcl` 读取每个 SRAM 宏的 `CLKA`、`CLKB` 和 `COLLDISN`，导出时钟网络、相关时钟、可用的固定值以及两个时钟引脚是否连接到同一网络。

对每个存储库，脚本保存 `report_lib -timing_arcs` 结果，并查询 `CLKA→CLKB` 与 `CLKB→CLKA` 两个方向的库弧，记录 `timing_type` 和 `when` 条件。工具版本不支持独立库弧查询时，表格中的状态指向完整库报告。

对应文件为 `npu_top_sram_clock_pins.tsv`、`npu_top_sram_clock_arcs.tsv`、`npu_top_sram_clock_diagnostics.rpt` 和每个 SRAM 库的 `*_timing_arcs.rpt`。这些检查用于分析同源时钟、库条件与保持时间要求，保持现有时钟约束和库检查有效。

## 本地验证范围

```bash
python3 test/asic_profile/check.py
```

本地已执行生产配置和已有配置的 `prepare-only`，并通过 Python 与 Tcl 命令模型检查。检查覆盖完整生产参数、RAW 空间、源码摘要、约束副本、Tcl 字面字符串、各 5,000 个不同端点的排序与导出、SRAM 双向条件弧、库弧查询兼容分支、面积和保持时间未达标的状态记录及警告上下文。

当前环境未运行 DC，也未加载 SMIC40 工艺库。上述本地检查验证输入准备与报告逻辑；新的单元面积和时序数值由实际 DC 运行产生。
