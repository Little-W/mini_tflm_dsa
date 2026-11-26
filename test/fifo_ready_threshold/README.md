# 输出容量阈值比较

`fifo_ready_threshold` 以三个计数位为一组，并行比较已经完成写入的存储体数量和接收阈值。最高的不相等分组决定大小关系，部分写入与计数回绕条件在最终组合层参与结果。`fifo_bank_watermark` 在预计算阈值配置下使用该模块，FIFO 的数据存储、寄存器更新和握手周期保持相同。

未知输入使用完整关系表达式确定结果，保留原有 X/Z 传播规则。

## 功能检查

通用和 FPGA 编译方式分别完成一项覆盖 12 种计数宽度的全输入组合证明。计数宽度为 1、2、3、4、5、6、7、9、12、16、32、64 位，所有计数、阈值和部分写入编码均可自由变化。

两种编译方式共完成 983,088 次逐位四态比较，包含六位输入空间的完整遍历、任意宽度边界、随机输入和逐位未知值。结果保存在 `validation.json`。

## 实际映射

比较采用同一组 `physical-cost` 设置：最大 LUT 输入数 8，目标周期 6,667 ps，布线延迟参数 300 ps，启用 ABC9 功能检查。

| 测量范围 | 参考实现 | 当前实现 |
|---|---:|---:|
| 容量比较逻辑 LUT | 5 | 6 |
| 容量比较寄存器间级数 | 3 | 2 |
| 完整 FIFO 名义 LUT 数量 | 1,026 | 1,027 |
| 完整 FIFO 最长寄存器间级数 | 10 | 10 |

完整 FIFO 保留 32 个存储体、16 个向量元素、64 位输出总线和循环数据存储。名义 LUT 数量包含逻辑与分布式存储的架构需求，完整 SoC 的跨模块路径由整机测量报告记录。

## 运行

```sh
python test/fifo_ready_threshold/run.py --out build/fifo_ready_threshold/validation
python test/fifo_ready_threshold/measure.py --out build/fifo_ready_threshold/mapping
```
