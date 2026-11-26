# 权重行首地址的分段加法

行首地址与行间距按高、低两段同时求和，低段进位只参与高段的分组修正。完整模宽结果由普通算术表达式推断，描述符保存时钟、遍历状态和地址回绕行为保持一致。分组地址与分组列位置只保存使用到的和值；未连接的最高进位输出不要求保留额外组合节点。

生产加法表达式在含未知输入时使用完整模宽的原生加法。16、32、64 位三种地址宽度分别检查通用和 FPGA 两种编译方式，共完成 49,152 次四态比较。完整权重控制器在四组分块与计数参数、两种明确宏配置下完成八项时序等价证明，全部共有状态和公开输出每周期一致，外部输入没有附加限制。

## 完整加载器测量

采用 16 个元素一块、29 位计数、64 位总线，参照提交为 `d7cb67be`。两种实现使用相同综合设置并通过 ABC9 映射检查。

| 指标 | 参照实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 2,888 | 2,902 |
| 触发器 | 1,990 | 1,990 |
| 推断 DSP | 10 | 11 |
| RAMB18 等效块 | 16 | 16 |
| 最长寄存器间组合级数 | 11 | 10 |
| 行间距寄存器到当前 DMA 地址 | 10 | 4 |

完整资源和实际连接路径保存在 `measurement.json`，状态与算术检查保存在 `validation.json`。

```bash
python3 test/kernel_completion/run.py --reference d7cb67be --out build/kernel_row_address/control
python3 test/kernel_row_address/check_arithmetic.py --out build/kernel_row_address/arithmetic
python3 test/kernel_port_selection/measure.py --reference d7cb67be --out build/kernel_row_address/measurement
```
