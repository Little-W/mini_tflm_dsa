# FPGA 面积和时序优化交接

## 目标与设计范围

完整 SoC 面向 Artix-7 `xc7a200tfbg484-3`，时钟目标为 150 MHz，周期为 6.667 ns，LUT 占用目标少于 50,000。当前工作分支为 `experiment/no-ps-compression`，部分和采用直接 INT32 存储。设计同时支持可切换的 WS 和 IS、INT8 与 INT16 GEMM、硬件 im2col 卷积、深度卷积、池化、Add 和 Softmax。

优化应保持计算结果、事务顺序、复位与错误恢复行为。NPU 控制和地址生成不引入运行时除法器；PicoRV32 保留其现有除法器。性能统计放在测试平台，RTL 中仅在仿真宏控制下保留必要的不可综合断言。优先使用固定连接、计数器、标志位和分阶段状态控制。

## 当前实现与测量

开源综合流程和参考数据见 [开源 FPGA 综合](open_fpga_synthesis.md) 及其 [资源数据](data/open_fpga_reference.json)。Yosys 0.71 对完整 NPU 的映射统计如下：

| 项目 | 结果 |
| --- | ---: |
| LUT 逻辑单元 | 69,871 |
| 触发器 | 45,171 |
| DSP48E1 | 390 |
| RAMB36E1 / RAMB18E1 | 85 / 89 |
| RAM64M / SRL16E | 48 / 192 |
| 组合路径最大级数 | 35 |

该流程独立综合 NPU，组合逻辑级数用于定位结构复杂的路径。LUT 单元、分布式 RAM 和移位寄存器资源分别统计。初步优化规划是将 NPU 逻辑 LUT 单元压至 40,000 以下，并保留 SoC 互连与处理器所需的资源。

完整 SoC 的最近一次 Vivado 综合使用同一器件和 150 MHz 约束，得到 76,562 LUT、54,643 个触发器、448 个 DSP 和 179 个块 RAM tile；最差建立时间裕量为 −8.617 ns。该结果未满足面积和时序目标。Vivado 的层次统计中，NPU 占 71,011 LUT，其中 DMA 及其缓存约 22,019 LUT，向量计算单元约 12,243 LUT，计算核心约 7,577 LUT，权重加载器约 4,979 LUT，IA 加载器约 3,749 LUT，共享存储器接口约 3,868 LUT。这些模块层次数值适合确定优化次序；开源综合与 Vivado 的资源映射和 LUT 打包方式各自独立。

已完成的结构包括：阵列的活动权重与预取权重寄存器、偏置同步 RAM、共享 IA/PS RAM 的固定 bank 路由、分阶段配置计算、向量写回的数据分组，以及支持同步块 RAM 推断的卷积缓存。脉动阵列保持原有权重输入方向及外部旋转结构。

## 建议优先处理的模块

1. **DMA 和卷积缓存。** 检查 `rtl/npu/dma/`、`rtl/npu/dma/cache/` 和 `rtl/npu/conv/conv_im2col_frontend.sv`。优先压缩缓存标签、预取状态、地址运算和多路选择的面积，保留同步 RAM、字节写使能、突发边界和错误恢复。评估地址递推与提前准备，以减少每个输出位置重复计算坐标及预取地址所需的周期。
2. **向量计算单元。** 检查 `rtl/npu/conv/vector_engine.sv` 及其配置、舍入、Softmax 和写回子模块。优先复用算术资源、缩小操作数位宽并拆分功能控制，确保各功能模式、吞吐率和舍入结果正确。
3. **权重及 IA 加载器。** 检查 `rtl/npu/loaders/` 中的地址选择、缓存状态和加载请求握手。完整 SoC 的最长时序路径经过 IA 加载请求、DMA 仲裁及向量控制；减少组合握手跨模块传播，并检查引入寄存器后的事务顺序与周期变化。
4. **共享存储和工作区调度。** 检查 `rtl/npu/buffers/ia_ps_shared_ram.sv` 与 `rtl/npu/control/ps_window_scheduler.sv`。保持 IA 和部分和共享 RAM、端口优先级、同步读取与冲突处理。

固定等待配置下，`perf_mobile_dw_48_c8` 运行 147,841 周期，读取 18,632 字节，缓存缺失 1,038 次，预取 117 条缓存行。该任务可用于检查连续输出位置的地址递推与预取时机。

性能分析应固定阵列尺寸、数据宽度、缓存容量、总线宽度和外部存储延迟，同时记录周期、输入读取字节数、缓存命中与缺失、预取量及等待周期。对于长组合路径，优先检查运算、选择器及握手跨越的寄存器边界，避免仅凭逻辑级数推断实际时钟频率。

## 无 Vivado 环境的工作流程

安装 Python 环境、Verilator、C/C++ 编译器、GNU Make 和 `pyosys`。在仓库根目录运行：

```sh
python3 -m pip install pyosys==0.71.post40
make open-fpga-synth
make open-fpga-synth OPEN_FPGA_SYNTH_CASES=npu_top
python3 test/cache_pipeline/run.py --jobs 2
python3 test/conv_replacement/predictor_test.py
python3 test/vector_engine/run.py --tile 16 --pes 8 --jobs 2 --perf
python3 test/conv_npu/run.py --sizes 16 --bus-width 64 --shared-bank-bytes 8192 --shared-bank-count 7 --smoke
```

Yosys 结果位于 `build/open_fpga_synth/`，包含映射网表、源码摘要、资源统计和最长组合路径单元序列。每次修改使用独立输出目录并核对源码摘要；功能测试还应覆盖随机等待、尾块、32/64 位总线及错误恢复。完整模型性能测试的模型准备、RISC-V 工具链和运行方法见 [完整模型性能测试](../test/model_benchmark/README.md)。

当前修改已通过完整 NPU 的 38 项任务检查、缓存流水线测试、预测器 31 项测试、32/64 位缓存 RAM 逐周期比较及阵列权重四态仿真。完整 SoC 面积和时序需要在具备目标器件模型的环境中再次检查；开源布局布线工具应明确记录器件、封装、速度等级及其时序模型的覆盖范围。
