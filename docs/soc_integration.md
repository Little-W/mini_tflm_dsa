# SoC 集成与验证

## 硬件组成

`soc_top` 集成 PicoRV32、NPU、AXI 互连、共享 RAM、UART 和 SoC 控制寄存器。NPU 通过 AXI-Lite 接收任务配置，并作为 AXI 主设备访问共享 RAM。CPU 通过 MMIO 写入任务参数和读取完成状态。

| 地址 | 用途 |
|---|---|
| `0x0000_0000` | 程序与数据 RAM |
| `0x0200_0000` | UART 寄存器 |
| `0x1000_0000` | NPU AXI-Lite 寄存器 |
| `0x2000_0000` | SoC 完成状态与进度寄存器 |

处理器源码位于 `picorv32/`，NPU RTL 位于 `rtl/npu/`，配置接口和 SoC 外设分别位于 `rtl/axi_top/`、`rtl/soc/`。FPGA、UVM 和模块测试均读取这些源码。

## 任务配置

驱动根据输出矩阵尺寸、阵列尺寸及片上缓存容量计算操作数复用窗口、工作组数量和尾组大小。`drivers/gempact_tiling.h` 提供计算函数；`drivers/dsa_accel.c` 和 NMSIS-NN 驱动写入对应寄存器。寄存器地址和控制位见 [寄存器说明](../drivers/registers_v2.md)。

TFLM 的 INT16×INT8 路径使用 INT16 输入、INT8 权重、INT32 偏置和 INT16 输出。NMSIS 驱动在启动 NPU 前写入工作组配置。

## 统一仿真入口

从仓库根目录运行：

```bash
make vcs-unit
make vcs-axil
make vcs-soc
make vcs-nmsis-abi
make vcs-tflm TFLM_APP=mnist_mlp_int16x8
```

`vcs-unit` 覆盖 DMA、DMA 仲裁、部分和缓存、计算核心和 NPU 顶层。`vcs-axil` 和 `vcs-soc` 使用 UVM 环境；`vcs-nmsis-abi` 检查 NMSIS 驱动的多工作组计算及尾组输出。`vcs-tflm` 编译 RISC-V 固件并在 SoC 中运行模型。

可使用 `SIZE`、`IA_CACHE_BLOCKS`、`PS_FRAME_COUNT`、`SEED` 和 `SIM_ARGS` 指定阵列、缓存和测试参数。例如：

```bash
make vcs-soc SIZE=4 IA_CACHE_BLOCKS=4 PS_FRAME_COUNT=8 \
  SOC_K=9 SOC_N=12 SOC_M=11 SOC_DATAFLOW_MODE=1 SOC_LHS_DTYPE=2
make vcs-random-npu COUNT=2 SEED=42
```

模块测试的构建产物和日志位于 `build/vcs/unit/`，UVM 日志位于 `veri/sim/runs/`。测试运行器检查仿真退出状态、模块测试的成功标记以及 UVM 错误计数。

## Python 周期模型

`veri/python_model/` 提供 Python 接口，使用本仓库 NPU RTL、顶层测试平台和 AXI 存储器模型。构建和逐周期比较方法见 [Python 仿真说明](../veri/python_model/README.md)。

## FPGA

`fpga/vivado/tflm_ai_dsa_soc/scripts/sources.tcl` 枚举本仓库的硬件源码。工程创建、综合和导出方法见 [FPGA 工程说明](../fpga/vivado/tflm_ai_dsa_soc/README.md)。
