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

标准单元使用 SMIC40 RVT 的 `tt_v1p1_25c` 时序库；SRAM 宏使用 1.10 V、25 °C 的典型条件。工艺库文件需由使用者自行提供，并通过环境变量指定各自的根目录：

```bash
export STD_ROOT="<SMIC40_2025 目录>"
export SRAM_ROOT="<SRAM_Lib_2025 目录>"
```

标准单元和 SRAM 时序库的目录结构及文件名称由 `synthesis/Makefile` 定义，可通过其中的变量调整。

`synthesis/scripts/compile_sram_libs.tcl` 使用 Synopsys Library Compiler 将 SRAM Liberty 模型转换为 `.db`，存放在各综合输出目录的 `libs/` 子目录。综合时标准单元作为目标库，SRAM 作为链接库；宏的功能 Verilog 模型用于仿真。

## SRAM 封装

`rtl/smic40_sram_1r1w.sv` 使用 `RAMTP128X16` 或 `RAMTP1024X16` 拼接所需字宽和深度，支持独立同步读写及逐位写掩码。读取使能有效时输出在时钟沿更新，未读取时保持输出。当前 SoC/NPU 宏接入位置包括输入缓存、部分和存储、权重行缓存、输出 FIFO，以及统一计算路径的 IA/PS 共享 bank。

宏的同地址同时读写结果未定义；仿真封装会报告这一冲突。小容量状态寄存器和采用其他访问方式的数组由综合器映射为标准单元。SRAM 容量向宏的物理尺寸取整，资源报告应以实际宏实例为准。

## 运行

从仓库根目录运行：

```bash
make -C asic sram-test       # 真实宏功能模型与封装测试
make -C asic npu-test        # 标准 NPU 顶层仿真
make -C asic pcr-test        # 统一路径 PS 压缩顶层仿真
make -C asic syn             # 当前配置的 NPU 综合
make -C asic summary         # 综合摘要
make -C asic/synthesis elaborate PCR_ENGINE=1 NPU_SIZE=16  # 检查统一路径与 SRAM 宏引用
```

SRAM 功能仿真使用 Icarus Verilog 或 VCS。NPU 仿真禁用厂商模型中的器件级时序检查，以便验证零延迟 RTL 与宏的功能连接；实际时序由工艺时序库和综合约束分析。

综合读取仓库的 `config/npu.mk`，也可通过 `NPU_CONFIG` 选择另一份配置。默认使用 16×16 阵列、64 位 AXI4、七个 2 KiB 共享 bank 和 400 MHz 综合目标。频率是约束目标，实际时序结果记录在综合报告中。

| 参数 | 范围 | 默认值 |
|---|---|---:|
| `NPU_AXI_DATA_WIDTH` | 32、64 位，传入 RTL 的 `BUS_WIDTH` | 64 |
| `SHARED_BANK_BYTES` | 2048、4096、8192 字节 | 2048 |
| `SHARED_BANK_COUNT` | 6、7、8、9 | 7 |

共享数据 RAM 总量为 `SHARED_BANK_BYTES × SHARED_BANK_COUNT`，默认 14336 字节。每层执行前为 IA 分配 1、2 或 4 个 bank，其余用于 PS。S16 输入至少需要两个 IA bank；跨 K 的 RAW32 部分和至少需要四个 PS bank，经严格范围检查的 S24、S16 部分和上限分别要求至少三个、两个 PS bank。任务执行期间分配保持固定。

NPU 的控制寄存器在 SoC 中使用固定 32 位数据、16 位地址的 AXI-Lite 接口；`NPU_AXI_DATA_WIDTH` 控制张量数据的 AXI4 接口。综合顶层 `npu_top` 的任务配置端口由 SoC 的 AXI-Lite 寄存器模块连接。

```bash
make -C asic/synthesis syn NPU_AXI_DATA_WIDTH=64 \
  SHARED_BANK_BYTES=2048 SHARED_BANK_COUNT=7 \
  TARGET_FREQ_MHZ=400 MAX_CORES=2

make -C asic/synthesis syn NPU_AXI_DATA_WIDTH=32 \
  SHARED_BANK_BYTES=4096 SHARED_BANK_COUNT=8 \
  TARGET_FREQ_MHZ=400 MAX_CORES=2
```

`PCR_ENGINE=1` 启用统一路径中的 PS 编码和 frame 调度。ASIC 共享 RAM 使用同步 128 位 1R1W bank，逻辑行数为 `SHARED_BANK_BYTES / 16`。生产路径为 `ia_ps_shared_ram` → `smic40_sram_1r1w`，共享 bank 固定使用 `MACRO_DEPTH=128`。

| 每个共享 bank | 128 位行数 | 每 bank 的 `RAMTP128X16` 数量 | 七 bank 的宏数量 | 七 bank 数据容量 |
|---:|---:|---:|---:|---:|
| 2 KiB | 128 | 8 | 56 | 14 KiB |
| 4 KiB | 256 | 16 | 112 | 28 KiB |
| 8 KiB | 512 | 32 | 224 | 56 KiB |

三种配置使用全部宏数据位，逻辑数据容量与物理数据容量相等。目录、缓存标签和其他存储分别统计。完整说明见 [共享 RAM 映射](../docs/shared_ram_mapping.md)。

以下检查通过生产封装展开 SRAM 实例，覆盖三种 bank 大小与 6 至 9 个 bank，核对宏数量、位宽、时钟和控制连接：

```bash
python3 test/shared_ia_ps/check_asic_mapping.py \
  --yosys /path/to/yosys --out build/asic/shared_ram_mapping
```

该脚本使用 SRAM 宏端口的黑盒声明，报告结构连接和数据容量。工艺时序、面积和功耗由实际工艺库及 Design Compiler 流程报告。

综合输出位于 `build/asic/`，目录名称包含 AXI4 数据宽度和 bank 参数。可使用 `PROJ_TEMP` 指定其他输出目录。报告包含网表、时序、面积、宏引用和设计规则检查；摘要分别列出建立时间与保持时间的最差余量，电容等约束见 `npu_top_constraints.rpt`。并行运行时应为每个任务指定独立的 `PROJ_TEMP`。
