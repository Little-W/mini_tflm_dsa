# 权重列尾的成对比较

控制器使用 `increment_equal` 同时检查相邻两位的加一关系，并独立归并全部比较结果。列位置与目标列数均保留完整计数位宽。`p_preserve_pairs` 只影响组合结构的保留方式，默认配置保持普通推断形式。

每个相邻位组与原有模加等式具有相同的四态运算关系，因此已知、X 和 Z 输入均使用同一组表达式。状态更新、尾部有效数量及描述符比较结果保持逐周期一致。

## 检查

```bash
python3 test/conv_descriptor_timing/check_increment_equal.py --out build/kernel_column_pairs/increment
python3 test/kernel_completion/run.py --reference c1c81d64 --out build/kernel_column_pairs/control
python3 test/kernel_port_selection/measure.py --reference c1c81d64 --out build/kernel_column_pairs/measurement
```

1 至 64 位的 13 种位宽同时检查两种结构配置，任意输入形式证明通过；每种位宽执行 16,384 组四态输入，共 425,984 次结果比较。完整控制器在 8 种分块、计数和编译配置下比较全部共有状态和公开输出，全部外部输入自由变化。

16 个元素一块、29 位计数、64 位总线的完整加载器使用 2,888 个逻辑 LUT，较参考实现减少 33 个。列位置到描述符比较寄存器的实际路径从 11 级缩短为 9 级，完整加载器最长路径为 11 级。完整 SoC 的路径和资源使用整机报告。

`increment_validation.json` 和 `control_validation.json` 保存功能检查结果，`measurement.json` 保存完整模块的资源和路径。
