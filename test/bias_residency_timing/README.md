# 偏置驻留范围与尾块行数

## 当前设计

两个数据银行并行计算请求起点、请求末端及装载状态，银行选择作用于最终驻留结果。请求起点使用完整扩展减法，借位表示请求是否位于银行起点之前。请求末端先将起点、长度和银行末端压缩为两个操作数，再通过公共定宽加法器取得最终进位。所有扩展位与计数回绕行为保持一致。

DMA 完整行数和扣除尾块后的行数并行计算，由范围条件选择最终行数。配置、装载和读取的采样周期、存储深度与数据精度保持一致。FPGA 通过普通算术与 `use_dsp` 属性推断运算资源。

## 验证结果

以提交 `415a70a` 为参考，完整 `bias_loader` 在六组参数下证明 118,489 个公开输出和共同状态位逐周期一致。公开输入和握手序列没有附加约束。

| SIZE | BUS_WIDTH | COUNT_WIDTH | GROUP_BLOCKS_MAX |
|---:|---:|---:|---:|
| 4 | 32 | 1 | 1 |
| 16 | 32 | 12 | 4 |
| 16 | 64 | 28 | 32 |
| 16 | 64 | 29 | 32 |
| 16 | 128 | 29 | 32 |
| 16 | 64 | 32 | 1 |

实际范围判断的四态仿真覆盖 1、5、29、32 位计数和两种装载索引共享配置，完成 142,720 次严格比较。

生产参数为 `SIZE=16`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`GROUP_BLOCKS_MAX=32`。完整加载器映射为 928 个逻辑 LUT、1,227 个触发器、12 个 DSP 和一个 RAMB36，最长寄存器间组合路径为 8 级，连接图完整。

## 复现

```bash
python test/bias_residency_timing/run_formal.py \
  --reference-rev 415a70a --out build/bias_residency_formal
python test/bias_residency_timing/check_four_state.py \
  --reference-rev 415a70a --out build/bias_residency_four_state
python test/bias_loader_reuse/run.py --out build/bias_residency_numeric --jobs 1
```

`measurement.json` 保存当前源码 SHA256、逐配置证明、四态检查和完整模块综合统计。实际 150 MHz 时序由 SoC 布局布线报告确认。
