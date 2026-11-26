# 窗口缓存的并行请求资格与循环预取选择

请求通路分别准备队首、下一项、当前输入和缺失请求的读写冲突及快照资格。需求接收事件选择已经完成的单比特结果，快照仍在原有边沿保存。

预取选择分别寻找队首以后和整个队列的第一个匹配项，再决定循环次序中的首项。没有匹配项时选择队首。逻辑槽位、物理槽位映射、队列容量和预取优先次序保持一致。输入包含 X 或 Z 时，读取资格和循环优先选择使用原表达式的四态传播结果。

## 功能检查

完整窗口缓存采用四组容量、行长度、总线宽度和需求队列深度，分别运行 generic 与 FPGA 配置。8 项时序等价检查覆盖 122,216 个共有状态和输出等价点，外部输入不附加限制。

读取资格和循环优先选择另外通过 16 项任意输入组合证明，以及 1,675,424 次四态比较。循环选择覆盖 1、2、4、8 个条目；8 个条目的测试包含每个有效队首位置下全部四态匹配向量、未知队首下全部二态匹配向量，以及队首和匹配位同时含未知值的输入。

generic 形式检查明确使用 `-USYNTHESIS -UXILINX_FPGA`；FPGA 检查使用 `-DSYNTHESIS=1 -DXILINX_FPGA=1`。完整参照缓存和请求通路及其依赖从提交 `d7cb67be` 读取。当前实现的全部公开输出及共有状态均参与检查。

## 完整缓存测量

配置为 16 组、2 路、128 字节缓存行、64 位外部总线与读取数据、2 个需求队列条目。两种实现采用相同综合脚本和 ABC9 物理成本映射，延迟目标为 6,667 ps、连线估计为 300 ps、最大 LUT 输入数为 8。

| 指标 | 参照实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 2,792 | 2,769 |
| LUTRAM 名义位置 | 68 | 68 |
| 触发器 | 2,001 | 2,001 |
| DSP | 16 | 16 |
| RAMB36 等效块 | 1 | 1 |
| RAMB18 等效块 | 26 | 26 |
| 最长寄存器间组合级数 | 10 | 10 |
| 请求计数到快照有效状态 | 10 | 8 |
| 填充组号到选择状态 | 10 | 9 |
| 缺失请求填充组号到选择状态 | 10 | 9 |
| 槽位映射到预取存储地址 | 9 | 10 |

逻辑 LUT 减少 23，包含 LUTRAM 的名义 LUT 数为 2,837。资源计数和组合级数来自完整缓存的实际连接图。150 MHz 的器件时序由布局布线后的延迟报告确认。

`measurement.json` 保存资源、输入摘要和指定路径，`validation.json` 保存全部功能检查结果。

## 重现

```bash
python3 test/cache_lookup_parallel/check_parent.py --out build/cache_lookup_parallel/parent
python3 test/cache_lookup_parallel/check_qualification.py --out build/cache_lookup_parallel/qualification
python3 test/cache_lookup_parallel/check_priority.py --out build/cache_lookup_parallel/priority
python3 test/cache_lookup_parallel/measure.py --out build/cache_lookup_parallel/measurement
```
