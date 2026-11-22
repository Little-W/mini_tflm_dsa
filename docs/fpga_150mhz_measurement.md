# 完整 SoC 的器件测量

目标器件为 `xc7a200tfbg484-3`。生产配置包括 16×16 计算阵列、8 个向量处理单元、64 位 AXI、7 个 8,192 字节共享存储银行、4,096 字节 im2col 缓存、16 个 PS 帧和 512 行量化输入缓存。

设计目标为 Vivado 报告的 **Slice LUTs 不超过 50,000**，完整连接图中寄存器间组合路径不超过 **10 个组合单元**，并在 **6.667 ns** 时钟周期下满足建立时间和保持时间。面积统计包含逻辑 LUT、存储 LUT 和 SRL。`RAMB36 + RAMB18 / 2` 表示使用的 Block RAM Tile 数量。

## 板级 fpga_top 测量

当前固定源码的开源综合与功能结果保存在 [R16 测量目录](rtl_checkpoint_20261122_r16/README.md)。其中布局前 LUT 合计为 49,665，完整连接图最长路径为 13 级；本文件的 Vivado 命令用于产生该源码的实际器件资源和布局布线时序报告。

板级工程包含 50 MHz 输入时钟、150 MHz 时钟生成模块和 SoC。其统计范围与 `fpga_top_utilization.rpt` 一致：

```sh
vivado -mode batch -source scripts/fpga/vivado_synth_fpga.tcl \
  -tclargs build/vivado_fpga_150
```

结果写入 `build/vivado_fpga_150/reports/`，报告文件使用 `fpga_top_` 前缀。工程配置沿用 `create_project.tcl` 的参数和环境变量；输入指纹记录实际顶层参数、综合策略、宏定义、RTL、约束和内存初始化文件。

执行同一板级工程的布局布线：

```sh
VIVADO_RUN_IMPL=1 vivado -mode batch -source scripts/fpga/vivado_synth_fpga.tcl \
  -tclargs build/vivado_fpga_150_impl
```

布线后的结果保存到 `reports/routed/`。该测量入口生成检查点和报告。

## 独立 soc_top 综合

在仓库根目录执行：

```sh
vivado -mode batch -source scripts/fpga/vivado_synth_soc.tcl \
  -tclargs build/vivado_soc_synth
```

入口从 `config/npu_fpga.mk` 读取生产配置，并检查容量和总线参数。`regfile.v` 与其他公共模块使用 SystemVerilog 解析。综合输入直接来自当前仓库的 RTL。

每次运行保存以下文件：

| 文件 | 内容 |
|---|---|
| `source_manifest.json` | Git 提交与源码树、工具版本、器件、顶层参数、宏定义以及实际源文件和头文件的 SHA-256 |
| `hardware_config.mk` | 本次使用的硬件配置 |
| `soc_top_utilization.rpt` | 完整 SoC 的原生 Vivado 资源统计 |
| `soc_top_utilization_hier.rpt` | 按模块分层的资源统计 |
| `soc_top_timing_summary.rpt` | 建立时间、保持时间和约束覆盖情况 |
| `soc_top_timing_paths.rpt` | 各路径组的主要建立时间路径 |
| `soc_top_hold_paths.rpt` | 各路径组的主要保持时间路径 |
| `soc_top_endpoints.tsv` | 每个捕获时钟下全部端点的最差建立时间与保持时间路径 |
| `soc_top_high_fanout.rpt` | 高扇出网络 |
| `soc_top_synth.dcp` | 综合检查点 |
| `measurement.json` | 从上述实际报告提取的资源、时序和目标状态 |
| `pe_dsp_boundary/dsp_b_cascade.json` | 256 个 PE 的 DSP 寄存器参数、实际 B 端口连接和组合级联检查 |

报告生成后重新检查全部输入文件的内容。如果运行期间修改了任一输入，脚本终止结果汇总，避免将多个源码版本的内容记录为同一次测量。

综合与布线后记录计算阵列的 B 端口连接、实际 `BREG`、`BCASCREG`、`B_INPUT` 属性与网络连接，并保存完整 DSP 参数表。连接图分析依据这些寄存器参数确定组合边界；时序检查使用布线后的 setup 和 hold 报告。

## 从同一 RTL 执行布局布线

第二个参数指定独立 `soc_top` 的实际封装引脚与接口约束文件：

```sh
vivado -mode batch -source scripts/fpga/vivado_synth_soc.tcl \
  -tclargs build/vivado_soc_impl /absolute/path/soc_pins.xdc
```

`soc_pins.xdc` 应包含使用板卡的封装引脚、电平和接口时序要求。主时钟已由入口设置为 6.667 ns，附加文件应保留唯一的 `soc_top.clk` 时钟。

脚本依次执行综合、逻辑优化、布局、物理优化和布线，在 `routed/` 中保存资源报告、时序报告、路由状态与 `soc_top_routed.dcp`。实现检查覆盖完整路由、严重 DRC、内部时序约束、全部捕获时钟的建立时间和保持时间。遇到负时序余量时仍保存实际测量值，随后返回失败状态。

## 结果解释

`measurement.json` 中的 `slice_luts` 直接读取原生 Vivado 利用率报告，包含逻辑和存储两部分。TNS 与失败端点数量来自 Vivado 原生时序汇总；端点 TSV 保存有界诊断样本。

`maximum_observed_logic_levels` 表示所枚举端点最差时序路径中的最大逻辑级数。完整深度条件由同一网表的全部连接路径检查产生，保存在 `all_connected_paths_within_limit`；连接图不完整时该条件保持未确认。建立时间和保持时间还包含器件单元及布线延迟，最终频率状态由布线后的实现检查确定。

综合结果的 `timing_150mhz_confirmed` 为未确认。布线结果同时保存实际实现检查状态。资源条件、观察到的逻辑级数条件和频率条件分别记录，便于明确每项目标的测量状态。

本地 `netlist_metrics.py` 的结构统计用于定位组合层次和比较 RTL 修改。其 LUT 原语计数、布局工具的物理位置计数和 Vivado 的 Slice LUTs 分别保存，完整 SoC 的面积目标使用原生 Vivado 报告。

## 脚本验证

```sh
python3 -m unittest discover -s scripts/fpga/tests -p test_vivado_soc_results.py
python3 scripts/fpga/tests/test_vivado_timing.py --out /tmp/vivado_timing_checks
```

这些测试使用人工构造的报告和 Tcl 命令模型，检查源文件指纹、资源单位、端点汇总和执行顺序。实际器件测量由上面的 Vivado 命令生成。
