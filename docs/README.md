# 文档中心

本目录介绍 TFLM AI DSA 的硬件结构、构建方法和验证入口。

- [快速开始](getting-started.md)：获取依赖、选择模型及运行仿真。
- [64 位 AXI 比较配置](axi64_configuration.md)：性能配置 PicoRV32、等容量数据 RAM、同步读取、可配置首拍延迟和多个在途请求。
- [64 位 AXI 算子比较](axi64_operators_sync8.md)：相同内存时序下的 GEMM、Conv、DW，以及 Dense 逐项 1.2 倍性能检查。
- [64 位 AXI 完整模型比较](fair_axi64_models.md)：四个 TFLM 模型、第三方 DWConv Gemmini 与硬件 Im2Col、逐层输出检查和 1000 倍周期预算。
- [64 位 AXI 瓶颈分析](axi64_bottlenecks.md)：Dense 外部带宽、DW 窗口返回、Conv 数据复用和部分和调度的实测与理论下界。
- [Gemmini 对等测试与性能分析](gemmini_comparison.md)：三种 Gemmini 存储配置、34 个共同算子、四个完整模型、PE 利用率、存储带宽与初始化开销。
- [硬件架构](architecture.md)：SoC、统一计算路径、共享 IA/PS bank 和容量调度。
- [向量计算引擎](vector_engine.md)：共享 DW、池化、Add 数据通路，输入复用、最近偶数舍入和完整模型测试；Softmax 与共享窗口缓存的当前设计见 Gemmini 性能分析。
- [VCE 完整模型测试结果](vce_model_performance.md)：32 位总线下的完整推理、逐算子周期、占比和正确性检查。
- [容量求解器](capacity.md)：统计缓冲数组和完整顺序逻辑状态，选择 IA/PS 容量及每层分配。
- [im2col 缓存容量配置](im2col_cache_configuration.md)：配置 512 B～64 KiB 输入缓存，查看对应卷积尺寸、状态开销与访存仿真结果。
- [共享 IA/PS 测量方法](shared_ia_ps_performance.md)：同一硬件和固件上的 RAW32/压缩对照、逐层周期、完整网络周期与初始化成本。
- [软件与模型](software.md)：寄存器、驱动、模型选择与 NMSIS。
- [ASIC 综合与路径优化](asic_synthesis.md)：SMIC40 SRAM 宏、分阶段频率约束及前 100 条最大延时路径分析。
- [仿真监视模块](../test/monitors/README.md)：TB 性能统计、层级观察与 RTL 断言配置。
- [仿真与 FPGA](verification.md)：VCS、Python 接口和 Vivado 的使用。
- [FPGA 资源与时序规划](fpga_resource_budget.md)：150 MHz、完整 SoC 的 LUT 分配，以及模块级优化与验证方法。
- [开源 FPGA 综合](open_fpga_synthesis.md)：使用 Yosys 比较模块资源和组合逻辑级数。
- [FPGA 优化交接](fpga_optimization_handoff.md)：当前资源、验证方法和后续优化方向。
- [block_dma 统一矩阵与 im2col 接口](block_dma_im2col.md)：当前主设计，包含 WS / IS 的分块请求、返回接口、DMA 内部缓存、事务完成处理、驱动与验证程序。
- [NMSIS 与 SoC 卷积性能对照](conv_soc_performance.md)：真实 PicoRV32 上比较原 CPU im2col 加 DSA GEMM 与 DMA 硬件 im2col，列明周期、流量、参考程序和适用范围。
- [Conv 源码交付与即时生成测试](conv_source_only.md)：使用固定提交 `148964d1`，测试向量、访问轨迹与编译产物在运行时生成，版本库保存源码。
- [硬件 Conv 集成与验证](hardware_conv.md)：运行时卷积配置、窗口数据复用、实际 RTL / NMSIS 协同仿真和支持范围。
- [卷积专用缓存替换](conv_replacement.md)：可配置的未来访问预测策略、真实 CNN 比较与存储成本；当前窗口策略使用 4 KiB 共享数据缓存。

默认 `PCR_ENGINE=1` 在统一 NPU 路径中启用 frame 存储，部分和使用固定 INT32 表示，硬件 Conv 与 Dense 使用同一组加载器、计算阵列及写回资源。VCE 使用独立的向量 PE，并与矩阵路径共享 DMA 和窗口缓存。窗口缓存的数据容量由 `IM2COL_CACHE_BYTES` 设置，默认 4 KiB。共享 RAM 使用六至九个 bank，bank 大小可选 2、4、8 KiB，通用及 ASIC 配置默认九个 2 KiB bank，FPGA 配置默认七个 8 KiB bank。软件在模型初始化时选择每层的 IA 容量、PS 策略和 R/W，推理时提交准备好的配置。AXI4 数据宽度通过 `NPU_AXI_DATA_WIDTH` 选择 32 或 64 位；AXI-Lite 配置接口保持 32 位数据和 16 位地址。

寄存器的完整定义见 [寄存器说明](../drivers/registers_v2.md)，FPGA 工程参数见 [Vivado 工程说明](../fpga/vivado/tflm_ai_dsa_soc/README.md)。
