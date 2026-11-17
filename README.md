# TFLM AI DSA

TFLM AI DSA 是面向 TensorFlow Lite Micro 和 NMSIS-NN 推理的矩阵运算加速器项目。仓库提供 NPU 的 SystemVerilog RTL、PicoRV32 SoC 集成、驱动、模型部署工具以及仿真和 FPGA 工程。

NPU 通过 32 位数据、16 位地址的 AXI-Lite 接收任务配置，通过可选 32 或 64 位数据宽度的 AXI4 访问存储器，执行分块矩阵乘、累加、量化和结果写回。它执行全连接、硬件 im2col 卷积，以及由共享 VCE 处理的 DW、池化、Add 和 Softmax。

## 主要特性

- DiP 二维脉动阵列使用对角输入传递和旋转权重，支持完整行输入及部分和读写。
- 支持 Weight Stationary（WS）和 Input Stationary（IS）数据流，可通过寄存器切换。
- 统一数据通路支持 INT8、INT16 输入、硬件 Conv，以及逐张量和逐通道量化。
- 集成 VCE，默认 8 PE，支持 4 PE；DW、池化、量化 Add 和 Softmax 共享计算及输入读取资源。
- 在统一计算路径内提供无损 PS 压缩、逐 frame 的 K 进度，以及容量不足时优先完成驻留输出的调度。
- IA 与 PS 共享 6 至 9 个 bank，每个 bank 可选 1、2 或 4 KiB；软件按层选择分配、R/W 和 WS/IS，S8 输入在 IA RAM 中紧凑存储。
- 提供容量求解器和 RTL 状态统计，支持在同一个硬件程序中比较 RAW32 与压缩模式。
- 提供 AXI-Lite 寄存器接口、C 驱动、TFLM 和 NMSIS-NN 集成。
- 提供模块级、NPU 顶层和 SoC 仿真，以及 FPGA 和 ASIC 综合入口。

## 系统结构

CPU 通过 AXI-Lite 提交配置。NPU 的 DMA 从主存读取输入和权重，IA/kernel loader 为阵列提供分块数据。中间部分和存入 IA/PS 共享 RAM，最终结果经过量化和 AXI 写回。独立的 VCE 复用 DMA 及 4 KiB 窗口缓存。

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

### 配置共享 IA/PS 存储

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

硬件参数保存在 `config/npu.mk`，也可用 `NPU_CONFIG` 选择另一份文件：

| 参数 | 可选值 | 默认值 |
|---|---|---:|
| `NPU_AXI_DATA_WIDTH` | 32、64 位 | 64 |
| `SHARED_BANK_BYTES` | 1024、2048、4096 字节 | 2048 |
| `SHARED_BANK_COUNT` | 6、7、8、9 | 7 |

共享数据 RAM 的总容量为 `SHARED_BANK_BYTES × SHARED_BANK_COUNT`，默认 14 KiB。软件在任务开始前分配 1、2 或 4 个 bank 给 IA，其余用于 PS，执行期间分配保持固定。真实 S16 输入至少需要两个 IA bank；跨 K 保存 RAW32 部分和至少需要四个 PS bank；采用经范围检查保证的 S24 容量上限时至少需要三个 PS bank。

容量求解器统计数据数组、目录、缓存标签及队列；`MAX_STATE_KIB` 还要求通过 Verilator 展开统计完整顺序逻辑状态。求解与构建分两次 Make 调用。配置范围、任务集合和验证入口见[容量说明](docs/capacity.md)。

```bash
make ps-stream-verify VERILATOR=/path/to/verilator
make shared-memory-test VERILATOR=/path/to/verilator
```

同容量 RAW32 与压缩模式的完整模型测试、周期定义及输出检查见
[共享 IA/PS 测量方法](docs/shared_ia_ps_performance.md)。

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
| `make -C asic sram-test` | 使用 SRAM 宏功能模型测试存储器封装 |
| `make -C asic syn` | 使用 Design Compiler 综合 NPU |

VCS、SoC、FPGA 和 ASIC 构建共用 `NPU_AXI_DATA_WIDTH`、`SHARED_BANK_BYTES` 与 `SHARED_BANK_COUNT`。阵列及调度参数包括 `SIZE`、`IA_CACHE_BLOCKS` 和 `PS_FRAME_COUNT`。`PCR_ENGINE=1` 启用统一路径中的 PS 压缩及 frame 调度。软件查询能力寄存器后选择合法参数，详细规则见[硬件架构](docs/architecture.md)。

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
- [共享 IA/PS 测量方法](docs/shared_ia_ps_performance.md)
- [软件与模型](docs/software.md)
- [仿真与 FPGA](docs/verification.md)
- [NPU 寄存器](drivers/registers_v2.md)

## 许可证

仓库包含的第三方源码遵循各自目录中的许可证。
