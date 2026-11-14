# 硬件架构

## SoC

`soc_top` 集成 PicoRV32、NPU、AXI 互连、共享 RAM 和 UART。CPU 通过 AXI-Lite 配置 NPU，NPU 通过 AXI 主接口访问共享存储器。接口地址及访问方法见 [寄存器说明](../drivers/registers_v2.md) 和 [驱动说明](../drivers/README.md)。

## NPU

NPU 顶层 `rtl/npu/top/npu_top.sv` 组织任务控制器、DMA、输入与权重加载器、计算阵列、部分和存储及输出量化和写回。`SIZE` 配置阵列边长，`IA_CACHE_BLOCKS` 和 `PS_FRAME_COUNT` 控制相关片上存储规模。硬件支持 WS 和 IS 数据流；工作组参数由软件计算后写入寄存器。

数据路径为输入加载、分块矩阵乘累加、输出量化及 AXI 写回。驱动支持 INT8 和 INT16 输入，并提供逐张量及逐通道量化接口。模块目录说明见 [RTL 说明](../rtl/README.md)。

## PCR 面板引擎

`PAPER_ENGINE=1` 选择 GEMPACT PCR 面板引擎。此配置使用 16×16 阵列、32 位总线和 INT8 输入，要求零输入偏移、无 bias、逐张量量化，矩阵尺寸及地址跨度为 16 的整数倍。`PS_POOL_BYTES` 配置部分和页池容量，`PANEL_MAX_R`、`PANEL_MAX_W` 配置面板尺寸上限。更多命令见 [TFLM 说明](../drivers/tflm/README.md)。
