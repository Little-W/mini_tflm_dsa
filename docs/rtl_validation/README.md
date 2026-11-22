# 当前 RTL 设计与验证结果

## 源码与目标

本目录中的完整功能测试、ASIC 结构检查和 FPGA 综合使用同一份固定 RTL。源码清单摘要为 `14cfa75662c93ab99b0cb6188913079ccdbdaab4497dfc782c9a35569e87b5ab`，各文件 SHA-256 见 [sources.json](sources.json)。

| 目标 | 数值 |
| --- | ---: |
| 完整 FPGA SoC 布局前 LUT 合计 | 不超过 45,000 |
| 最长寄存器间组合路径 | 不超过 10 个组合单元 |
| 特别关键路径的优先目标 | 少于 7 个组合单元 |
| 时钟频率 | 150 MHz，周期约 6.667 ns |
| DC 生产 NPU 的 cell area | 不超过 3,500,000 |

FPGA 配置包含 16 × 16 阵列、8 个向量 PE、64 位总线、7 × 8192 字节共享存储、4096 字节 im2col 缓存、16 个 PS 帧、PicoRV32、256 KiB CPU RAM、AXI 互连和 UART。ASIC 功能与结构检查使用 16 个向量 PE，其他容量参数按生产 DC 配置展开。

## 模块文件与流水数组

设计目录有 145 个 RTL 文件，分别定义 140 个模块和 5 个 package。112 个 NPU 文件均少于 1500 行，最大为 1488 行。原 PicoRV32 主模块保留在 `rtl/soc/picorv32_npu.v`，长度为 2201 行；其辅助模块分别使用独立文件。

| 文件 | 当前职责 | 行数 |
| --- | --- | ---: |
| `npu_top.sv` | 顶层配置与子系统连接 | 1483 |
| `npu_task_configuration.sv` | 任务参数和执行配置 | 1004 |
| `npu_matrix_engine.sv` | 矩阵计算与帧调度 | 1382 |
| `npu_output_pipeline.sv` | 偏置、量化和写回接口 | 585 |
| `conv_im2col_frontend.sv` | im2col 前端控制和子模块连接 | 1486 |
| `conv_im2col_prefetch.sv` | 预取位置和边界计算 | 473 |
| `vector_engine.sv` | 向量引擎子模块连接和算术控制 | 1488 |
| `vec_requant.sv` | 量化参数、数据顺序、分组和结果组装 | 1303 |
| `ps_window_scheduler.sv` | 窗口命令和下一窗口预测 | 798 |

同一字段跨阶段传递时使用数组，包括 `amount_q`、`batch_pipe_q`、`cfg_mode_q`、`cfg_k_q`、`cfg_m_q`、`g_weight_prediction.offset_q`、`prediction_depth_q`、`prediction_column_q` 和 `prediction_reads_frame_q`。数组元素保留各阶段的更新条件、复位方式和有符号类型。`accepted_coordinate_q` 等位置数组按横、纵坐标索引。

源文件组织、数组语义和长度检查见 [RTL 模块说明](../rtl_module_layout.md) 和 [rtl_layout.json](rtl_layout.json)。生产 RTL 使用普通可综合算术与同步存储描述；资源选择标志和显式 FPGA LUT、BRAM、DSP 原语的检查结果均为 0。

## 统一量化结构

矩阵量化使用一个 `vec_requant` 控制模块和一种单通道 `requant_compute_lane` 算术模块。逐张量参数广播给每个通道，逐通道参数按索引读取，INT8 与 INT16 通过模式选择。生产矩阵配置实例化两个算术通道，输入分组缓冲保持 512 行，每行 16 个 32 位元素及一个尾部标记。

单通道流水共七个使能边沿：乘法三阶段、移位两阶段、舍入与输出偏移一个阶段、裁剪一个阶段。有效位、尾部掩码、移位量和批次编号同步推进或暂停。输出共用 `requant_out_valid` 和 `requant_out_tile_done`，按模式进入 INT8 或 INT16 写回 FIFO。

向量 DW 的共享量化接口在 `REQUANT_COMPUTE_LANES == SIZE` 时启用。当前两个矩阵量化通道的生产配置保留向量引擎自己的标量算术，DW、ADD、AVGPOOL 和 Softmax 按操作复用该引擎的乘法与舍入资源。详细运算次序见 [统一量化说明](../unified_requant.md)。

## 完整功能检查

| 检查配置 | 任务数 | INT32 输出检查 | 帧位置与启动检查 | 结果 |
| --- | ---: | ---: | ---: | --- |
| FPGA 生产配置 | 86 | 216,348 | 1,860 | 通过 |
| ASIC 生产配置及同步 SRAM 行为模型 | 86 | 216,348 | 1,860 | 通过 |

完整测试覆盖卷积与 GEMM、WS/IS、逐张量及逐通道量化、INT8/INT16、尾部通道、数据反压、容量边界、输出顺序、配置切换和恢复。帧命令接收到 `frame_execute_start` 的延迟为 12 个周期，`frame_address_prepare` 的结果有效延迟为 11 个周期。SRAM 仿真检查同步读、逐位写掩码及同址并发访问，模型不包含工艺时序。

独立模块还保存以下检查：

- 调度器阶段数组的 2523 位完整状态与输出等价证明，以及 29 位列增量 SAT 检查。
- 乘法器四种输入寄存配置的逐周期证明、四态检查和 2,268,683 次完整 64 位结果比较。
- 预取位置算术的五项 SAT 检查、40,000 个四态输入向量及 160,000 次结果比较；其中 20,000 个输入向量包含 X/Z。三种前端配置共完成 126 项数值任务。
- 量化命令完成条件的四种完整控制配置、16,572 位状态与输出证明，以及 542,528 个 INT8/INT16 数值检查。

完整功能摘要、编译输入和仿真程序摘要保存在 [functional.json](functional.json)。各独立检查的实际参数与源文件摘要保存在相应 `test` 目录的说明和 JSON 中。

### 编译警告检查

FPGA 和 ASIC 编译分别保存 160 条和 177 条警告，类别包括时间单位、位宽转换及常量比较。多驱动、锁存器、未驱动和缺少输入连接的诊断数量均为 0。

位宽检查覆盖受配置限制的向量计数和数组索引、SRAM 银行与行地址分段、物理存储字的补齐位。线性地址的三个常量除数完成了 196,608 个商和余数逐值检查。诊断类别、有效范围及日志摘要见 [compiler_warnings.json](compiler_warnings.json)。

## 完整 SoC FPGA 综合

目标器件为 `xc7a200tfbg484-3`。普通映射和 LUT 等代价映射均使用当前固定源码生成的同一份完整 SoC 前级网表。LUT 等代价映射把 2 至 6 输入 LUT 的面积代价均设为 1，ABC 延迟目标为 6667 ps，连接延迟估计为 500 ps。

| 项目 | 普通映射 | LUT 等代价映射 |
| --- | ---: | ---: |
| 逻辑 LUT | 56,964 | 54,220 |
| 分布式 RAM 的名义 LUT 位置 | 664 | 664 |
| 移位寄存器的名义 LUT 位置 | 14 | 14 |
| 布局前 LUT 合计 | 57,642 | 54,898 |
| 触发器 | 41,654 | 41,649 |
| DSP | 311 | 311 |
| RAMB36 | 164 | 164 |
| RAMB18 | 78 | 78 |
| CARRY4 | 4,028 | 3,984 |
| 最长寄存器间组合路径 | 16 级 | 16 级 |
| 超过 10 级的端口数量 | 4,227 | 2,597 |

当前较小的布局前 LUT 合计为 **54,898**，超过 45,000 目标 **9,898**。两种映射中较短的最长路径为 **16 级**，仍超过 10 级目标。Vivado 布局布线尚未执行，物理 LUT 数量、建立时间、保持时间及 150 MHz 达成状态没有新测量结果。

LUT 合计按逻辑 LUT 单元、分布式 RAM 所需 LUT 位置和 SRL 所需 LUT 位置求和。该值在器件布局前统计；最终物理使用量以 Vivado 放置结果为准。组合路径检查覆盖完整连接图、跨模块连接、同步存储输入和 DSP 内部寄存器边界，按映射后的实际组合单元计数。

资源与目标状态见 [fpga_resources.json](fpga_resources.json) 和 [summary.json](summary.json)，模块资源归属见 [module_resources.json](module_resources.json)。

### 当前较长路径

普通映射共导出 4227 个超过 10 级的端口路径，完整起点、终点及单元类型见 [register_paths.csv](register_paths.csv)。表中每组寄存器只列一个位切片。

| 级数 | 起点 | 终点 | 终点端口 |
| ---: | --- | --- | --- |
| 16 | `u_block_dma_arbiter.u_dma.g_im2col.u_read_guard.addr_q [3]` | `u_block_dma_arbiter.u_dma.g_im2col.u_read_guard.pending_mask [2]` | `D` |
| 16 | `$99439.internal_register_output` | `u_matrix_engine.u_output_pipeline.u_vec_requant.g_serial_arithmetic.g_compute_lane[0].u_lane.u_product.o_product [60]` | `D` |
| 16 | `u_matrix_engine.u_task_configuration.o_ia_reuse_num_eff [6]` | `u_matrix_engine.u_output_pipeline.u_oa_writer.co_current_rows [0]` | `D` |
| 16 | `u_matrix_engine.u_task_configuration.o_ia_reuse_num_eff [6]` | `u_matrix_engine.u_output_pipeline.u_oa_writer.co_current_row_tiles_q [0]` | `D` |
| 15 | `$21042.internal_register_output` | `g_vector_engine.u_engine.u_scalar_multiplier.u_multiplier.o_product [60]` | `D` |
| 15 | `u_matrix_engine.o_frame_mode_q` | `u_matrix_engine.u_ia_loader.g_saved_demand_lookup.demand_lookup_match_q` | `D` |
| 15 | `u_matrix_engine.u_bias_loader.u_ctrl.current_block_idx [2]` | `u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.capacity_fault` | `D` |
| 15 | `u_matrix_engine.u_bias_loader.u_ctrl.current_block_idx [2]` | `u_matrix_engine.u_output_pipeline.is_bias_row_idx [0]` | `D` |

局部综合中，预取位置模块为 1238 个逻辑 LUT、1187 个触发器；完整模块最长路径为 12 级。其中已接收横坐标到投影横坐标的数据路径为 10 级，全部源寄存器到两个投影坐标的数据路径为 11 级。量化控制器以 `cmd_has_more_r` 保存本条 DMA 命令完成后是否仍需装载参数，`quant_need_load_r → cmd_has_more_r` 为 10 级，`cmd_has_more_r → state` 为 3 级，整个量化模块最长路径为 11 级。局部测量用于检查对应修改，完整 SoC 的最终组合路径由上表所列实际映射决定。

## ASIC 结构与 DC 检查

生产 NPU 的 ASIC 展开包含 256 个阵列计算单元、16 个向量 PE、两个量化运算通道和 165 个 SRAM 宏。其中 `RAMTP128X16` 为 60 个，`RAMTP1024X16` 为 105 个；量化分组缓冲使用 33 个 `RAMTP1024X16`，逻辑容量为 512 × 513 位。该缓冲的推断数组及 `regfile` 实例数量为 0，层次连接检查通过。

DC 生产入口、源文件准备和报告脚本的 44 项检查通过。脚本使用 150 MHz 约束，并分别导出最多 5000 条不同端点的建立、保持时间路径，以及 SRAM 双时钟时序弧。当前环境没有 Design Compiler 和目标 SMIC 工艺库，本轮没有新的 DC cell area 或静态时序结果；350 万面积目标保留为待测状态。

结构记录见 [asic_structure.json](asic_structure.json)，DC 入口检查见 [dc_profile.json](dc_profile.json)。

## 重复运行

在仓库根目录执行：

```bash
python3 test/rtl_layout/check.py --out build/rtl_layout
python3 test/fpga_integration/run.py --out build/fpga_integration --verilator verilator --jobs 1
python3 test/asic_integration/run.py --out build/asic_integration --verilator verilator --jobs 1
python3 test/requant_group_buffer_npu/run.py --out build/asic_npu_structure

MALLOC_ARENA_MAX=1 MALLOC_TRIM_THRESHOLD_=65536 MALLOC_MMAP_THRESHOLD_=65536 \
python3 scripts/fpga/open_fpga_synth.py --source-root . --cases soc_top \
  --out build/soc_mapping --max-register-path-cells 10

python3 scripts/fpga/netlist_metrics.py build/soc_mapping/soc_top/mapped.json \
  --top soc_top --register-origins build/soc_mapping/soc_top/pre_lut.il \
  --path-limit 5000 --group-limit 200 --minimum-path-cells 11 \
  --max-register-path-cells 10 --out build/soc_mapping/soc_top/critical_5000.json

MALLOC_ARENA_MAX=1 MALLOC_TRIM_THRESHOLD_=65536 MALLOC_MMAP_THRESHOLD_=65536 \
python3 scripts/fpga/remap_fpga_luts.py --source build/soc_mapping/soc_top \
  --out build/soc_equal_lut_cost --mode physical-cost --max-lut-inputs 6 \
  --small-lut-area-cost 1 --wire-delay-ps 500 --delay-target-ps 6667
```

开源综合使用 Yosys Slang 前端及 ABC。完整模块资源可用 `scripts/fpga/module_resources.py` 根据映射网表和前级网表重新统计。Vivado 与 DC 的运行入口分别见 [FPGA 器件测量](../fpga_150mhz_measurement.md) 和 [ASIC 综合配置](../asic_npu_r16_150.md)。

本次综合采用 jemalloc 管理临时内存，动态库摘要及环境变量见 [synthesis_environment.json](synthesis_environment.json)。运行示例中的 glibc 内存参数可按本机分配器替换；RTL、综合步骤和映射参数由保存的输入记录确定。
