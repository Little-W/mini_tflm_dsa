# 共享 IA/PS 容量与软件分配

硬件配置保存在 [`config/npu.mk`](../config/npu.mk)。默认使用 16×16 阵列、8 个 VCE PE、4 KiB 共享窗口缓存，以及 14 KiB 的 IA/PS bank RAM。`scripts/capacity` 计算所有已声明缓冲数组及元数据，并可通过 Verilator 展开统计完整顺序逻辑状态。

## 物理容量与任务分配

默认参数为：

```make
PCR_ENGINE ?= 1
SIZE ?= 16
NPU_AXI_DATA_WIDTH ?= 64
SHARED_BANK_BYTES ?= 2048
SHARED_BANK_COUNT ?= 7
IA_CACHE_BLOCKS ?= 4
PS_FRAME_COUNT ?= 16
AXI_READ_OUTSTANDING ?= 4
PS_POOL_BYTES ?= 12288
PS_FORCE_RAW ?= 0
CAPACITY_REPRESENTATION ?= adaptive
```

`PCR_ENGINE=1` 启用统一计算路径中的 PS frame 存储和调度。共享数据 RAM 的物理容量为 `SHARED_BANK_BYTES × SHARED_BANK_COUNT`，默认值为 `2048 × 7 = 14336` 字节。两个参数在编译时确定；每层执行前的软件分配决定其中多少 bank 用于 IA 和 PS。

| `SHARED_BANK_BYTES` | 每 bank 的 128 位行数 | `SHARED_BANK_COUNT=6、7、8、9` 时的数据总容量 |
|---:|---:|---|
| 1024 | 64 | 6、7、8、9 KiB |
| 2048 | 128 | 12、14、16、18 KiB |
| 4096 | 256 | 24、28、32、36 KiB |

`NPU_AXI_DATA_WIDTH` 可选 32、64 位，默认 64 位，控制 NPU AXI4、SoC 数据互连及主存数据接口。NPU 的 AXI-Lite 配置接口使用固定 32 位数据和 16 位地址。共享 SRAM 内部接口始终为 128 位；AXI4 数据宽度与 bank 大小分别配置。

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

例如，默认七个 2 KiB bank 中，IA=1、2、4 分别提供 2、4、8 KiB 输入容量和 12、10、6 KiB 部分和容量。IA=4 时余下三个 PS bank，可用于单个 K tile 的任务或使用 S24 存储上限的任务；RAW32 跨 K 的任务从 IA=1、2 中选择。八个或九个 bank 的构建在 IA=4 时仍保留至少四个 PS bank。

`IA_CACHE_BLOCKS` 和 `PS_POOL_BYTES` 保留固定缓冲实现的配置作用。当前共享配置通过 `SHARED_BANK_BYTES` 和 `SHARED_BANK_COUNT` 确定数据 RAM 总量。配置检查在构建前拒绝范围之外的 bank 参数。

## 查询与校验

```bash
make capacity-show
make capacity-check
make capacity-test

python3 test/capacity/check_elaboration.py \
  --verilator /path/to/verilator \
  --output-root build/capacity/elaboration
```

展开测试统计一个 `npu_axil_top` 的全部顺序逻辑声明，检查缓冲数组与模型逐项相等，并核对单个计算阵列、VCE PE 数和共享 bank 数。JSON 包含源码摘要、有效参数、各模块位数、共享 SRAM 映射和寄存器能力。源码或参数改变后，应重新生成统计。

容量分为两个范围：

| 范围 | 包含内容 |
|---|---|
| `buffer-ram` | IA/PS 数据、目录、缓存标签、bias/量化缓存、输出缓冲、Conv/VCE 数据、请求和响应队列 |
| `logical-state` | 当前 RTL 展开后全部顺序逻辑状态，包括上述数组、PE、流水线、控制寄存器和时钟门控状态 |

`buffer-ram` 统计逻辑位数，不计算 FPGA BRAM 或 ASIC 宏的额外容量取整。`logical-state` 统计存储位数，未包含组合逻辑面积。SoC 主存、PicoRV32 和固件存储均在此 NPU 统计范围之外。完整状态预算要求运行匹配当前源码的 RTL 展开。

共享 RAM 的 ASIC 分支使用 `smic40_sram_1r1w`。默认每个 128 位 bank 由八个 `RAMTP128X16` 宏组成，七个 bank 共 56 个宏，映射后数据容量为 14336 字节。1 KiB bank 的 64 行会按宏的 128 行深度取整；4 KiB bank 使用两组 128 行宏。容量报告分别记录逻辑数据量与宏的物理容量，目录和其他存储单独列出。

## 自动配置硬件

```bash
make menuconfig
make capacity-solve MAX_RAM_KIB=64
make capacity-check
```

菜单使用 Python 标准库 `curses`：方向键选择，回车编辑，`O` 求解，`S` 保存，`Q` 退出。修改保存后再执行构建命令，使 Make 重新读取配置。

```bash
python3 scripts/capacity/solve.py --config config/npu.mk \
  --max-state-kib 64 --measure-state --verilator /path/to/verilator \
  --shape 128,256,64 --output build/capacity/solution.json
```

命令未指定 `--apply` 时只导出结果。`--apply` 才会更新配置。可以用 `NPU_CONFIG` 选择另一份配置文件；修改前会校验预算和参数，外部修改过的文件不会被菜单直接覆盖。

求解器在所选 bank 大小下枚举六至九个物理 bank，并搜索 IA cache 和 frame 数参数。在每个候选硬件下调用与驱动共用的 C 调度函数，评估外部操作数读取及命令开销。默认任务集合为 [`config/capacity_workloads.json`](../config/capacity_workloads.json)。自定义形状采用标准矩阵维度 `A[M,K] × B[K,N]`：

```bash
make capacity-solve MAX_RAM_KIB=64 SHAPES='128,256,64 512,128,128'
make capacity-solve MAX_RAM_KIB=64 REPRESENTATION=raw32
```

容量求解结果用于硬件选择及软件规划；实际推理周期由 RTL 仿真测量。模型估计不会替代逐层及完整网络的周期比较。

## 每层选择 R、W 和数据流

软件读取运行时能力，以同一物理容量枚举合法 IA bank 分配、WS/IS、R/W 和 frame 高度。输入格式决定可用 R：紧凑 S8 每 tile 占 256 字节，真实 S16 占 512 字节；双缓冲分别需要 `512R` 和 `1024R` 字节。

中间 PS 的存储上限按每个 bank 计算。对于一个 frame 的 L 个有效行，RAW32 需要 4L 个 128 位字；S24 需要至多 3L 个字。每个 live frame 的字数向 bank 数取上整，分别计入每个 bank 的使用量。还必须满足共享目录总行数和 frame 数限制。K 只有一个 tile 时无需保留中间 PS。

S24 的可用性由输入类型、offset 和最大非最终 K 前缀计算。bias 在最终 K 后加入。无法保证 S24 范围时使用 RAW32 上限；动态差分压缩仍可节省实际空间，容量不足时由受保护 frame 的优先完成机制继续执行。

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
