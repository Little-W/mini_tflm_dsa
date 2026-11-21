# IS 偏置分组边界

末组地址分别计算完整分组和尾部分组。FPGA 综合在 17 至 47 位地址配置下使用一次完整定宽减法计算完整分组起点，并通过 `use_dsp` 属性允许算术资源推断。通用配置采用低位借位与高位独立减一的分组表达式；尾部分组通过清除对应低位得到组首地址。分组掩码逐位并行计算，保留零计数、完整定宽回绕和所有配置编码。

`is_bias_group_base`、`is_bias_last_group_base`、行数状态及初始化周期保持。实现使用普通组合 RTL。

```sh
python3 test/is_bias_group_depth/run_formal.py --out build/is_bias_group/formal
python3 test/is_bias_group_depth/check_four_state.py --strict --out build/is_bias_group/four_state
```

30 组完整输入证明覆盖 FPGA 与通用综合配置、4、8、16、32、40、64 位地址计数，以及 1 至 32 位分组行数。输入未增加限制。事件仿真保留分组表达式，98,304 组含未知值输入通过全部结果位的严格四态比较。

生产参数下，独立计算的最长寄存器间组合路径为 5 级，参考提交为 6 级；逻辑 LUT 分别为 94 和 105，DSP 分别为 2 和 1。两侧均使用相同的输入及输出寄存器，共 94 个触发器。完整 SoC 的路径和目标器件时序单独测量。形式检查、四态检查和映射摘要见 [measurement.json](measurement.json)。
