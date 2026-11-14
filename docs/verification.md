# 仿真与 FPGA

以下命令在仓库根目录运行。首先执行 `git submodule update --init --recursive`，确保 PicoRV32 源码可用。

## VCS

```bash
make vcs-unit
make vcs-axil
make vcs-soc
make vcs-nmsis-abi
make vcs-tflm
```

`vcs-unit` 运行 DMA、部分和存储、计算核心和 NPU 顶层测试；`vcs-axil` 和 `vcs-soc` 运行 UVM 测试；`vcs-nmsis-abi` 运行驱动接口测试。`make vcs-pcr-soc` 运行 PCR 面板引擎的 SoC 测试。运行日志和构建产物分别位于 `build/vcs/` 和 `veri/sim/runs/`。

可用 `SIZE`、`IA_CACHE_BLOCKS`、`PS_FRAME_COUNT`、`SEED` 等变量设置参数，使用 `make help` 查看入口。

## Python 接口

[Python 模型说明](../veri/python_model/README.md)介绍 Verilator 后端的构建及逐周期比较。PCR 面板引擎对应 `veri/pcr_model/`，构建命令见 [TFLM 说明](../drivers/tflm/README.md)。

## FPGA

Vivado 工程入口、器件和时钟参数见 [Vivado 工程说明](../fpga/vivado/tflm_ai_dsa_soc/README.md)。例如：

```bash
vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_batch_synth.tcl
```

实际时序和资源使用量以对应配置的综合及实现报告为准。

## ASIC

SMIC40 标准单元、SRAM 宏、综合与功能仿真入口见 [ASIC 综合环境](../asic/README.md)。
