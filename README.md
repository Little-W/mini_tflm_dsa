# TFLM AI DSA

面向 TensorFlow Lite Micro / NMSIS-NN 端侧推理的自定义神经网络加速器工程。仓库主体是一套 SystemVerilog NPU RTL，围绕矩阵乘、全连接和卷积 im2col 后端构建，配套提供 AXI-Lite/MMIO 驱动、VCS/UVM 验证环境、FPGA SoC wrapper 与设计/验证/性能文档。

当前 NPU 的目标是在 RISC-V SoC 中由软件通过 MMIO 配置任务，由硬件自主完成输入加载、权重加载、偏置读取、分块矩阵乘累加、重量化、s8 写回和完成状态上报，从而加速 TFLM 推理中的密集线性代数路径。

## 目录

- [项目特性](#项目特性)
- [仓库结构](#仓库结构)
- [硬件架构](#硬件架构)
- [软件接口](#软件接口)
- [环境依赖](#环境依赖)
- [快速开始](#快速开始)
- [仿真与验证](#仿真与验证)
- [FPGA SoC 目录](#fpga-soc-目录)
- [关键参数](#关键参数)
- [文档索引](#文档索引)
- [开发建议](#开发建议)
- [常见问题](#常见问题)

获取源码后，运行 `git submodule update --init --recursive` 初始化 PicoRV32。新建工作目录可使用 `git clone --recurse-submodules <repository-url>`。

## 项目特性

- 参数化 `SIZE x SIZE` 脉动阵列，测试中覆盖 `SIZE=4/8/16/32` 等组合。
- 同时支持 Weight Stationary (WS) 和 Input Stationary (IS) 数据流，可通过配置寄存器切换。
- 支持 int8 与 int16 输入路径。
- 支持 per-tensor 与 per-channel 重量化，输出侧包含激活范围裁剪。
- IA cache、W reuse、PS buffer 和 output FIFO 共同支持分块复用。
- 统一 `axi_dual_block_dma` 与 `axi_block_dma_arbiter` 负责 loader/writer 的 AXI4 读写访问。
- 标准 AXI-Lite MMIO 寄存器接口，软件侧提供 `drivers/dsa_accel.c/.h` 封装。
- VCS 分层测试覆盖 DMA、PS buffer、compute core、NPU 顶层、AXI-Lite 和 SoC。
- 文档目录包含架构设计、模块设计、RTL 验证、性能分析和项目方案材料。

## 仓库结构

```text
tflm_ai_dsa/
  asic/                            # ASIC 综合、工艺 SRAM 封装与测试
  rtl/
    common/                         # 通用 RAM/基础单元
    npu/
      top/                          # npu_top 顶层
      control/                      # 控制器与任务调度
      dma/                          # AXI block DMA 与 client 仲裁
      loaders/                      # IA、kernel、bias loader 与 IA cache
      compute/                      # 脉动阵列、累加、de-diagonalizer
      buffers/                      # partial-sum buffer / FIFO
      writeback/                    # requant、s8 打包、OA writer
    axi_top/                        # AXI-Lite 配置接口
    soc/                            # CPU 桥接、互连、RAM 和 UART
    soc_top.sv                      # SoC 顶层
  picorv32/                         # PicoRV32 上游 Git 子模块
  drivers/                          # 裸机 MMIO 驱动、TFLM 集成和寄存器文档
  test/                             # 模块级与 NPU 顶层测试平台
  veri/                             # UVM 环境、SoC 测试程序和仿真工具
  fpga/vivado/tflm_ai_dsa_soc/      # FPGA SoC wrapper、约束、仿真和工程脚本
  docs/                             # 项目文档
  paper/                            # 本地论文工作台，独立于 Git 管理
  deliverables/                     # FPGA 发布包和仿真交付资料
  scripts/                          # 辅助脚本
```

补充说明：

- `rtl/README.md` 记录 RTL 分层原则。
- `drivers/README.md` 记录 C 驱动用法。
- `drivers/tflm/README.md` 说明模型选择、NMSIS 源码与PCR 面板引擎的构建方法。
- `fpga/vivado/tflm_ai_dsa_soc/README.md` 记录 FPGA SoC 子目录的脚本入口和参数。
- `test/compute_core/README.md` 记录 compute core 测试平台的控制协议说明。

## 硬件架构

NPU 顶层为 `rtl/npu/top/npu_top.sv`，对外暴露控制配置端口和 AXI4 master 数据接口。SoC 集成时，外层 AXI-Lite shell 将 MMIO 寄存器映射为 `npu_top` 的配置端口，CPU 通过寄存器启动任务，NPU 经 AXI master 访问共享 RAM。

核心数据路径如下：

```text
AXI-Lite registers
        |
        v
 npu_controller
        |
        +--> ia_loader ----+
        +--> kernel_loader +--> compute_core --> ps_buffer
        +--> bias_loader --+                         |
        +--> quant loader ---------------------------+
                                                  vec_requant
                                                      |
                                                vec_s8_to_fifo
                                                      |
                                                   oa_writer
                                                      |
                                                AXI4 writeback
```

主要模块职责：

| 模块 | 文件 | 作用 |
|---|---|---|
| `npu_top` | `rtl/npu/top/npu_top.sv` | 参数裁剪、模块互连、共享 DMA client 汇聚 |
| `npu_controller` | `rtl/npu/control/npu_controller.sv` | 校验配置、发出 loader/compute 触发、管理完成握手 |
| `ia_loader` | `rtl/npu/loaders/ia_loader*.sv` | IA tile 加载、IA cache 管理、连续对角化输出 |
| `kernel_loader` | `rtl/npu/loaders/kernel_loader*.sv` | RHS/W tile 加载、列展平权重缓存与阵列写权重 |
| `bias_loader` | `rtl/npu/loaders/bias_loader*.sv` | s32 bias 读取和分组输出 |
| `compute_core` | `rtl/npu/compute/compute_core.sv` | WS 脉动阵列、partial sum、bias mux、最终输出 |
| `ps_buffer` | `rtl/npu/buffers/ps_buffer.sv` | partial sum 存储、回灌和 de-diagonalize 输出 |
| `vec_requant` | `rtl/npu/writeback/vec_requant.sv` | int32 累加结果重量化、激活裁剪 |
| `vec_s8_to_fifo` | `rtl/npu/writeback/vec_s8_to_fifo.sv` | s8 向量打包为 32-bit 写回数据和 byte mask |
| `oa_writer` | `rtl/npu/writeback/oa_writer.sv` | 输出 tile 地址展开与 AXI 写回 |
| `axi_dual_block_dma` | `rtl/npu/dma/axi_dual_block_dma.sv` | 统一 AXI4 读写 DMA，支持 outstanding 与非对齐访问 |

### 数据流与复用

硬件按 `SIZE x SIZE` tile 执行分块矩阵乘。`NPU_REG_DATAFLOW` 选择 WS 或 IS 数据流，分别使用配置值 `0` 和 `1`。WS 模式下权重驻留在阵列中，IA 经过对角化流入阵列。IA cache 允许一个 IA group 在多个 W group 上复用，PS buffer 保存中间 partial sum 并支持后续归约 tile 回灌。

驱动根据矩阵尺寸和缓存容量计算复用窗口与工作组参数，并写入配置寄存器。配置接口及外部预计算方法见 `drivers/registers_v2.md`。

## 软件接口

### MMIO 地址

NPU AXI-Lite 窗口基地址为：

```c
#define DSA_MMIO_BASE 0x10000000u
```

完整寄存器定义见 `drivers/registers_v2.md`。常用寄存器如下：

| Byte offset | 名称 | 用途 |
|---:|---|---|
| `0x000` | `NPU_REG_CTRL` | start、输入位宽、量化模式、dataflow 控制 |
| `0x004` | `NPU_REG_STATUS` | ready/busy/done/error 状态，done 写 1 清除 |
| `0x010` | `NPU_REG_LHS_BASE` | LHS/IA 基地址 |
| `0x014` | `NPU_REG_RHS_BASE` | RHS/W 基地址 |
| `0x018` | `NPU_REG_DST_BASE` | 输出基地址 |
| `0x01c` | `NPU_REG_BIAS_BASE` | bias 基地址，0 表示无 bias |
| `0x020` | `NPU_REG_K` | 输出行数 / LHS rows |
| `0x024` | `NPU_REG_N` | 内积长度 |
| `0x028` | `NPU_REG_M` | 输出列数 / RHS cols |
| `0x044` | `NPU_REG_Q_MULT` | per-tensor multiplier 或 per-channel multiplier 指针 |
| `0x048` | `NPU_REG_Q_SHIFT` | per-tensor shift 或 per-channel shift 指针 |
| `0x054` | `NPU_REG_IA_REUSE` | IA cache 复用深度 |
| `0x058` | `NPU_REG_W_REUSE` | W 侧复用窗口 |
| `0x05c` | `NPU_REG_DATAFLOW` | `0=WS`，`1=IS` |
| `0x060`–`0x06c` | 工作组配置 | 外部计算的行列工作组数量和尾组大小 |
| `0x070` | `NPU_REG_CONFIG_ABI` | 配置接口版本 |
| `0x0fc` | `NPU_REG_ID` | 固定 ID，`0x4e50_5531` |

### C 驱动

驱动文件：

- `drivers/dsa_accel.h`
- `drivers/dsa_accel.c`
- `drivers/test_main.c`

典型调用流程：

```c
#include "dsa_accel.h"

int8_t  A[128 * 256];
int8_t  B[256 * 64];
int8_t  C[128 * 64];
int32_t bias[64];

dsa_matmul_config_t cfg;
dsa_matmul_config_init(&cfg);

cfg.lhs_ptr = (uint32_t)(uintptr_t)A;
cfg.rhs_ptr = (uint32_t)(uintptr_t)B;
cfg.dst_ptr = (uint32_t)(uintptr_t)C;
cfg.bias_ptr = (uint32_t)(uintptr_t)bias;

cfg.K = 128;
cfg.N = 256;
cfg.M = 64;

cfg.lhs_row_stride = 256;
cfg.rhs_row_stride = 256;
cfg.dst_row_stride = 64;

cfg.lhs_offset = 128;
cfg.rhs_offset = 0;
cfg.dst_offset = 0;
cfg.dst_mult = 1234567;
cfg.dst_shift = 10;

uint32_t status = dsa_matmul_execute(&cfg);
```

per-channel 量化时，将 `cfg.quant_mode` 设置为 `DSA_QUANT_PER_CHANNEL`，并配置 `cfg.dst_mult_ptr` 与 `cfg.dst_shift_ptr` 指向长度为 `M` 的 int32 数组。

## 环境依赖

- Linux、GNU Make、Python 3 和 NumPy。
- Synopsys VCS 与 UVM 1.2；可通过 `VCS` 和 `SIM_LAUNCHER` 指定工具及运行方式。
- RISC-V 裸机工具链，用于 SoC 固件和 TFLM 构建。
- Vivado，用于 FPGA 工程导出和综合。
- Verilator 与 C++ 编译器，用于构建可由 Python 控制的周期级 RTL 模型。

## 快速开始

在仓库根目录执行：

```bash
make help
make vcs-unit
make vcs-axil
make vcs-soc
```

`vcs-unit` 运行 DMA、仲裁器、部分和缓存、计算核心和 NPU 顶层测试。`vcs-axil` 和 `vcs-soc` 分别运行 AXI-Lite 与 SoC 的 UVM 测试。编译及运行日志位于 `build/vcs/unit/` 和 `veri/sim/runs/`。

## 仿真与验证

| 命令 | 验证对象 |
|---|---|
| `make vcs-unit-axi_dual_block_dma` | AXI 读写 DMA |
| `make vcs-unit-axi_block_dma_arbiter` | DMA 请求仲裁 |
| `make vcs-unit-ps_buffer` | 部分和缓存及输出 |
| `make vcs-unit-compute_core` | 计算核心和结果检查 |
| `make vcs-top` | NPU 顶层与矩阵结果比较 |
| `make vcs-axil` | AXI-Lite 寄存器与 NPU UVM 测试 |
| `make vcs-soc` | PicoRV32、互连、NPU 和固件联合测试 |
| `make vcs-nmsis-abi` | NMSIS 驱动的寄存器配置与 INT16 输出 |
| `make vcs-tflm` | TFLM INT16 模型的 SoC 推理测试 |

测试输入与阵列参数可由命令行指定：

```bash
make vcs-random-npu COUNT=2 SEED=41000 \
  SIZE=4 IA_CACHE_BLOCKS=4 PS_FRAME_COUNT=8 \
  RANDOM_GEN_ARGS='--random --random_quant --lhs_dtype 1 --min_dim 1 --max_dim 12' \
  SIM_ARGS='+DDR_RAND_LAT=1 +DDR_CMD_MAX_LAT=3 +DDR_W_MAX_LAT=2 +DDR_RSP_MAX_LAT=8'
make vcs-random-compute COUNT=2 SEED=42
make vcs-param-npu SIZES='4 8 16' CACHE_BLOCKS_LIST='2 4 8' COUNT=2
make vcs-uvm DUT_MODE=axil CASE=ai_axil_reg_directed_test
```

顶层测试使用 `veri/top_regression/gen_mem.py` 生成输入、配置和参考结果。模块测试检查成功标记及进程退出状态；UVM 测试检查错误与致命错误计数。原有 `test/*/Makefile` 入口调用仓库根目录的 VCS 命令。

使用 `make -C test/npu_top wave` 或 `make -C test/compute_core wave` 可生成 VCD 波形，文件位于对应的 `build/vcs/unit/` 目录。

TFLM 应用可通过仓库根目录的 Makefile 运行：

```bash
make vcs-tflm TFLM_APP=mnist_mlp_int16x8 \
  SIZE=4 IA_CACHE_BLOCKS=4 PS_FRAME_COUNT=8
```

使用容器运行 VCS 时，`make vcs-uvm` 会将主机的 NumPy 安装复制到 `build/vcs/python_deps/`，供容器中的 Python 使用。Python 解释器需具有相同的主版本与次版本。可用 `+PYTHON_BIN=<路径>` 指定仿真内调用的 Python。

## FPGA SoC 目录

FPGA SoC 相关文件位于 `fpga/vivado/tflm_ai_dsa_soc/`。根 README 只说明目录用途，具体脚本参数以该目录下 README 和 Tcl 脚本为准。

```text
fpga/vivado/tflm_ai_dsa_soc/
  rtl/fpga_top.sv                         # FPGA wrapper
  rtl/clk_wiz_0_sim_stub.sv               # Clocking Wizard 仿真 stub
  constraints/tflm_ai_dsa_soc.xdc         # 板级约束
  sim/fpga_top_behav_smoke_tb.sv          # behavioral smoke testbench
  scripts/                                # 工程、仿真、导出和分析脚本
```

该目录中的 `scripts/sources.tcl` 枚举本仓库的 NPU、SoC 和 PicoRV32 源码及板级约束。

## 关键参数

### `npu_top` 参数

| 参数 | 说明 |
|---|---|
| `WEIGHT_WIDTH` | 权重数据宽度；s8 路径会符号扩展到内部计算宽度 |
| `DATA_WIDTH` | IA 数据宽度 |
| `SIZE` | 脉动阵列边长，也是基本 tile 边长 |
| `BUS_WIDTH` | AXI 数据总线宽度，当前常用 32 bit |
| `REG_WIDTH` | 配置寄存器宽度，当前 32 bit |
| `ADDR_WIDTH` | NPU 内部地址宽度 |
| `IA_CACHE_BLOCKS` | IA loader cache slot 数 |
| `PS_FRAME_COUNT` | partial sum / output FIFO 可保留的输出列 tile 数 |
| `AXI_READ_OUTSTANDING` | AXI 读通道可提前排队的 burst 数 |
| `AXI_WRITE_OUTSTANDING` | AXI 写通道可提前排队的 burst 数 |
| `ENABLE_IS_MODE` | 置 0 时裁剪 IS 相关路径 |
| `ENABLE_PER_CHANNEL` | 置 0 时裁剪 per-channel 量化路径 |
| `OA_FIFO_BANKS_MAX` | output FIFO 最大 bank 数 |

## 文档索引

请从 [文档中心](docs/README.md) 阅读项目文档：

- [快速开始](docs/getting-started.md)
- [硬件架构](docs/architecture.md)
- [软件与模型](docs/software.md)
- [仿真与 FPGA](docs/verification.md)
- [NPU 寄存器](drivers/registers_v2.md)
- [ASIC 综合环境](asic/README.md)

## 开发建议

- RTL 源文件按功能域放在 `rtl/npu/*`。
- 修改 ready/valid、AXI、DMA、FIFO、PS buffer 或 loader 控制后，应至少运行对应模块级 smoke 和 `test/npu_top` 随机 golden compare。
- 修改参数裁剪、`SIZE`、`IA_CACHE_BLOCKS`、`PS_FRAME_COUNT`、WS/IS 或 per-channel 相关路径后，应运行参数化回归。
- FPGA SoC 与仿真共用本仓库的 RTL 源码。
- 测试输出、波形、工具日志和工程生成目录体积较大，提交前应确认是否确实需要归档。

## 常见问题

### Vivado 脚本提示缺少 RTL 文件

执行 `git submodule update --init --recursive` 获取 PicoRV32，然后确认 `rtl/` 和 FPGA 约束文件完整，并从仓库根目录运行导出脚本。

### NPU 顶层随机仿真超时或输出不一致

先降低随机范围并关闭 trace 复现：

```bash
make vcs-random-npu \
  SIZE=4 IA_CACHE_BLOCKS=4 PS_FRAME_COUNT=8 \
  COUNT=1 SEED=<seed> \
  RANDOM_GEN_ARGS='--random --random_quant --lhs_dtype 1 --min_dim 1 --max_dim 12'
```

若数值不一致，优先检查 `compute_core`、`ps_buffer` 和 `vec_requant`；若发生死锁，优先检查 DMA、arbiter、RAM 随机响应延时和 FIFO full/empty 条件。

### per-channel 模式返回资源缺失

per-channel 模式下 `NPU_REG_Q_MULT` 和 `NPU_REG_Q_SHIFT` 被解释为数组指针，必须指向长度为 `M` 的有效 int32 参数数组。

## License

仓库包含的第三方源码遵循各自目录中的许可证。
