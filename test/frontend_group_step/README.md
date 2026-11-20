# 前端递增通道范围

`LANES <= 4` 时，前端分别计算增量 0 至 `LANES` 对应的低四位加法等式。
加数的第 3 位恒为零；低四位相等成立时，传入第 4 位的进位由
`ch_q[3] && !target[3]` 确定。因此，四个组末阈值的高十二位关系可以提前计算，
与低四位等式共同保留完整的 16 位回绕结果。

实际有效通道掩码只控制最后的两级优先选择。
该选择保留全零掩码与非连续掩码的行为，始终采用最后有效通道对应的增量。
组通道数非零及短组条件与高位关系共同进入末级选择。
`group_range_next[5]` 的四个输出分别合并边界标志，其中三个输出采用独立单级 LUT。
其它通道来源、全部时序状态、接口握手、容量和周期保持一致。

本次隔离验证的参考提交为 `3c8cafeb2bb7029d903479ace4bd591e5109f03b`。
参考前端 SHA-256 为 `257f573697653f2ef5e87b06c39ef4a2c14cefb052b15eea687158bd072e802b`；
当前前端为 `d176073208d2312b446e888c61957a328218a394b9fb0f2ecff11bc94c13901a`。
完整报告保存于 `measurement.json`。

## 正式证明

`formal.py` 直接读取参考与当前源码中的递增边界表达式和最终范围表达式，
并确认其余前端源码逐字相同。
它同时检查通道数编码确实采用最后有效通道，比较器辅助模块与参考版本完全相同。

证明按组合关系分为两部分：

1. 对 `LANES=1、2、3、4`，分别在通用实现和官方 FPGA 原语模型下，证明四个边界标志完全一致。
   每组允许 81 至 84 个输入位任意取值，包括当前通道、四个独立的 16 位阈值和全部有效通道掩码。
2. 对任意四个边界标志，分别证明普通通道来源和递增通道来源的最终四位范围输出。
   通用实现和官方 FPGA 原语模型均通过，四组检查完整覆盖新增的范围合并逻辑。

这两部分共同证明实际 `group_range_next[5]` 的完整四位输出，包含通道索引回绕、全零掩码和非连续掩码。
证明不要求组末阈值之间存在特定关系。

## 局部映射

映射直接使用上述实际源码片段，并在输入与完整四位范围输出两侧加入测试寄存器。
参数为 `LANES=4`，启用 FPGA 实现，按真实逐位连接统计组合单元数。

| 项目 | 参考版本 | 当前版本 |
|---|---:|---:|
| 逻辑 LUT | 93 | 97 |
| 触发器 | 88 | 88 |
| 全部输入到四位范围输出的最长路径 | 6 级 | 8 级 |
| 有效通道掩码到四位范围输出的最长路径 | 6 级 | 3 级 |

当前最长路径由通道数和阈值的数据运算产生。
晚到的有效通道掩码经过两级优先选择与一级范围合并。
该测量范围包含实际最终输出，全部组合连接均已完成分析。

## FPGA 窗口与数值检查

数值测试采用实际 DMA、前端、缓存及官方 FPGA 原语模型，并启用协议断言和未定义行为检查。
配置为 `BUS_WIDTH=32`、DMA 大小 64、前端大小 16、`LANES=4`、`CACHE_SETS=128`、`CACHE_BLOCKS=4`。
参考模型的全部源码摘要已核对，当前模型只改变上述前端逻辑。

| 检查 | 结果 |
|---|---|
| 配置、背压、撤销、复位与错误恢复 | 422 个请求接收，418 个完成，4 个复位取消，4,457 个输出数值，19 个预期错误 |
| 连续驻留窗口 | 512 个响应，1,534 周期，最大响应间隔 3 周期 |
| 驻留窗口逐周期比较 | 1,545 行记录完全相同 |
| 非幂次宽度、卷积核及通道数 | 30 组配置，960 个完成请求，7,916 个输出数值，249,416 周期 |
| 非幂次窗口逐周期比较 | 249,411 行记录完全相同 |

## 运行

以下命令在本次隔离提交的源码上重新构建两侧模型及报告。
`window.py` 还支持复用经过源码摘要检查的参考模型。

```bash
source /workspace/scratch/92f7be750f11/toolchain/env.sh
python3 test/frontend_group_step/formal.py --reference 3c8cafeb --out build/r21_group_step/formal
python3 test/frontend_group_step/synthesis.py --proof build/r21_group_step/formal --out build/r21_group_step/local_range --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock --range-output
python3 test/window_dma/run.py --out build/r21_group_step/window --verilator verilator-modern --jobs 1 --fpga --reference-ref 3c8cafeb
python3 test/frontend_group_step/numeric.py --model build/r21_group_step/window --proof build/r21_group_step/formal/summary.json --verilator-include /workspace/scratch/92f7be750f11/toolchain/verilator/verilator/include --out build/r21_group_step/numeric
python3 test/frontend_group_step/summarize.py --build build/r21_group_step --out test/frontend_group_step/measurement.json
```
