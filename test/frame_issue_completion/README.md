# 矩阵帧完成与输入发送

帧执行、计算尾部、部分和保存及输出完成条件提前形成完成资格。
`frame_command_active` 在最终帧完成选择中参与计算；矩阵控制器分别计算
输入数据和状态资格，任务完成信号在输入发送的最后组合层阻止新的计算组。
所有寄存器更新、握手时刻和任务完成时刻保持不变。

## 验证

`frame_validation.json` 记录实际矩阵引擎完成表达式的无约束组合证明，
并枚举全部十一位控制信号的 `0/1/X/Z` 输入，共 4,194,304 次。
`controller_validation.json` 记录完整控制器状态和公开输出的逐周期等价证明：
`REG_WIDTH` 为 8、16、28、29、32、64，分别检查通用与 FPGA 配置，共十二项。
发送资格额外完成 314,372 次四态比较。

```sh
python test/matrix_frame_complete/run.py --out build/frame_complete_validation
python test/controller_ps_ready/run.py --out build/frame_issue_controller_validation
python test/frame_issue_completion/measure.py --out build/frame_issue_measure
```

## 组合路径测量

测量程序直接读取生产矩阵引擎的完成表达式，并连接完整 `npu_controller`。
控制输入和公开输出均添加测量寄存器；控制器内部状态、计算尾部和发送寄存器保持原样。
组合图检查覆盖所有寄存器输入，ABC9 映射执行功能验证。
参数为 `SIZE=16`、`REG_WIDTH=32`、`BUS_WIDTH=64`、`DATA_WIDTH=16`、`WEIGHT_WIDTH=16`。

| 范围 | 参考提交 `92f722e6` | 当前设计 |
|---|---:|---:|
| 完成表达式和完整控制器的 LUT 数量 | 132 | 135 |
| 所有输入的最长完整寄存器路径 | 8 | 8 |
| `frame_command_active` 到任一寄存器 | 7 | 4 |
| `frame_command_active` 到输入发送输出 | 6 | 2 |

`measurement.json` 保存连接后的完整组合图检查结果、路径、源文件摘要及映射摘要。
上述数值用于比较 RTL 结构；150 MHz 的最终建立与保持时间仍由目标器件布局布线报告确认。
