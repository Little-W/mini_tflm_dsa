# ASIC 综合环境

本目录提供 `npu_top` 的 Design Compiler 综合流程及 SRAM 宏功能仿真。

```text
asic/
  Makefile                    综合与仿真入口
  rtl/                        工艺 SRAM 宏封装
  synthesis/
    Makefile                  综合参数及库路径
    constraints/              时钟与 I/O 约束
    filelists/                RTL 文件列表
    scripts/                  库转换、综合和报告脚本
  tests/                      SRAM 宏测试
```

## 工艺库

默认标准单元库为 `/media/6/IC/lib/SMIC40_2025` 中的 SMIC40 RVT，使用 `tt_v1p1_25c` 条件。SRAM 宏来自 `/media/6/IC/lib/SRAM_Lib_2025`，使用 1.10 V、25 °C 的典型条件。两个根目录可分别通过 `STD_ROOT` 和 `SRAM_ROOT` 覆盖。工艺库文件不包含在本仓库中。

`synthesis/scripts/compile_sram_libs.tcl` 使用 Synopsys Library Compiler 将 SRAM Liberty 模型转换为 `.db`，存放在各综合输出目录的 `libs/` 子目录。综合时标准单元作为目标库，SRAM 作为链接库；宏的功能 Verilog 模型用于仿真。

## SRAM 封装

`rtl/smic40_sram_1r1w.sv` 使用 `RAMTP128X16` 或 `RAMTP1024X16` 拼接所需字宽和深度，支持独立同步读写及逐位写掩码。读取使能有效时输出在时钟沿更新，未读取时保持输出。当前 SoC/NPU 宏接入位置包括输入缓存、部分和存储、权重行缓存、输出 FIFO，以及 PCR 面板引擎的输入面板、部分和页池和空闲页栈。

宏的同地址同时读写结果未定义；仿真封装会报告这一冲突。小容量状态寄存器和采用其他访问方式的数组由综合器映射为标准单元。SRAM 容量向宏的物理尺寸取整，资源报告应以实际宏实例为准。

## 运行

从仓库根目录运行：

```bash
make -C asic sram-test       # 真实宏功能模型与封装测试
make -C asic npu-test        # 标准 NPU 顶层仿真
make -C asic paper-test      # PCR 面板引擎顶层仿真
make -C asic syn             # 标准 NPU 综合
make -C asic summary         # 综合摘要
make -C asic/synthesis elaborate PAPER_ENGINE=1 NPU_SIZE=16  # 检查论文引擎和宏引用
```

SRAM 功能仿真使用 Icarus Verilog 或 VCS。NPU 仿真禁用厂商模型中的器件级时序检查，以便验证零延迟 RTL 与宏的功能连接；实际时序由工艺时序库和综合约束分析。

综合默认使用 `SIZE=4`、`IA_CACHE_BLOCKS=32`、`PS_FRAME_COUNT=4` 和 400 MHz 目标。可直接设置参数，例如：

```bash
make -C asic/synthesis syn NPU_SIZE=4 NPU_IA_CACHE_BLOCKS=4 \
  NPU_PS_FRAME_COUNT=4 TARGET_FREQ_MHZ=400 MAX_CORES=2
make -C asic/synthesis syn PAPER_ENGINE=1 NPU_SIZE=16 \
  NPU_IA_CACHE_BLOCKS=64 NPU_PS_FRAME_COUNT=25
```

综合输出默认位于 `build/asic/npu_top/`，包含网表、时序、面积、宏引用和检查报告。可使用 `PROJ_TEMP` 指定其他输出目录。`PAPER_ENGINE=1` 启用 PCR 面板引擎，页池与面板上限由 `PS_POOL_BYTES`、`PANEL_MAX_R`、`PANEL_MAX_W` 指定。摘要分别列出建立时间与保持时间的最差余量；电容等设计规则检查结果见 `npu_top_constraints.rpt`。并行运行时应为每个任务指定独立的 `PROJ_TEMP`。
