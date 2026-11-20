# 权重 DMA 行组装

## 数据组织

`kernel_loader` 按 DMA 返回的列起点，将有效输入通道写入当前权重行。通道数为二的幂时，当前实现先根据列起点低位循环选择输入数据和有效标志。相隔 `BUS_WIDTH/8` 列的位置共用这一选择结果，每列分别检查传输范围、物理列数和逻辑列数，决定写入、填零或保留已有值。

最后一个实际有效元素决定整行完成。完成时输出本次组装结果并清空行累积寄存器。FPGA 实现用一个 `LUT6_2` 同时生成每位输出行和累积行，两个输出共用列范围、更新条件及输入数据；通用实现使用相同的布尔表达式。清空缓存、丢弃传输、部分有效通道和末尾填充沿用原有优先次序。其他整数通道数使用逐项更新结构。

修改仅涉及行组装组合逻辑。描述符控制、两个逻辑槽位、三个物理权重槽位、列存储器以及所有寄存周期保持一致。生产配置的权重存储继续保存 `3 × 16 × 16` 个 16 位数值。

## 面积来源

固定提交 `722112fa` 的完整 SoC 中，`shared_between_modules` 共计 6811 个逻辑 LUT。按原始信号和实际消费者检查，最大的 977 个 LUT 组连接 `kernel_loader` 与 `kernel_loader_buffer`，主要输出为 `row_emit_n`、`dma_row_data` 和 `u_buf.row_data`。本次优化针对其中的输入通道选择与行累积更新。

其他较大的组分别为写回数据到 linear DMA 的输出选择 936 个 LUT、权重预取描述符相关逻辑 380 个 LUT，以及共享存储返回数据相关逻辑 271 个 LUT。分类结果保存在验证报告中。

## 完整加载器综合

参考提交为 `015b4187`。两份实现使用相同的 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=29` 和原生 Xilinx 7 系列综合流程，包含实际权重存储和计数控制器。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 7860 | 4798 |
| 分布式 RAM LUT | 384 | 384 |
| 触发器 | 2786 | 2786 |
| DSP48E1 | 6 | 6 |
| CARRY4 | 292 | 342 |
| 寄存器间最长组合单元数 | 14 | 15 |

逻辑 LUT 减少 3062 个，约 39.0%。逐位连接图完整，最长组合路径满足不超过 15 级的要求。完整 SoC 的物理 LUT 位置与 150 MHz 时序由整机实现报告统计。

## 功能和周期

`run_formal.py` 从实际源码提取行组装部分，验证其余源码按字节一致，并证明所有输入位模式下的累积行、输出行和完成条件相同。

| 检查 | 配置与结果 |
|---|---|
| 行组装组合等价 | 7 种配置分别检查通用与 FPGA 实现，共 14 组、3868 个结果位，全部通过 |
| 非二的幂配置 | `SIZE=6/BUS_WIDTH=64`、`SIZE=4/BUS_WIDTH=24`，通过 |
| 单通道配置 | `SIZE=4/BUS_WIDTH=8`，通过 |
| 完整加载器状态与输出 | 2 种配置、28280 位，通过 |
| 完整状态的小配置 | `SIZE=4/DATA_WIDTH=8/BUS_WIDTH=32/COUNT_WIDTH=8` |
| 完整状态的生产配置 | `SIZE=16/DATA_WIDTH=16/BUS_WIDTH=64/COUNT_WIDTH=29` |

完整状态证明使用实际 FPGA 分支及官方 LUT、DSP 功能模型，外部输入没有附加取值限制。

实际预取测试运行 32、64、128 位总线三种配置，每种检查 270 块权重和 69120 个数值，共 810 块、207360 个数值。32 位总线运行 42035 周期，64 位总线运行 27456 周期，128 位总线运行 19841 周期，全部通过。

这些测试覆盖预取命中、在途命中、请求等待、描述符不匹配、延迟预取、清空与排空、8 位和 16 位数据、im2col、末尾块及随机请求。每种总线均达到两个有效槽位和两个并发 DMA 上下文，并完成 12 次重叠启动。测试使用实际 FPGA 功能模型，并对全部 C++ 编译单元启用未定义行为检查。

源码摘要、原语模型、仿真程序、完整状态证明和独立综合结果记录在 `docs/data/kernel_row_assembly_validation.json`。当前源码 SHA-256 为 `3b95388048c4bb75b56dacfd21600f3aecbaa4e561a93cb393ce747f48f0e86d`，参考源码为 `910e30a9f550c8423b3a718dd814c5a9ae536df31c1d2895c369848989eae500`。

## 复现

从仓库根目录运行，环境需提供带 slang 的 Pyosys 和 Verilator。

```bash
python3 test/kernel_row_assembly/run_formal.py \
  --reference 015b4187 --out build/kernel_row_assembly/formal
python3 test/kernel_prefetch/run.py --fpga --verilator verilator-modern \
  --bus-width 32 --count-width 29 --out build/kernel_row_assembly/sim32
python3 test/kernel_prefetch/run.py --fpga --verilator verilator-modern \
  --bus-width 64 --count-width 29 --out build/kernel_row_assembly/sim64
python3 test/kernel_prefetch/run.py --fpga --verilator verilator-modern \
  --bus-width 128 --count-width 29 --out build/kernel_row_assembly/sim128
python3 test/kernel_count_paths/prepare_measurement.py \
  --reference 015b4187 --out build/kernel_row_assembly/sources
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/kernel_row_assembly/sources/cases.json \
  --cases loader_reference loader_current --out build/kernel_row_assembly/synthesis
```
