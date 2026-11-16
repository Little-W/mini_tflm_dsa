# 文档中心

本目录介绍 TFLM AI DSA 的硬件结构、构建方法和验证入口。

- [快速开始](getting-started.md)：获取依赖、选择模型及运行仿真。
- [Gemmini 对等测试与性能分析](gemmini_comparison.md)：三种 Gemmini 存储配置、34 个共同算子、四个完整模型、PE 利用率、存储带宽与初始化开销。
- [硬件架构](architecture.md)：SoC、NPU 和论文计算引擎的组成。
- [向量计算引擎](vector_engine.md)：共享 DW、池化、Add 数据通路，输入复用、最近偶数舍入和完整模型测试；Softmax 与共享窗口缓存的当前设计见 Gemmini 性能分析。
- [VCE 完整模型测试结果](vce_model_performance.md)：32 位总线下的完整推理、逐算子周期、占比和正确性检查。
- [容量求解器](capacity.md)：在 RAM 或完整逻辑状态预算内选择面板/PS 容量，自动更新构建配置。
- [软件与模型](software.md)：寄存器、驱动、模型选择与 NMSIS。
- [仿真与 FPGA](verification.md)：VCS、Python 接口和 Vivado 的使用。
- [block_dma 统一矩阵与 im2col 接口](block_dma_im2col.md)：当前主设计，包含 WS / IS 的分块请求、返回接口、DMA 内部缓存、事务完成处理、驱动与验证程序。
- [NMSIS 与 SoC 卷积性能对照](conv_soc_performance.md)：真实 PicoRV32 上比较原 CPU im2col 加 DSA GEMM 与 DMA 硬件 im2col，列明周期、流量、参考程序和适用范围。
- [Conv 源码交付与即时生成测试](conv_source_only.md)：使用固定提交 `148964d1`，测试向量、访问轨迹与编译产物在运行时生成，版本库保存源码。
- [硬件 Conv 集成与验证](hardware_conv.md)：运行时卷积配置、窗口数据复用、实际 RTL / NMSIS 协同仿真和支持范围。
- [卷积专用缓存替换](conv_replacement.md)：可配置的未来访问预测策略、真实 CNN 比较与存储成本；当前窗口策略使用 4 KiB 共享数据缓存。

当前默认配置选择 PCR 核心；实际构建使用硬件 Conv 时须选择标准核心（`PCR_ENGINE=0`）。Conv 回归入口由各 Python 脚本选择固定的标准核心测试配置，不会自动套用 menuconfig 的 PCR 容量参数；旧 GEMM 回归另行覆盖 PCR 核心。

寄存器的完整定义见 [寄存器说明](../drivers/registers_v2.md)，FPGA 工程参数见 [Vivado 工程说明](../fpga/vivado/tflm_ai_dsa_soc/README.md)。
