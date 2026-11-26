# 算术辅助信号保留属性验证

`add_equal.p_keep_bits` 控制逐位比较结果的保留属性，`p_preserve_bits` 继续控制原有的实现结构。默认值保持既有保留行为。描述符位置模块的四态参考比较采用相同计算，仅关闭其内部逐位结果的保留。

`parallel_prefix_add.p_keep_carry` 控制分段加法中只参与最高输出进位的末组传播节点。该参数不改变完整和值和最高进位的计算。完整四位末组的传播条件只用于其后的输出进位；末组以内的和值使用前面各组及本组的低位传播条件。部分末组原有保留条件为假。

各调用方只在最高进位没有后续使用时关闭对应保留。`requant_group_difference` 将该设置转发到内部加法器，默认继续保留最高进位相关节点。

## 运行方法

```bash
python test/retained_arithmetic/run.py --repo . --out build/retained_arithmetic
python test/descriptor_position_context/run.py --out build/descriptor_position_context
```

第一项比较保留开启和关闭时的完整和值、最高进位及模加相等结果。八组位宽与分段组合分别在普通仿真和 `SYNTHESIS` 配置下进行形式证明及四态事件仿真，输入不附加范围限制。四态仿真覆盖普通数值及操作数、目标值、输入进位中的 `X`、`Z`。

第二项检查描述符位置的保存边沿、配置优先级、有效提交条件及七种行数位宽，保持原有描述符处理周期。
