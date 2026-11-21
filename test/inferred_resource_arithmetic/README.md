# 地址准备、读取范围和返回路由

## RTL 结构

线性 DMA 的逐通道零点运算、输出写入地址和顶层配置地址准备使用完整位宽的普通加减表达式。运算结果通过 `use_dsp` 属性交给综合工具选择资源，保留原有寄存阶段、符号扩展和溢出行为。RTL 不实例化 LUT、BRAM 或 DSP 原语。

读取保护器把字地址的相等判断分成三个比特一组，各组并行比较。状态更新直接读取分配区间是否含有有效字节的结果，逐字节掩码仍用于返回数据。低地址部分继续使用实际逐字节比较的归并结果，保持四态仿真行为。页内末字索引和下一字地址分别使用可推断的普通算术。

双模式 DMA 在保存前端返回数据的同一边沿保存矩阵响应资格。返回标签和矩阵数据选择直接使用该寄存位，输出周期和窗口背压行为保持一致。

量化行缓冲为计数的每一位并行计算加一和减一的翻转条件。读写事件只选择最终计数位，同时读写时保持计数。行地址、存储时序和组容量预留保持原有行为。

## 已执行的检查

| 检查对象 | 覆盖与结果 |
|---|---|
| 线性 DMA、输出写入模块 | 共 10 组参数，完整模块状态和公开输出逐周期等价证明通过 |
| 读取保护器 | 7 组地址和数据宽度、页拆分配置的完整状态证明通过；32/64 位总线的 4 种配置各完成 20,000 个四态周期比较 |
| 量化缓冲控制 | 7 种深度的控制状态与全部存储端口等价证明通过，两侧存储读取值使用同一任意输入 |
| 量化缓冲存储 | 10 种深度和通道组合，33,045 次行读取、3,941,205 次有效数据位比较通过，覆盖满容量、回绕、并发、暂停、清空和复位 |
| 顶层地址算术 | 5 组尺寸和共享存储配置的完整输入证明通过，40,960 组四态样本一致 |
| DMA 返回路由 | 复位检查和无界归纳通过，196,608 次四态比较一致，覆盖返回标签、输出资格和背压保持 |

完整模块证明使用未约束的功能输入。顶层算术和返回路由检查从实际 RTL 提取表达式及寄存过程；量化缓冲的存储功能另由真实存储 RTL 与独立队列模型检查。详细参数、文件 SHA256 和结果保存在 [validation.json](validation.json)。

## 独立综合

以下结果使用相同生产参数和 `xc7` 综合设置。LUT 合计包含分布式存储的标称占用，路径统计遍历完整的寄存器连接图。

| 模块 | 参考 LUT | 当前 LUT | 参考 DSP | 当前 DSP | 参考最长级数 | 当前最长级数 |
|---|---:|---:|---:|---:|---:|---:|
| `conv_axi_read_guard` | 821 | 698 | 16 | 19 | 10 | 9 |
| `axi_linear_block_dma` | 1,556 | 1,487 | 9 | 17 | 10 | 10 |
| `oa_writer` | 1,165 | 1,147 | 16 | 17 | 8 | 7 |
| `requant_group_buffer` | 56 | 59 | 0 | 0 | 6 | 5 |

这些数值来自各模块独立实例。完整 SoC 使用固定源码版本重新综合，以统计跨模块路径。150 MHz 需要目标器件的布局、布线和静态时序分析结果确认。

## 复现

```sh
python3 test/inferred_resource_arithmetic/run_formal.py \
  --reference 0097b66e --cases linear_dma oa_writer read_guard requant_buffer \
  --out /tmp/resource_arithmetic_formal
python3 test/inferred_resource_arithmetic/run_top.py --out /tmp/top_arithmetic
python3 test/inferred_resource_arithmetic/run_return_routing.py --out /tmp/return_routing
python3 test/conv_guard/run_four_state.py \
  --reference-ref 0097b66e --out /tmp/read_guard_four_state
python3 test/requant_group_buffer_memory/run.py \
  --out /tmp/group_memory --verilator verilator --jobs 1
```
