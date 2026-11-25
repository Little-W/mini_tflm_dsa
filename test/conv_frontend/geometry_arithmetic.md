# 坐标地址增量算术

`conv_geometry_movement_add` 计算完整的 32 位地址增量和。低、高半字分别使用普通加法表达式，低半字进位修正高半字结果。综合器依据 `use_dsp` 属性推断算术资源，设计 RTL 保留通用表达式。

该组合模块服务于五组地址增量。状态寄存器、更新边沿、数值位宽和公开端口保持相同的逐周期行为。

## 固定配置测量

比较版本为 `35408bcf`。两侧均显式传入生产参数，使用相同的 Yosys XC7 映射、64 个模块一批的 ABC9 设置，以及完整连接路径分析。

| 项目 | 比较版本 | 当前设计 |
| --- | ---: | ---: |
| 完整坐标模块逻辑 LUT | 4,937 | 4,742 |
| 完整坐标模块触发器 | 1,458 | 1,458 |
| 完整坐标模块 DSP | 8 | 13 |
| 完整坐标模块最长寄存器路径 | 8 | 8 |
| 完整 im2col 前端逻辑 LUT | 16,872 | 16,677 |
| 完整 im2col 前端 LUT 合计 | 16,940 | 16,745 |
| 完整 im2col 前端触发器 | 6,241 | 6,241 |
| 完整 im2col 前端 DSP | 13 | 18 |
| 完整 im2col 前端 RAMB36 / RAMB18 | 1 / 22 | 1 / 22 |
| 前端最长寄存器路径 | 17 | 17 |
| 输入至寄存器路径 | 17 | 17 |
| 寄存器至输出路径 | 12 | 12 |
| 输入至输出路径 | 2 | 2 |

前端 LUT 合计包含 68 个分布式 RAM 的名义 LUT 位置。前端参数为 SIZE16、SLOT5、LANES8、LINE128、BUS64、DMA2048、SETS16、WAYS2、POLICY3、REGISTER_DESCRIPTOR0、REGISTER_CACHE_REQUEST1 和 RSP_FIFO_DEPTH1。模块测量用于确认地址增量改写的实际影响，完整 SoC 的总资源独立测量。

## 功能检查

四组完整坐标模块参数覆盖 1、8、16 个并行通道以及两种描述符寄存配置，共 11,926 个等价位全部通过无限时序证明。证明比较所有公开输出与真实状态，结构合并得到的等价点也全部完成证明，不限制外部输入。

所使用的 `parallel_prefix_add` 文件与其既有器件功能验证的 SHA256 相同。32 位、固定输入进位为零的实际映射网表使用完整 Xilinx 功能模型，33 位和值及最高进位全部通过等价证明。非综合 RTL 的四态检查记录与该文件摘要一并保存。

```bash
python test/conv_frontend/tools/check_geometry_arithmetic.py \
  --reference 35408bcf \
  --out build/geometry_arithmetic_equivalence
```

完整参数、源文件摘要、资源统计、路径深度和形式证明结果见 [geometry_arithmetic_validation.json](geometry_arithmetic_validation.json)。
