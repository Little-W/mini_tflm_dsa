# IA 加载器的面积与组合路径优化

## 当前实现

预取尾部宽度由低位差和高位模加等式共同确定。下一块是否位于归约范围内，先比较当前高位，再检查相邻高位及低位关系；完整的地址加法与宽比较不再串接。请求和预取标记按三位分组比较，归并结果与行数、槽位及请求资格并行计算。

六个绝对坐标或预取地址加法使用公共 `parallel_prefix_add`，由普通加法表达式推断并行算术资源。地址更新保留双输入组合层次，两个部分和由公共子模块生成，固定为零的输入进位在该层次内完成化简。高段传播按分组形成，所有有效结果位和低段进位均参与计算。控制器的当前迭代与尾部迭代分别计算结束条件，再选择单个位的结果。

共享写数据排列复用普通数据路径的低字节，在列位置确定后恢复紧凑存储偏移，减少重复排列。读数据恢复按所需结果宽度描述算术。配置中的存储容量、寄存器接收边沿、握手与输出周期保持一致。未知输入使用原有表达式的四态传播规则。

## 生产参数

`measure.json` 指定 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`DMA_LANES=8`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、`COMPACT_S8=1`、`ORDERED_JOB=1`、`RAM_WORD_ADDR_WIDTH=12`、`PS_FRAME_COUNT=16`，并启用 DMA 源数据排列、共享写数据寄存级和 DMA 请求寄存级。

共享数据存储测试使用 7 个 8192 字节存储块，完整检查 1、2、4 个存储块分配给 IA 时的行为。2 个 IA 存储块提供 32 个普通槽位或 64 个紧凑槽位。

## 验证方法

所有版本比较以提交 `7ddc0d8d` 为参考。测试脚本在输出目录保存输入文件摘要、参数、形式验证日志、仿真结果及运行配置。

```bash
python3 test/ia_optimization/compare_formal.py --out build/ia_optimization/formal
python3 test/ia_optimization/compare_interface.py --out build/ia_optimization/interface
python3 test/ia_optimization/check_prefetch_width.py --out build/ia_optimization/prefetch
python3 test/ia_optimization/check_iteration_boundaries.py --out build/ia_optimization/iteration
python3 test/ia_optimization/check_write_format.py --out build/ia_optimization/write
python3 test/ia_optimization/check_arithmetic_four_state.py --out build/ia_optimization/arithmetic
python3 test/ia_optimization/check_mapped_arithmetic.py --out build/ia_optimization/mapped
python3 test/ia_shared/run.py --out build/ia_optimization/shared \
  --bank-bytes 8192 --bank-count 7 --compact-offset-width 9 \
  --bus-width 64 --dma-lanes 8 --shared-write-stage 1 --jobs 1
```

`compare_formal.py` 在五组参数下比较完整 IA 的公开输出和状态更新，覆盖生产配置、32 位计数、关闭紧凑存储、四通道通用配置和十六通道通用配置。输入不施加取值限制，存储器展开后使用等价证明与时序归纳。

`compare_interface.py` 复用数值驱动，对两个完整 IA 实例施加相同输入，逐周期比较全部公开输出，包括未使能时的输出值。预取、有序预取和 32 个普通槽位三组测试同时检查数据值、DMA 描述符、复用、尾部、回绕与请求保持。

四态测试直接从两个版本的实际 RTL 提取相关表达式和寄存器结构。固定随机种子为 `20261125`，涵盖 X/Z 数据、控制字段、输入掩码、使能与保持。实际映射后的算术测试加载完整的 `xilinx/cells_sim.v` 功能模型，证明地址、写数据排列和读数据恢复的全部 704 位公开输出。

## 资源与路径测量

```bash
python3 scripts/fpga/open_fpga_synth.py \
  --case-config test/ia_optimization/measure.json --cases ia_production \
  --out build/ia_optimization/fpga \
  --abc9-batch-size 256 --abc9-isolate-leaves
```

资源来自完整 `ia_loader` 实例的 Xilinx 7 系列映射。其外部共享数据 RAM 由上层实例化；共享存储的容量与并发行为由上述数值测试覆盖。组合路径分析使用寄存器和存储端口之间的完整连接图，并检查未分类单元、组合环及未完成映射的内部单元。

`validation.json` 保存实际运行结果。LUT 原语、分布式 RAM、INV、寄存器、DSP 和块 RAM 分别统计。物理 Slice LUT 数量及 150 MHz 的时序结果需要目标器件的布局布线测量。

## 已完成的检查

五组完整模块时序等价证明共通过 58,723 个等价点。三组接口比较共运行 239,923 个周期，对全部 40 个公开输出逐周期比较，并完成 1,083,872 个数值检查。局部四态测试完成 2,741,058 次比较。实际映射的三个算术模块使用完整器件模型，全部 704 位公开输出的时序等价证明通过。

64 位总线、8 个 DMA 通道的共享存储测试运行 2,834,983 个周期，完成 15,022,624 个数值检查。该测试包含 256 种紧凑偏移、全部 65,536 种 16 位输入图样、任意输入掩码、跨存储字写入以及 IA 与 PS 并发读写。

| 完整 IA 实例的测量项目 | 参考版本 | 当前版本 |
| --- | ---: | ---: |
| 逻辑 LUT 原语 | 5,866 | 5,527 |
| 分布式 RAM 名义 LUT | 20 | 20 |
| INV | 181 | 195 |
| FF | 2,812 | 2,816 |
| DSP48E1 | 0 | 10 |
| RAMB36E1 | 2 | 2 |
| RAMB18E1 | 1 | 1 |
| CARRY4 | 387 | 332 |
| 寄存器间最长组合路径 | 12 | 10 |

两份完整连接图均无未分类单元和组合环。普通存储槽位、紧凑存储槽位和数值结果保持相同。
