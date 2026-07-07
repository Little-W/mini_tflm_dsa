# TFLM AI DSA

面向 TensorFlow Lite Micro / NMSIS-NN 端侧推理的自定义神经网络加速器工程。仓库主体是一套 SystemVerilog NPU RTL，围绕矩阵乘、全连接和卷积 im2col 后端构建，配套提供 AXI-Lite/MMIO 驱动、Verilator 测试平台、FPGA SoC wrapper 与设计/验证/性能文档。

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
- [开发约定](#开发约定)
- [常见问题](#常见问题)

## 项目特性

- 参数化 `SIZE x SIZE` 脉动阵列，测试中覆盖 `SIZE=4/8/16/32` 等组合。
- Weight Stationary (WS) 数据流为主，RTL 回归中也覆盖 Input Stationary (IS) 子集。
- 支持 int8 与 int16 输入路径。
- 支持 per-tensor 与 per-channel 重量化，输出侧包含激活范围裁剪。
- IA cache、W reuse、PS buffer 和 output FIFO 共同支持分块复用。
- 统一 `axi_dual_block_dma` 与 `axi_block_dma_arbiter` 负责 loader/writer 的 AXI4 读写访问。
- 标准 AXI-Lite MMIO 寄存器接口，软件侧提供 `drivers/dsa_accel.c/.h` 封装。
- Verilator 分层测试覆盖 DMA、PS buffer、compute core 和 NPU top。
- 文档目录包含架构设计、模块设计、RTL 验证、性能分析和项目方案材料。

## 仓库结构

```text
tflm_ai_dsa/
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
  drivers/                          # 裸机 MMIO 驱动和寄存器文档
  test/                             # Verilator 模块级与 NPU 顶层 testbench
  fpga/vivado/tflm_ai_dsa_soc/      # FPGA SoC wrapper、约束、仿真和工程脚本
  docs/                             # 架构、验证、性能和项目文档
  scripts/                          # 辅助脚本
```

补充说明：

- `rtl/README.md` 记录 RTL 分层原则。
- `drivers/README.md` 记录 C 驱动用法。
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

硬件按 `SIZE x SIZE` tile 执行分块矩阵乘。WS 模式下权重驻留在阵列中，IA 经过对角化流入阵列。IA cache 允许一个 IA group 在多个 W group 上复用，PS buffer 保存中间 partial sum 并支持后续归约 tile 回灌。

软件可写入 `NPU_REG_IA_REUSE` 和 `NPU_REG_W_REUSE` 显式配置复用窗口；写 0 时驱动和 RTL 会按 `IA_CACHE_BLOCKS`、`PS_FRAME_COUNT` 和矩阵 tile 数裁剪。

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
| `0x004` | `NPU_REG_STATUS` | ready/busy/done/error 状态，done/writeback valid 写 1 清除 |
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

建议环境：

- Linux shell 环境。
- Verilator 5.x，用于模块级和 NPU 顶层仿真。
- Python 3，用于生成随机矩阵和 memory case。
- RISC-V 裸机工具链，用于驱动或 SoC firmware 编译。
- Vivado 相关脚本依赖外部 SoC shell 与 PicoRV32 源码；默认路径在子目录 README 中说明。

## 快速开始

### 1. 查看源码结构

```bash
cd /home/etc/FPGA/tflm_ai_dsa
find rtl/npu -maxdepth 2 -type f | sort
```

### 2. 运行一个 NPU 顶层随机仿真

```bash
make -C test/npu_top run_random \
  SIZE=4 IA_CACHE_BLOCKS=4 PS_FRAME_COUNT=8 \
  COUNT=2 SEED=41000 TRACE=0 \
  RANDOM_GEN_ARGS='--random --random_quant --lhs_dtype 1 --min_dim 1 --max_dim 12 --ps_frame_count 8' \
  SIM_ARGS='+DDR_RAND_LAT=1 +DDR_CMD_MAX_LAT=3 +DDR_W_MAX_LAT=2 +DDR_RSP_MAX_LAT=8'
```

通过时日志中应出现：

```text
[TB] PASS
[run_random] PASS=2 FAIL=0
```

### 3. 运行模块级 smoke

```bash
make -C test/axi_dual_block_dma run
make -C test/axi_block_dma_arbiter run
make -C test/ps_buffer run
make -C test/compute_core run_random COUNT=2 SEED=42
```

### 4. 运行参数扫描

```bash
make -C test/npu_top run_param_random \
  SIZES='4 8 16' CACHE_BLOCKS_LIST='2 4 8' \
  COUNT=4 TRACE=0
```

## 仿真与验证

`test/` 下保留了可直接运行的 Verilator testbench。

| 目录 | 入口 | 覆盖内容 |
|---|---|---|
| `test/axi_dual_block_dma` | `make -C test/axi_dual_block_dma run` | AXI 读写通道、burst、完成握手 |
| `test/axi_block_dma_arbiter` | `make -C test/axi_block_dma_arbiter run` | 多 client 仲裁和重叠请求 |
| `test/ps_buffer` | `make -C test/ps_buffer run` | partial sum replay、de-diagonalize、FIFO bypass |
| `test/compute_core` | `make -C test/compute_core run_random` | 脉动阵列输出、final row、`tile_calc_over` 检查 |
| `test/npu_top` | `make -C test/npu_top run_random` | 完整 loader/compute/requant/writeback 和 RAM golden compare |

NPU 顶层测试由 `test/npu_top/gen_mem.py` 生成：

- `out/init.mem`
- `out/golden.mem`
- `out/config.mem`

仿真时 RAM 模型加载 `init.mem`，NPU 完成后测试平台读取输出区域并与 `golden.mem` 比较。这条路径能直接覆盖 tail tile、byte mask、非对齐写回和 RAM 随机响应延时。

常用参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `SIZE` | 4 | 阵列边长 |
| `IA_CACHE_BLOCKS` | 4 | IA cache block 数 |
| `PS_FRAME_COUNT` | 8 | PS/output buffer 帧数 |
| `AXI_READ_OUTSTANDING` | 4 | AXI 读 outstanding 深度 |
| `COUNT` | 20 | 随机用例数量 |
| `SEED` | 1000 | 起始随机种子 |
| `TRACE` | 1 | 是否生成 Verilator trace |

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

该目录中的 `scripts/sources.tcl` 统一枚举 FPGA SoC 需要的 NPU RTL、外部 SoC shell 源码和约束文件。若外部 SoC shell 不在默认路径，需要设置：

```bash
export AIENGINE_ROOT=/path/to/aiEngine_integrated
```

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

建议优先阅读：

| 文档 | 内容 |
|---|---|
| `docs/npu_architecture_design_report_cn.md` | NPU 架构、模块树、分块数据流、IA cache、DMA、写回与量化 |
| `docs/rtl_verification_report_cn.md` | RTL 模块级、NPU 顶层、SoC、TFLM 和覆盖率验证报告 |
| `docs/performance_report_cn.md` | 新旧 MMA、IA cache 和 TFLM 性能对比 |
| `docs/size_cache_hw_sw_perf_report_cn.md` | SIZE/cache 对硬件与软件性能的影响 |
| `docs/DSA模块设计文档.md` | DSA 模块级设计说明 |
| `docs/DSA 设计目标.md` | DSA 目标说明 |
| `drivers/registers_v2.md` | NPU AXI-Lite 寄存器表 |
| `docs/面向TFLM的自定义神经网络加速指令集.md` | 自定义指令扩展草案 |
| `docs/项目设计方案.md` | 项目背景、系统设计和 AI 校准方案 |

## 开发约定

- RTL 源文件按功能域放在 `rtl/npu/*`。
- 修改 ready/valid、AXI、DMA、FIFO、PS buffer 或 loader 控制后，应至少运行对应模块级 smoke 和 `test/npu_top` 随机 golden compare。
- 修改参数裁剪、`SIZE`、`IA_CACHE_BLOCKS`、`PS_FRAME_COUNT`、WS/IS 或 per-channel 相关路径后，应运行参数化回归。
- FPGA SoC 目录依赖外部 SoC shell 源码时，通过 `AIENGINE_ROOT` 指定路径。
- 测试输出、波形、工具日志和工程生成目录体积较大，提交前应确认是否确实需要归档。

## 常见问题

### Vivado 脚本提示缺少 RTL 文件

检查 `AIENGINE_ROOT` 是否指向包含 `rtl/axi_accelerator` 和 `picorv32` 的外部集成工程：

```bash
export AIENGINE_ROOT=/media/proj_tmp/aiEngine_integrated
```

### NPU 顶层随机仿真超时或输出不一致

先降低随机范围并关闭 trace 复现：

```bash
make -C test/npu_top run_random \
  SIZE=4 IA_CACHE_BLOCKS=4 PS_FRAME_COUNT=8 \
  COUNT=1 TRACE=0 SEED=<seed> \
  RANDOM_GEN_ARGS='--random --random_quant --lhs_dtype 1 --min_dim 1 --max_dim 12'
```

若是数值错，优先检查 `compute_core`、`ps_buffer` 和 `vec_requant`；若是死锁，优先检查 DMA、arbiter、RAM 随机响应延时和 FIFO full/empty 条件。

### per-channel 模式返回资源缺失

per-channel 模式下 `NPU_REG_Q_MULT` 和 `NPU_REG_Q_SHIFT` 被解释为数组指针，必须指向长度为 `M` 的有效 int32 参数数组。

## License

仓库当前未包含明确的开源许可证文件。对外分发、复用或并入其他工程前，请先补充 LICENSE 并确认第三方依赖和外部 SoC shell 的授权边界。
