# IS 偏置分组边界

末组地址分别计算完整分组和尾部分组。完整分组的减法只在实际分组计数宽度内传播借位，高位字节独立准备减一结果，再使用低位借位选择；尾部分组通过清除对应的低位得到组首地址。分组掩码逐位并行计算，保留零计数、完整定宽回绕和所有配置编码。

`is_bias_group_base`、`is_bias_last_group_base`、行数状态及初始化周期保持。实现使用普通组合 RTL。

```sh
python3 test/is_bias_group_depth/run_formal.py --out build/is_bias_group/formal
python3 test/is_bias_group_depth/check_four_state.py --out build/is_bias_group/four_state
```

15 组完整输入证明覆盖 4、8、16、32、40、64 位地址计数，以及 1 至 32 位分组行数。四态检查包含 98,304 组输入，参考实现的全部已知输出位保持；位运算可以确定部分原先含 X/Z 的结果。

生产参数下，独立计算的最长寄存器间组合路径为 9 级，参考实现为 17 级；逻辑 LUT 分别为 95 和 51。两侧保持相同的输入及输出寄存器。完整 SoC 的路径单独测量。形式检查、四态检查和映射摘要见 [measurement.json](measurement.json)。
