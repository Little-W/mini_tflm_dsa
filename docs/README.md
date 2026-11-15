# 文档中心

本目录介绍 TFLM AI DSA 的硬件结构、构建方法和验证入口。

- [快速开始](getting-started.md)：获取依赖、选择模型及运行仿真。
- [硬件架构](architecture.md)：SoC、NPU 和论文计算引擎的组成。
- [DW、池化与向量运算引擎](dw_pool_engine.md)：共享 DMA、默认 8 PE、4 PE 配置、NMSIS 接口与实验结果。
- [容量求解器](capacity.md)：在 RAM 或完整逻辑状态预算内选择面板/PS 容量，自动更新构建配置。
- [软件与模型](software.md)：寄存器、驱动、模型选择与 NMSIS。
- [仿真与 FPGA](verification.md)：VCS、Python 接口和 Vivado 的使用。
- [block_dma 统一矩阵与 im2col 接口](block_dma_im2col.md)：当前主设计，包含 WS / IS 的分块请求、返回合同、DMA 内部缓存、错误排空、驱动与本轮验证。
- [NMSIS 与 SoC 卷积性能对照](conv_soc_performance.md)：真实 PicoRV32 上比较原 CPU im2col 加 DSA GEMM 与 DMA 硬件 im2col，列明周期、流量、基线和适用边界。
- [Conv 源码交付与即时生成测试](conv_source_only.md)：固定 `148964d1` 基线，测试向量、访问轨迹与编译产物在运行时生成，不提交二进制或日志。
- [硬件 Conv 集成与验证](hardware_conv.md)：运行时卷积配置、窗口数据复用、实际 RTL / NMSIS 协同仿真和支持范围。
- [卷积专用缓存替换](conv_replacement.md)：按未来访问预测选择替换和存入，1 KiB 默认配置、真实 CNN 对照与存储成本。

当前默认配置选择 PCR 核心；实际构建使用硬件 Conv 时须选择标准核心（`PCR_ENGINE=0`）。Conv 回归入口由各 Python 脚本选择固定的标准核心测试配置，不会自动套用 menuconfig 的 PCR 容量参数；旧 GEMM 回归另行覆盖 PCR 核心。

寄存器的完整定义见 [寄存器说明](../drivers/registers_v2.md)，FPGA 工程参数见 [Vivado 工程说明](../fpga/vivado/tflm_ai_dsa_soc/README.md)。
