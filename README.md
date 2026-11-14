# TFLM AI DSA

TFLM AI DSA 是面向 TensorFlow Lite Micro 和 NMSIS-NN 推理的矩阵运算加速器项目。仓库提供 NPU 的 SystemVerilog RTL、PicoRV32 SoC 集成、驱动、模型部署工具以及仿真和 FPGA 工程。

NPU 通过 AXI-Lite 接收任务配置，通过 AXI 访问存储器，执行分块矩阵乘、累加、量化和结果写回。它可用于全连接运算，以及转换为矩阵乘的卷积运算。

## 主要特性

- 参数化二维脉动阵列，支持可配置的输入缓存和部分和存储。
- 支持 Weight Stationary（WS）和 Input Stationary（IS）数据流，可通过寄存器切换。
- 标准数据通路支持 INT8、INT16 输入，以及逐张量和逐通道量化。
- 提供 PCR 面板引擎，使用无损部分和压缩和可配置的页池管理片上存储。
- 提供 AXI-Lite 寄存器接口、C 驱动、TFLM 和 NMSIS-NN 集成。
- 提供模块级、NPU 顶层和 SoC 仿真，以及 FPGA 和 ASIC 综合入口。

## 系统结构

```text
                    AXI-Lite                  AXI
PicoRV32 / 软件  ──────────────>  NPU  ──────────────>  存储器
                                  │
              输入与权重缓存 → 脉动阵列 → 部分和存储
                                               │
                                         量化与结果写回
```

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
| `make vcs-pcr-soc` | 运行 PCR 面板引擎的 SoC 仿真 |
| `make -C asic sram-test` | 使用 SRAM 宏功能模型测试存储器封装 |
| `make -C asic syn` | 使用 Design Compiler 综合 NPU |

VCS 仿真参数包括 `SIZE`、`IA_CACHE_BLOCKS` 和 `PS_FRAME_COUNT`。`PCR_ENGINE=1` 选择 PCR 面板引擎；该配置的输入格式和尺寸要求见 [TFLM 文档](drivers/tflm/README.md)。

FPGA 工程使用 AMD Vivado，入口和参数见 [FPGA 工程说明](fpga/vivado/tflm_ai_dsa_soc/README.md)。ASIC 流程需要 Synopsys 工具和使用者提供的工艺库，配置方法见 [ASIC 综合环境](asic/README.md)。Python 周期仿真接口见 [Python 模型说明](veri/python_model/README.md)。

## 仓库结构

| 路径 | 内容 |
|---|---|
| [`rtl/`](rtl/) | NPU、AXI 接口和 SoC RTL |
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
- [软件与模型](docs/software.md)
- [仿真与 FPGA](docs/verification.md)
- [NPU 寄存器](drivers/registers_v2.md)

## 许可证

仓库包含的第三方源码遵循各自目录中的许可证。
