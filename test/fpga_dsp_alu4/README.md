# 四通道 DSP 算术映射

## 接口和位宽

`fpga_dsp_alu4` 使用一个组合模式的 `DSP48E1`，配置为 `FOUR12`，提供
四个独立的十位算术通道。`A`、`B`、`X`、`Y` 和 `CO` 均为四十位，
通道 `lane` 对应 `[10*lane +: 10]`。`CI[lane]` 为各通道独立进位，
`BI` 为四个通道共用的加减控制。

映射较窄的 `$alu` 时，调用方先按原 `A_SIGNED`、`B_SIGNED` 和
`Y_WIDTH` 规则扩展或截断两个操作数，再将结果补零至十位。
两操作数均有符号时采用符号扩展，其余情况采用零扩展。
输出从相应通道的低 `Y_WIDTH` 位读取，包含每一位 `X`、`Y` 和 `CO`。

## 通道算术

各十二位 DSP 段使用以下输入：

```text
A_segment = {0, A_lane, CI_lane & ~BI}
B_segment = {0, B_lane, BI ? ~CI_lane : CI_lane}
```

`BI=0` 时，段内结果为 `2*(A+B+CI)`；`BI=1` 时，段内结果为
`2*(A-B)-(1-CI)`。去除最低编码位后，十位结果分别为
`A+B+CI` 和 `A-B-(1-CI)`，保持原十位补码回绕。

`FOUR12` 分隔四段进位。`X` 由操作数和 `BI` 逐位生成；相邻的和位与
`X` 恢复内部逐位进位，段内最高位与 `BI` 生成第十位进位。
所有 DSP 内部寄存器均旁路，输出保持组合关系。

## 验证结果

`run.py` 从安装的 Yosys 库提取官方 `$alu` 与 `DSP48E1` 功能模型。
模型内容及源码摘要记录在 `measurement.json`。

| 检查 | 范围 | 结果 |
| --- | --- | --- |
| 完整输入 SAT | 四路十位 A/B、四个 CI 和一个 BI 共 85 个输入位全部自由，比较全部 120 个输出位 | 通过 |
| 位宽与符号 SAT | 六组四通道配置，覆盖 1 至 10 位结果、扩展、截断及四种符号参数组合 | 通过 |
| 通道独立性 SAT | 逐一固定被观察通道，允许其他三个通道操作数及 CI 任意变化 | 四个通道均通过 |
| 已知值仿真 | 所有 CI 组合、加减模式、进位和借位边界及随机值 | 52,768 组通过 |
| 四态仿真 | 85 个输入位分别注入 X/Z，以及整个通道的未知操作数与 CI | 5,696 组通过 |
| 实际技术映射 | `$__FPGA_DSP_ALU4` 展开为一个 FOUR12 DSP，内部寄存器数为零 | 通过 |

四态检查对全部 120 个输出执行精确四态比较，包含未知输入对本通道
结果的影响及其他通道的独立结果。公共 `BI` 的未知状态同时参与四个
通道的比较。

## 运行方法

```sh
python3 test/fpga_dsp_alu4/run.py --out build/fpga_dsp_alu4
```

技术映射使用 SystemVerilog 读取设置，再加载
`scripts/fpga/techmap/fpga_dsp_alu4.sv`。脚本同时验证自定义单元类型已
完成替换及 DSP 的 `FOUR12` 参数和寄存器配置。

## 组合路径分析

`netlist_metrics.py` 对固定 ALU 操作模式下的 `FOUR12` 逐位建立依赖。
每个输出位仅连接本十二位通道中不高于它的操作数位，公共控制输入
仍保留依赖。`ONE48` 按同样规则处理一个四十八位通道。

`dependencies.json` 记录官方 DSP 模型的 96 项 SAT 结果：四十八项
覆盖 `ONE48` 的全部输出位，另四十八项覆盖 `FOUR12` 的四个通道。
每项保持被观察的操作数低位不变，允许其他操作数位、进位及
`ALUMODE` 任意取值，检查 `P` 和 `PCOUT` 的逐位结果。

```sh
python3 scripts/fpga/test_dsp_alu_bit_dependencies.py --out build/dsp_alu_dependencies
python3 scripts/fpga/test_netlist_metrics.py
```
