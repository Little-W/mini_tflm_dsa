# TFLM AI DSA

TFLM AI DSA 是面向 TensorFlow Lite Micro 和 NMSIS-NN 推理的矩阵运算加速器项目。仓库提供 NPU 的 SystemVerilog RTL、PicoRV32 SoC 集成、驱动、模型部署工具以及仿真和 FPGA 工程。

NPU 通过 32 位数据、16 位地址的 AXI-Lite 接收任务配置，通过可选 32 或 64 位数据宽度的 AXI4 访问存储器，执行分块矩阵乘、累加、量化和结果写回。它执行全连接、硬件 im2col 卷积，以及由共享 VCE 处理的 DW、池化、Add 和 Softmax。

## 主要特性

- DiP 二维脉动阵列逐周期接收完整输入行，输入在 PE 之间对角传递，驻留权重按列旋转，部分和按完整行读写。
- 支持 Weight Stationary（WS）和 Input Stationary（IS）数据流，AUTO 根据设备容量、物理 AXI 数据拍和调度费用选择方案。
- 统一数据通路支持 INT8、INT16 输入、硬件 Conv，以及逐张量和逐通道量化。
- 集成 VCE，默认 8 PE，支持 4 PE；DW、池化、量化 Add 和 Softmax 共享计算及输入读取资源。
- 在统一计算路径内提供无损 PS 压缩、逐 frame 的 K 进度，以及容量不足时优先完成驻留输出的调度。
- IA 与 PS 共享 6 至 9 个 bank，每个 bank 可选 2、4 或 8 KiB；S8 输入在 IA RAM 中紧凑存储。通用及 ASIC 配置默认 14 KiB，FPGA 配置默认 56 KiB。
- 模型初始化时为每层计算 IA/PS 分配、R/W 和 WS/IS，将配置保存到 tensor arena；Invoke 通过 NMSIS 配置指针执行。
- 提供容量求解器和 RTL 状态统计，支持在同一硬件配置下比较 RAW32 与压缩模式。
- 提供 AXI-Lite 寄存器接口、C 驱动、TFLM 和 NMSIS-NN 集成。
- 提供模块级、NPU 顶层和 SoC 仿真，以及 FPGA 和 ASIC 综合入口。

## 系统结构

CPU 通过 AXI-Lite 提交配置。NPU 的 DMA 从主存读取输入和权重，IA/kernel loader 为阵列提供分块数据。中间部分和存入 IA/PS 共享 RAM，最终结果经过量化和 AXI 写回。独立的 VCE 复用 DMA 及可配置容量的窗口缓存，窗口缓存默认使用 4 KiB 数据 RAM。

NPU 顶层位于 [`rtl/npu/top/npu_top.sv`](rtl/npu/top/npu_top.sv)，SoC 顶层位于 [`rtl/soc_top.sv`](rtl/soc_top.sv)。数据通路和配置参数见[硬件架构](docs/architecture.md)，寄存器定义见[寄存器说明](drivers/registers_v2.md)。

## 快速开始

### 获取源码

```bash
git clone --recurse-submodules https://github.com/Little-W/mini_tflm_dsa.git tflm_ai_dsa
cd tflm_ai_dsa
```

已有工作目录可执行 `git submodule update --init --recursive`，获取 PicoRV32 子模块。

### 运行模块仿真

模块仿真需要 Linux、GNU Make、Python 3 和 Synopsys VCS。在仓库根目录执行：

```bash
make help
make vcs-unit-axi_dual_block_dma
```

运行全部模块及 NPU 顶层测试：

```bash
make vcs-unit
```

构建产物和日志位于 `build/vcs/unit/`。其他仿真入口见[仿真与 FPGA](docs/verification.md)。

### 向量计算引擎与完整模型测试

Vector Compute Engine（VCE）支持 INT8 DW、平均/最大/最小池化、量化 Add，
以及 INT8/INT16 的求和、极值、点积和 Hadamard 积。默认使用 8 个共享 PE。
DW 与小窗口池化复用输入行，全局池化采用批量线性读取。池化窗口最多包含 256 个位置，
覆盖 25×5 和 8×8 平均池化。量化与平均值计算使用最近偶数舍入。

`NPU_AXI_DATA_WIDTH` 选择 AXI4 数据宽度，支持 32 和 64 位，默认 64 位。AXI-Lite 寄存器接口保持 32 位数据和 16 位地址。`PCR_ENGINE=1` 在统一核心中启用 PS 压缩，并提供硬件 Conv 和 VCE。

```bash
make vector-engine-test VERILATOR=/path/to/verilator VECTOR_PE_COUNT=8
make vector-engine-soc VERILATOR=/path/to/verilator \
  MODEL_BENCHMARK_GCC=/path/to/riscv-none-elf-gcc \
  MODEL_BENCHMARK_PREPARED=/path/to/prepared
```

结构、数值规则和寄存器见 [VCE 设计说明](docs/vector_engine.md)。
CNN、MobileNetV1、DS-CNN、ResNet-8 的测试方法见
[完整模型测试说明](test/model_benchmark/README.md)。

### 配置共享 IA/PS 存储与 im2col 缓存

可以在终端菜单中编辑硬件参数、查看容量占用并调用求解器：

```bash
make menuconfig
```

方向键选择参数，回车编辑；`O` 自动求解、`S` 保存、`Q` 退出。界面使用 Python 标准库 `curses`。也可以直接通过命令行求解：

```bash
make capacity-solve MAX_RAM_KIB=64
make capacity-show
make vcs-top
```

通用及 ASIC 参数保存在 [`config/npu.mk`](config/npu.mk)。FPGA 工程默认读取 [`config/npu_fpga.mk`](config/npu_fpga.mk)，也可通过 `NPU_CONFIG` 显式选择配置文件：

| 参数 | 可选值 | 通用及 ASIC 默认值 | FPGA 默认值 |
|---|---|---:|---:|
| `NPU_AXI_DATA_WIDTH` | 32、64 位 | 64 | 64 |
| `IM2COL_CACHE_BYTES` | 512～65536 字节，二次幂 | 4096 | 4096 |
| `SHARED_BANK_BYTES` | 2048、4096、8192 字节 | 2048 | 8192 |
| `SHARED_BANK_COUNT` | 6、7、8、9 | 7 | 7 |

共享数据 RAM 的总容量为 `SHARED_BANK_BYTES × SHARED_BANK_COUNT`。通用及 ASIC 默认使用七个 2 KiB bank，共 14 KiB；FPGA 默认使用七个 8 KiB bank，共 56 KiB。FPGA 工程要求 8 KiB bank，每个 bank 使用两个 `RAMB36E1` 的完整数据容量。ASIC 使用完整的 `RAMTP128X16` 宏组合形成 bank。内部存储接口为 128 位，外部 AXI 位宽独立配置。数据容量和 parity 位的统计见[共享 RAM 物理映射](docs/shared_ram_mapping.md)。

Prepare 为每层选择 1、2 或 4 个 IA bank，其余用于 PS。Invoke 提交保存的分配，任务执行期间保持固定。以完整 S16 行存入 IA RAM 时至少需要两个 IA bank；跨 K 保存 RAW32 部分和至少需要四个 PS bank；经范围检查保证的 S24、S16 上限分别需要至少三个、两个 PS bank。

```bash
make capacity-show NPU_CONFIG=config/npu.mk
make capacity-show NPU_CONFIG=config/npu_fpga.mk
```

容量求解器统计数据数组、目录、缓存标签及队列；`MAX_STATE_KIB` 还要求通过 Verilator 展开统计完整顺序逻辑状态。求解与构建分两次 Make 调用。配置范围、任务集合和验证入口见[容量说明](docs/capacity.md)。

`IM2COL_CACHE_BYTES` 设置 im2col 原始输入缓存的数据容量，标签和使用状态另计；它与 IA/PS 共享 RAM 分别配置。缓存固定使用两路、16 字节缓存行，组数为 `IM2COL_CACHE_BYTES / 32`。在 16 字节对齐、通道数为 16 的整数倍的 NHWC 输入下，4 KiB 可容纳一个 K16 通道片段的三行输入带，宽度上限为 S8 的 85 像素或 S16 的 42 像素。`menuconfig` 帮助和 `capacity-show` 显示对应容量的卷积尺寸提示。完整公式、常用尺寸和仿真结果见 [im2col 缓存容量配置](docs/im2col_cache_configuration.md)。

```bash
make capacity-show IM2COL_CACHE_BYTES=8192
make capacity-check IM2COL_CACHE_BYTES=8192
```

```bash
make ps-stream-verify VERILATOR=/path/to/verilator
make shared-memory-test VERILATOR=/path/to/verilator
```

同容量 RAW32 与压缩模式的完整模型测试、周期定义及输出检查见
[共享 IA/PS 测量方法](docs/shared_ia_ps_performance.md)。

### 按层准备与执行

`AllocateTensors()` 在模型初始化时调用各算子的 Prepare。`InitializeLayerConfig` 为 Conv、Dense、DW、池化、Add 和 Softmax 分配持久化 arena 配置，算子的 `OpData` 保存其指针。矩阵层在这一阶段完成设备能力查询、静态权重打包、部分和范围分析及联合调度搜索。

Invoke 使用准备好的配置和本次激活地址。矩阵与空间算子调用 `riscv_nn_execute_prepared_s8`，Add 和 Softmax 使用各自的配置指针入口。驱动读取张量地址、检查范围并提交保存的寄存器值；调度搜索和权重打包在 Prepare 完成。重复推理的配置、只读权重、arena 用量及规划计数检查见[Prepare 生命周期测试](test/prepared_lifecycle/README.md)。

`dsa_set_ps_force_raw()` 在 `AllocateTensors()` 前选择 RAW32 或压缩策略。已经准备的层配置保存其策略；更换策略、模型形状或设备容量后重新执行 Prepare。具体公式、接口和缓存条件见[矩阵调度与窗口缓存](docs/scheduling_and_window_cache.md)。

### 选择模型并运行 SoC 仿真

SoC 固件构建需要 RISC-V 裸机交叉编译工具链；TFLM 仿真还需要 VCS、UVM 和 NumPy。

```bash
make model-list
make model-select MODEL=mnist_mlp_int16x8
make model-build
make vcs-tflm
```

不指定 `MODEL` 时，`make model-select` 显示模型选择菜单。部署模型位于 [`drivers/tflm/models/`](drivers/tflm/models/)，模型配置和 NMSIS 说明见 [TFLM 文档](drivers/tflm/README.md)。

## 仿真与实现

| 入口 | 用途 |
|---|---|
| `make vcs-top` | 运行 NPU 顶层矩阵运算仿真 |
| `make vcs-axil` | 运行 AXI-Lite 接口的 UVM 仿真 |
| `make vcs-soc` | 运行 PicoRV32 SoC 仿真 |
| `make vcs-nmsis-abi` | 运行 NMSIS 驱动接口仿真 |
| `make vcs-pcr-soc` | 运行统一计算路径及 PS 压缩的 SoC 仿真 |
| `make menuconfig` | 在终端菜单中编辑硬件配置、查看容量并自动求解 |
| `make capacity-solve MAX_RAM_KIB=<n>` | 求解共享计算路径的存储容量并更新配置 |
| `make capacity-test` | 验证求解器、配置传递和软件分块 |
| `make pcr-backend` | 用当前统一硬件配置编译 Verilator 后端 |
| `make dip-array-test` | 验证 DiP 传播、权重旋转及完整行输入 |
| `make -C asic sram-test` | 使用 SRAM 宏功能模型测试存储器封装 |
| `make -C asic syn` | 使用 Design Compiler 综合 NPU |

VCS、SoC、FPGA 和 ASIC 构建使用 `NPU_AXI_DATA_WIDTH`、`IM2COL_CACHE_BYTES`、`SHARED_BANK_BYTES` 与 `SHARED_BANK_COUNT`，并按目标选择配置文件。阵列及调度参数包括 `SIZE`、`IA_CACHE_BLOCKS` 和 `PS_FRAME_COUNT`。`PCR_ENGINE=1` 启用统一路径中的 PS 压缩及 frame 调度。软件在 Prepare 查询能力寄存器并选择合法参数，详细规则见[硬件架构](docs/architecture.md)。

FPGA 工程使用 AMD Vivado，入口和参数见 [FPGA 工程说明](fpga/vivado/tflm_ai_dsa_soc/README.md)。ASIC 流程需要 Synopsys 工具和使用者提供的工艺库，配置方法见 [ASIC 综合环境](asic/README.md)。Python 周期仿真接口见 [Python 模型说明](veri/python_model/README.md)。

## 仓库结构

| 路径 | 内容 |
|---|---|
| [`rtl/`](rtl/) | NPU、AXI 接口和 SoC RTL |
| [`config/`](config/) | 统一硬件参数与容量求解任务集合 |
| [`drivers/`](drivers/) | 加速器驱动、TFLM、NMSIS 和部署模型 |
| [`test/`](test/) | 模块级和 NPU 顶层测试平台 |
| [`veri/`](veri/) | UVM 环境、SoC 测试程序和 Python 仿真接口 |
| [`fpga/`](fpga/) | Vivado 工程、约束和脚本 |
| [`asic/`](asic/) | ASIC 综合脚本和 SRAM 宏封装 |
| [`picorv32/`](picorv32/) | PicoRV32 上游 Git 子模块 |
| [`scripts/`](scripts/) | 模型、仿真和工程辅助工具 |
| [`docs/`](docs/) | 架构、软件和验证文档 |

## 文档

- [文档中心](docs/README.md)
- [快速开始](docs/getting-started.md)
- [硬件架构](docs/architecture.md)
- [容量求解器](docs/capacity.md)
- [im2col 缓存容量配置](docs/im2col_cache_configuration.md)
- [共享 IA/PS 测量方法](docs/shared_ia_ps_performance.md)
- [软件与模型](docs/software.md)
- [仿真与 FPGA](docs/verification.md)
- [NPU 寄存器](drivers/registers_v2.md)

## 许可证

仓库包含的第三方源码遵循各自目录中的许可证。
