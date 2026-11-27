# 偏置地址零值及需求选择

矩阵引擎按六位地址分组保存组合零值结果，再直接归并各组；偏置需求模块提前计算帧模式、首末帧和通道地址条件，完整地址非零标志参与末级组合。所有输出保持当周期行为。

## 验证

`run.py` 从生产 `npu_matrix_engine.sv` 提取零值分组和 `npu_bias_presence` 的实际实例连接，证明模块表达式以及地址宽度为 1、16、29、32、33、64 时的完整偏置需求。形式证明不限制输入值，七项检查全部通过。四态仿真穷举独立需求模块的 65,536 种条件组合，并完成六种地址位宽的 393,216 次比较。

```bash
python test/bias_zero_selection/run.py --out /tmp/bias_zero_validation
python test/bias_zero_selection/measure.py \
  --validated-inputs /tmp/bias_zero_validation --out /tmp/bias_zero_measure
```

## 组合路径测量

`measure.py` 提取固定远端提交 `9e3e5d6a6f47befe6c86aceacad7999923206458` 和当前生产表达式，将地址、控制条件及结果分别用寄存器限定，使用与整机相同的 Xilinx 映射过程计算完整组合路径。

| 项目 | 远端参考 | 当前设计 |
| --- | ---: | ---: |
| 逻辑 LUT | 10 | 11 |
| 最长寄存器组合路径 | 5 级 | 3 级 |
| 偏置地址至需求输出 | 5 级 | 3 级 |

生产源码摘要、证明结果和实际映射结果分别保存在 `validation.json` 与 `measurement.json`。组合级数用于检查结构深度，150 MHz 时序需由整机布局布线报告确认。
