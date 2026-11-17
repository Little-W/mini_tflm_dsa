# 共享 IA/PS 容量与软件分配

通用及 ASIC 配置保存在 [`config/npu.mk`](../config/npu.mk)，FPGA 配置保存在 [`config/npu_fpga.mk`](../config/npu_fpga.mk)。两者默认使用 16×16 阵列、8 个 VCE PE 和 4 KiB 窗口缓存。通用配置的共享 IA/PS 数据容量为 18 KiB，FPGA 为 56 KiB。`scripts/capacity` 计算缓冲数组及元数据，并通过 Verilator 展开统计完整顺序逻辑状态；物理 RAM 的组织与复现命令见 [共享 RAM 映射](shared_ram_mapping.md)。

## 物理容量与任务分配

通用及 ASIC 的默认参数为：

```make
PCR_ENGINE ?= 1
SIZE ?= 16
NPU_AXI_DATA_WIDTH ?= 64
IM2COL_CACHE_BYTES ?= 4096
SHARED_BANK_BYTES ?= 2048
SHARED_BANK_COUNT ?= 9
IA_CACHE_BLOCKS ?= 2
PS_FRAME_COUNT ?= 4
AXI_READ_OUTSTANDING ?= 4
PS_POOL_BYTES ?= 16384
PS_FORCE_RAW ?= 0
CAPACITY_REPRESENTATION ?= adaptive
```

`PCR_ENGINE=1` 启用统一计算路径中的 PS frame 存储和调度。共享数据容量为 `SHARED_BANK_BYTES × SHARED_BANK_COUNT`。通用配置值为 `2048 × 9 = 18432` 字节；FPGA 默认值为 `8192 × 7 = 57344` 字节，配置中的 `PS_POOL_BYTES=49152`。两个 bank 参数在编译时确定；每层执行前的软件分配决定其中多少 bank 用于 IA 和 PS。

| `SHARED_BANK_BYTES` | 每 bank 的 128 位行数 | `SHARED_BANK_COUNT=6、7、8、9` 时的数据总容量 |
|---:|---:|---|
| 2048 | 128 | 12、14、16、18 KiB |
| 4096 | 256 | 24、28、32、36 KiB |
| 8192 | 512 | 48、56、64、72 KiB |

ASIC 支持表中的三种 bank 大小，均使用完整的 `RAMTP128X16` 数据容量。FPGA 工程入口要求 `SHARED_BANK_BYTES=8192`，每个 bank 使用两个 `RAMB36E1` 的全部数据位。每个 FPGA bank 另有 1024 字节 parity 容量，单独统计，不包含在共享数据总量中。

`NPU_AXI_DATA_WIDTH` 可选 32、64 位，默认 64 位，控制 NPU AXI4、SoC 数据互连及主存数据接口。NPU 的 AXI-Lite 配置接口使用固定 32 位数据和 16 位地址。共享 SRAM 内部接口始终为 128 位；AXI4 数据宽度与 bank 大小分别配置。

`IM2COL_CACHE_BYTES` 设置原始输入窗口缓存的数据容量，支持 512 B～64 KiB 的二次幂容量，默认 4 KiB。容量求解保留所选值，统计数据以及每条 16 B 缓存行的 75 位标签与使用状态。`capacity-show` 的 `im2col_cache_guidance` 和 `menuconfig` 帮助显示当前容量对应的卷积窗口尺寸。完整公式与常用配置见 [im2col 缓存容量配置](im2col_cache_configuration.md)。

软件可分配 1、2 或 4 个 bank 给 IA。IA 与 PS 使用互不重叠的 bank 集合，且分配在任务执行期间保持不变。能力寄存器的 `IA_BANK_MASK` 指定允许的 IA bank 数；驱动进一步根据输入格式、PS 长度上限和任务形状筛选分配。

| 项目 | 配置或约束 |
|---|---|
| 每个物理 bank | 同步 1R1W，每周期最多一次读和一次写 |
| IA 字节数 | `IA_BANKS × SHARED_BANK_BYTES` |
| PS 字节数 | `(SHARED_BANK_COUNT − IA_BANKS) × SHARED_BANK_BYTES` |
| IA 接口 | 紧凑 S8 每行 1 个字；S16 每行 2 个字，至少分配 2 个 bank |
| PS 接口 | 每行 0 至 4 个 128 位字，分别访问不同 bank |
| 共享 PS 目录 | 1024 行，目录项位宽随 bank 深度计算 |
| 最大 frame 数 | `PS_FRAME_COUNT`，默认 16 |
| 紧凑 S8 的双缓冲容量要求 | `512R ≤ IA_BANKS × SHARED_BANK_BYTES` |
| S16 的双缓冲容量要求 | `1024R ≤ IA_BANKS × SHARED_BANK_BYTES` |
| RAW32 跨 K | PS 至少 4 个 bank，每有效矩阵行 64 字节 |
| S24 跨 K | PS 至少 3 个 bank，并通过中间累加范围检查 |
| S16 跨 K | PS 至少 2 个 bank，并通过中间累加范围检查 |

例如，默认七个 2 KiB bank 中，IA=1、2、4 分别提供 2、4、8 KiB 输入容量和 12、10、6 KiB 部分和容量。IA=4 时余下三个 PS bank，可用于单个 K tile 的任务或使用 S24 存储上限的任务；RAW32 跨 K 的任务从 IA=1、2 中选择。八个或九个 bank 的构建在 IA=4 时仍保留至少四个 PS bank。

FPGA 默认七个 8 KiB bank 中，IA=1、2、4 分别提供 8、16、32 KiB 输入容量和 48、40、24 KiB 部分和容量。紧凑 S8 的 IA 容量上限对应 R=16、32、64；S16 在 IA=2、4 时对应 R=16、32。具体任务还需要满足 PS 目录、frame 数和每个 PS bank 的容量限制。

完整容量统计还包括为整个 IA 行组保留的输出空间。默认 16 个 PS frame 下，2、4 KiB bank 使用 32 个 S8 输出 tile bank，共 8 KiB；8 KiB bank 使用 64 个 S8 输出 tile bank，共 16 KiB。S16 输出默认保留四个 tile bank。`output_banks_s8`、`output_banks_s16` 和 `oa_s8_fifo` 分别报告数量和位数，展开检查将其与设备的 `MATRIX_OUTPUT_BANKS` 寄存器比较。

`IA_CACHE_BLOCKS` 影响输出队列等构建参数，`PS_FRAME_COUNT` 决定 frame 数上限。`PS_POOL_BYTES` 用于独立部分和存储配置。共享数据 RAM 的容量由 `SHARED_BANK_BYTES` 和 `SHARED_BANK_COUNT` 决定，运行时按任务分配 IA 和 PS bank。

## 查询与校验

```bash
make capacity-show
make capacity-show NPU_CONFIG=config/npu_fpga.mk
make capacity-check
make capacity-test

python3 test/capacity/check_elaboration.py \
  --config config/npu.mk \
  --verilator /path/to/verilator \
  --output-root build/capacity/elaboration

NPU_CONFIG=config/npu_fpga.mk python3 test/capacity/check_elaboration.py \
  --verilator /path/to/verilator \
  --output-root build/capacity/fpga_elaboration
```

展开测试统计一个 `npu_axil_top` 的全部顺序逻辑声明，检查缓冲数组与模型逐项相等，并核对单个计算阵列、VCE PE 数和共享 bank 数。JSON 包含源码摘要、有效参数、各模块位数、共享 SRAM 映射和寄存器能力。源码或参数改变后，应重新生成统计。

容量分为两个范围：

| 范围 | 包含内容 |
|---|---|
| `buffer-ram` | IA/PS 数据、目录、缓存标签、bias/量化缓存、输出缓冲、Conv/VCE 数据、请求和响应队列 |
| `logical-state` | 当前 RTL 展开后全部顺序逻辑状态，包括上述数组、PE、流水线、控制寄存器和时钟门控状态 |

`buffer-ram` 统计逻辑位数。报告的 `physical_shared_memory` 单独给出共享 RAM 的物理实例数、数据容量、未使用数据容量和 FPGA parity 容量。`logical-state` 统计存储位数，未包含组合逻辑面积。SoC 主存、PicoRV32 和固件存储均在此 NPU 统计范围之外。完整状态预算要求运行匹配当前源码的 RTL 展开。

当前逐行权重选择实现的默认配置展开结果如下。每种配置分别检查 RAW32 与 adaptive，缓冲数组逐项相等，总顺序逻辑状态也相等。

| 配置 | 共享数据 RAM | RAW32 总状态 | adaptive 总状态 |
|---|---:|---:|---:|
| AXI64，2 KiB × 7 | 14 KiB | 442,019 位 | 442,019 位 |
| AXI64，8 KiB × 7 | 56 KiB | 998,206 位 | 998,206 位 |

SIZE=16 的阵列使用 16 位 `row_weight_select`，每个物理行保存一个权重选择位。PE 的两组权重寄存器、IA/PS RAM、目录和输出 FIFO 按各自的实际存储容量统计。单 K tile 直接输出调度在已有 FIFO 内额外预留两个输出 tile bank；可用空间不足时采用按完成状态启动下一组的调度。

共享 RAM 的 ASIC 分支使用 `smic40_sram_1r1w`。2、4、8 KiB bank 分别使用 8、16、32 个 `RAMTP128X16` 宏，每个宏提供 128×16 位数据。七个 bank 分别需要 56、112、224 个宏，物理数据容量与逻辑容量相等。FPGA 的七个 8 KiB bank 使用 14 个 `RAMB36E1`，提供 56 KiB 数据和独立的 7 KiB parity。PS 目录和其他存储单独列出。

## 自动配置硬件

```bash
make menuconfig
make capacity-solve MAX_RAM_KIB=64
make capacity-check
```

菜单使用 Python 标准库 `curses`：方向键选择，回车编辑，`O` 求解，`P` 查看各工作负载的 bank 分配与调度结果，`S` 保存，`Q` 退出。修改保存后再执行构建命令，使 Make 重新读取配置。

```bash
python3 scripts/capacity/solve.py --config config/npu.mk \
  --max-state-kib 64 --measure-state --verilator /path/to/verilator \
  --shape 128,256,64 --output build/capacity/solution.json
```

命令未指定 `--apply` 时只导出结果。`--apply` 才会更新配置。可以用 `NPU_CONFIG` 选择另一份配置文件；修改前会校验预算和参数，外部修改过的文件不会被菜单直接覆盖。

求解器保持所选 bank 大小、输出缓冲参数和 frame 数不变，枚举六至九个物理 bank。在每个候选硬件下调用与驱动共用的 C 调度函数，评估外部操作数读取及命令开销，并为各任务选择 IA/PS bank 分配。JSON 的 `runtime_bank_allocations` 给出可选物理划分，`plans` 给出每个工作负载的调度结果。默认任务集合为 [`config/capacity_workloads.json`](../config/capacity_workloads.json)。自定义形状采用标准矩阵维度 `A[M,K] × B[K,N]`：

```bash
make capacity-solve MAX_RAM_KIB=64 SHAPES='128,256,64 512,128,128'
make capacity-solve MAX_RAM_KIB=64 REPRESENTATION=raw32
```

容量求解结果用于硬件选择及软件规划；实际推理周期由 RTL 仿真测量。模型估计不会替代逐层及完整网络的周期比较。

## 每层选择 R、W 和数据流

软件读取运行时能力，以同一物理容量枚举合法 IA bank 分配、WS/IS、R/W 和 frame 高度。IA 流式操作数的格式决定可用 R：紧凑 S8 每 tile 占 256 字节，完整 S16 占 512 字节；双缓冲分别需要 `512R` 和 `1024R` 字节。WS 的流式操作数为激活，IS 为 S8 权重，两种方向分别计算 R 上限。

中间 PS 的存储上限按每个 bank 计算。对于一个 frame 的 L 个有效行，RAW32 需要 4L 个 128 位字，严格 S24 界需要至多 3L 个字，严格 S16 界需要至多 2L 个字。每个有效 frame 的字数按 PS bank 数向上取整，分别计入各 bank 的使用量。还必须满足共享目录总行数和 frame 数限制。K 只有一个 tile 时无需保留中间 PS。

Prepare 使用 [`dsa_ps_bound_s8`](../drivers/dsa_ps_bound.h) 读取固定权重，根据输入类型、offset 和最大的非最终 K 前缀，计算所有合法 S8 输入的中间累加范围。该计算不读取运行时激活。满足有符号 16 位或 24 位范围时，分别通过 `PS_CONTROL[5:4]` 保存 S16 或 S24 上限；硬件接收每个编码记录时检查其长度。这里的 S16/S24 指部分和值的范围。bias 在最终 K 后加入，不参与中间部分和上限。范围较宽时按 RAW32 长度保留空间。

实际行编码还可选择重复行、差分 Rice 和独立的 Sparse128。Sparse128 使用一个 128 位字保存非零 lane 掩码、元素字宽和非零值；容量规划仍采用已经证明的最坏长度。遇到存储压力时，受保护 frame 的优先完成机制继续执行并释放部分和空间。

`adaptive` 模式允许无损压缩和 RAW32，驱动选择使预计任务周期较小的参数。`raw32` 模式强制原始 INT32 存储，但仍使用相同的共享 RAM、IA 紧凑格式及硬件队列。两者比较时应使用同一个 RTL 二进制，在 Prepare 前切换运行时策略，并分别记录 Prepare、Invoke、Conv、Dense 与 VCE 周期。

## 验证入口

```bash
make ps-stream-verify VERILATOR=/path/to/verilator
make shared-memory-test VERILATOR=/path/to/verilator
python3 test/capacity/run_raw_only_capability.py \
  --verilator /path/to/verilator --out build/capacity/raw_only
python3 test/performance_analysis/validate_configuration_bounds.py \
  --verilator /path/to/verilator --out build/capacity/configuration_bounds
```

覆盖行编解码、frame 更新、容量压力调度、共享 RAM 同周期访问、IA 格式、寄存器访问、RAW-only 编译能力和 NPU 数值结果。完整模型测试使用 [`test/model_benchmark`](../test/model_benchmark/README.md)，保留硬件 im2col、DW、池化、Softmax 和准备好的矩阵描述符。
