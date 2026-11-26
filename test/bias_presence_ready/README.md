# 偏置需求与计算就绪条件

`npu_bias_presence` 并行形成帧执行和直接执行两种模式的偏置需求。当前通道地址的零值结果在最后一级参与选择。控制器同时保存独立的组合条件 `issue_tail_quant_ready`，将计算尾部与量化参数的就绪检查提前完成。

模块不增加时钟周期。偏置基址为零、模式选择、帧首尾条件、控制器可见地址回绕及未知输入的条件选择语义均保持一致。

## 验证

- 对 8 个布尔输入的全部二态组合进行任意输入形式证明。
- 对全部 65,536 种四态组合分别运行通用和 FPGA 模式，合计 131,072 次严格比较。
- 核对矩阵父模块的全部端口连接及其余功能代码。
- 控制器在 6 种寄存器位宽、2 种综合配置下通过 12 项完整状态等价证明，另通过 314,372 次输入发送资格四态比较。

```bash
python3 test/bias_presence_ready/run.py --out /tmp/bias_presence_ready
python3 test/controller_ps_ready/run.py --out /tmp/controller_ready
python3 test/bias_presence_ready/measure.py --out /tmp/bias_presence_mapping
```

## 组合路径测量

测量包含完整 32 位偏置地址检查、模式和帧位置选择、偏置有效条件、计算尾部及量化参数条件，输入和输出均由寄存器限定。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 48 | 50 |
| 最长寄存器间组合路径 | 6 级 | 5 级 |

`measurement.json` 保存实际映射来源、资源统计及连接路径；完整 SoC 单独检查跨模块路径。
