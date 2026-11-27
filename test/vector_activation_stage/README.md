# 向量激活阶段

`vector_activation_stage` 为向量引擎提供四类限幅结果。量化与平均池化保持各自的输入周期；量化加法在现有舍入保存边沿捕获十位偏移候选、完整激活配置和范围标志，随后完成严格界限比较。

| 控制阶段 | 运算与保存内容 |
| --- | --- |
| `ADD_ROUND_WAIT` 的结束边沿 | 同时保存舍入值加输出偏移的十位结果、原始舍入值的范围条件及激活上下限 |
| `ADD_CLAMP` | 比较已保存的候选与界限，并在结束边沿保存 `serial_clamped_q` |
| `ADD_STORE` | 按原有字节写入和写回条件提交结果 |

数值和配置在同一边沿采样。十位偏移结果保留补码回绕，界限比较保留完整三十二位输入以及未知位的传播。数据寄存器由控制器的计算阶段限定使用时机。

## 检查范围

`run.py` 对比全部 128 位输出。参考模型将原有量化加法结果延迟一拍，其余三类结果保持原有周期。四种宏配置均执行无输入限制的形式等价检查，并分别完成 262,144 次四态比较。

向量引擎采用 16 通道、8 个 PE、64 位总线和 7 个 8 KiB 共享存储体进行集成检查。功能测试通过 616 个用例，覆盖 170,743 个结果；其中量化加法为 143 个用例、135,758 个结果。55 个公开输出连续比较 3,466,547 个周期，保持一致。性能测试通过 40 个用例，55 个公开输出连续比较 1,106,184 个周期，包含 3 个量化加法用例和 28,672 个量化加法结果。

独立量化加法限幅测量使用完整输入和输出寄存器。参考实现为 106 个逻辑 LUT、最长 10 级，阶段实现为 105 个逻辑 LUT、最长 5 级。完整向量引擎中，至 `serial_clamped_q` 的最长路径由 8 级缩短至 6 级。该统计计算展开模块后的完整连接图；150 MHz 的建立和保持裕量由 Vivado 时序报告确定。

## 复现命令

```sh
python3 test/vector_activation_stage/run.py --out build/vector_activation_stage
python3 test/vector_activation_stage/measure.py --scope add --out build/vector_activation_stage_add_map
python3 test/vector_activation_stage/measure.py --scope engine --out build/vector_activation_stage_engine_map
```

参考源码固定为远端提交 `9e3e5d6a6f47befe6c86aceacad7999923206458`。脚本保存源码摘要、形式检查日志摘要、四态比较数量及映射配置。
