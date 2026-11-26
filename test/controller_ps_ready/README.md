# 偏置、部分和就绪与输入发送资格

`npu_controller` 并行形成输入数据资格、计算尾部与量化参数资格，以及控制状态资格。`npu_ia_issue_select` 提前归并这些条件，在最终组合层加入偏置有效、部分和就绪和输出容量条件，直接产生 `send_ia_trigger`。偏置基址为零或当前计算组使用部分和回放时，计算组可直接继续。状态更新、握手周期和四态逻辑保持相同。

## 完整控制器测量

参照提交为 `ee8e2fc6`。完整模块综合采用 `REG_WIDTH=32`、`SIZE=16`、`BUS_WIDTH=64`、`DATA_WIDTH=8`、`WEIGHT_WIDTH=8`，使用相同的 `physical-cost` 映射设置：最大 LUT 输入数 8、布线延迟参数 300 ps、目标周期 6,667 ps。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 127 | 128 |
| 全部寄存器路径最大级数 | 4 | 4 |
| `ps_frame_ready` 到 `send_ia_trigger` | 1 | 1 |
| `fifo_full_flag` 到 `send_ia_trigger` | 1 | 1 |
| `bias_valid` 到 `send_ia_trigger` | 2 | 1 |
| `bias_sleep` 到 `send_ia_trigger` | 2 | 1 |

端口间级数只统计控制器内部连接，完整 SoC 中的上游和下游组合逻辑由整机报告统计。

## 功能检查

完整控制器在 8、16、28、29、32、64 位寄存器接口下分别验证通用与 FPGA 编译方式，共 12 项状态和公开输出等价证明。所有外部输入自由变化。

测试直接提取实际控制器的相关表达式，另行完成两项任意输入组合证明和 314,372 次四态比较，包含控制状态、数据、偏置、计算尾部、驻留权重、输出缓冲及部分和就绪条件。

```sh
python test/controller_ps_ready/run.py --out build/controller_ps_ready/validation
python test/controller_ps_ready/measure.py --out build/controller_ps_ready/mapping
```

`validation.json` 保存参数与源码摘要，`measurement.json` 保存完整资源统计及实际连接路径。
